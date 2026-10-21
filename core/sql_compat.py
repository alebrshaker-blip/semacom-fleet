"""Translate the SQLite-flavoured SQL used across the project to PostgreSQL."""
import re

# Splits SQL into string literals, quoted identifiers, comments and plain code.
_SEGMENT_RE = re.compile(
    r"""('(?:[^']|'')*')|("(?:[^"]|"")*")|(--[^\n]*)|(/\*.*?\*/)""", re.S
)

_TRIGGER_RE = re.compile(
    r"""^\s*CREATE\s+TRIGGER\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>\w+)\s+
        (?P<when>BEFORE|AFTER)\s+(?P<event>INSERT|UPDATE|DELETE)
        (?:\s+OF\s+(?P<cols>[\w,\s]+?))?\s+ON\s+(?P<table>\w+)\s+
        (?:FOR\s+EACH\s+ROW\s+)?WHEN\s*(?P<cond>.*?)\s*
        BEGIN\s+SELECT\s+RAISE\s*\(\s*ABORT\s*,\s*'(?P<msg>(?:[^']|'')*)'\s*\)\s*;\s*END\s*;?\s*$""",
    re.S | re.I | re.X,
)

_TS_TEXT = "to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"
_NOW_FN_RE = re.compile(
    r"\b(datetime|date)\(\s*'now'\s*(?:,\s*'([+-]?\d+)\s+(\w+?)s?'\s*)?\)", re.I
)
_PRAGMA_TABLE_INFO_RE = re.compile(
    r"^\s*PRAGMA\s+table_info\(\s*['\"`]?([\w.]+)['\"`]?\s*\)\s*;?\s*$", re.I
)

_SQLSTATE_UNIQUE = "23505"


def _now_fn(match):
    kind, amount, unit = match.group(1).lower(), match.group(2), match.group(3)
    expr = "(now() AT TIME ZONE 'UTC')"
    if amount:
        expr = f"({expr} + interval '{int(amount)} {unit.lower()}')"
    fmt = "YYYY-MM-DD HH24:MI:SS" if kind == "datetime" else "YYYY-MM-DD"
    return f"to_char({expr}, '{fmt}')"


def split_statements(script):
    """Split a script on ';' outside quotes/comments, keeping CREATE TRIGGER bodies whole."""
    statements, current, pos = [], [], 0
    pieces = []
    for match in _SEGMENT_RE.finditer(script):
        pieces.append((False, script[pos:match.start()]))
        pieces.append((True, match.group(0)))
        pos = match.end()
    pieces.append((False, script[pos:]))

    for is_literal, text in pieces:
        if is_literal:
            current.append(text)
            continue
        parts = text.split(";")
        for index, part in enumerate(parts):
            current.append(part)
            if index == len(parts) - 1:
                break
            statement = "".join(current)
            if re.match(r"\s*CREATE\s+TRIGGER\b", statement, re.I) and not re.search(
                r"\bEND\s*$", statement, re.I
            ):
                current.append(";")
                continue
            statements.append(statement.strip())
            current = []
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return [s for s in statements if s]


def _translate_trigger(sql):
    match = _TRIGGER_RE.match(sql)
    if not match:
        raise NotImplementedError(f"Unsupported trigger definition: {sql[:80]}")
    name, table = match.group("name"), match.group("table")
    event = match.group("event").upper()
    if match.group("cols"):
        event += " OF " + ", ".join(c.strip() for c in match.group("cols").split(","))
    function = (
        f"CREATE OR REPLACE FUNCTION {name}_fn() RETURNS trigger AS $fn$ BEGIN "
        f"IF ({match.group('cond')}) THEN "
        f"RAISE EXCEPTION USING MESSAGE = '{match.group('msg')}', ERRCODE = '{_SQLSTATE_UNIQUE}'; "
        f"END IF; RETURN NEW; END; $fn$ LANGUAGE plpgsql"
    )
    return [
        function,
        f"DROP TRIGGER IF EXISTS {name} ON {table}",
        f"CREATE TRIGGER {name} {match.group('when').upper()} {event} ON {table} "
        f"FOR EACH ROW EXECUTE PROCEDURE {name}_fn()",
    ]


def _translate_code(code, is_ddl, has_params):
    code = re.sub(r"\bLIKE\b", "ILIKE", code, flags=re.I)
    code = re.sub(r"(\w+)\s+COLLATE\s+NOCASE\b", r"LOWER(\1)", code, flags=re.I)
    if is_ddl:
        code = re.sub(
            r"\bINTEGER\s+PRIMARY\s+KEY(\s+AUTOINCREMENT)?\b",
            "SERIAL PRIMARY KEY",
            code,
            flags=re.I,
        )
        code = re.sub(r"\bREAL\b", "DOUBLE PRECISION", code)
        code = re.sub(r"\b(?:DATETIME|TIMESTAMP|DATE)\b", "TEXT", code)
        code = re.sub(r"\bBLOB\b", "BYTEA", code)
        code = re.sub(r"\bCURRENT_(?:TIMESTAMP|DATE)\b", _TS_TEXT, code)
        code = re.sub(
            r"\bADD\s+COLUMN\s+(?!IF\s+NOT\s+EXISTS)",
            "ADD COLUMN IF NOT EXISTS ",
            code,
            flags=re.I,
        )
    if has_params:
        code = code.replace("%", "%%").replace("?", "%s")
    return code


def translate(sql, has_params=False):
    """Return the list of PostgreSQL statements equivalent to one SQLite statement."""
    sql = sql.strip()
    while sql.startswith(("--", "/*")):
        end = sql.find("\n") if sql.startswith("--") else sql.find("*/") + 1
        sql = sql[end + 1:].lstrip() if end >= 0 else ""
    if not sql:
        return []

    pragma = _PRAGMA_TABLE_INFO_RE.match(sql)
    if pragma:
        table = pragma.group(1).split(".")[-1].replace("'", "''")
        return [
            "SELECT ordinal_position - 1 AS cid, column_name AS name, data_type AS type, "
            "CASE WHEN is_nullable = 'NO' THEN 1 ELSE 0 END AS notnull, "
            "column_default AS dflt_value, 0 AS pk "
            "FROM information_schema.columns "
            f"WHERE table_schema = current_schema() AND table_name = '{table}' "
            "ORDER BY ordinal_position"
        ]
    if re.match(r"PRAGMA\b", sql, re.I):
        return ["SELECT 1 WHERE FALSE"]
    # Connections are already inside a transaction; SQLite's write-lock hint is a no-op here.
    if re.match(r"BEGIN(\s+(IMMEDIATE|EXCLUSIVE|DEFERRED))?(\s+TRANSACTION)?\s*;?\s*$", sql, re.I):
        return ["SELECT 1 WHERE FALSE"]
    if re.match(r"CREATE\s+TRIGGER\b", sql, re.I):
        return _translate_trigger(sql)

    sql = _NOW_FN_RE.sub(_now_fn, sql)
    is_ddl = bool(re.match(r"(CREATE\s+TABLE|ALTER\s+TABLE)\b", sql, re.I))

    ignore = bool(re.match(r"INSERT\s+OR\s+IGNORE\s+INTO\b", sql, re.I))
    if ignore:
        sql = re.sub(r"^INSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", sql, flags=re.I)
    if re.match(r"INSERT\s+OR\s+REPLACE\b", sql, re.I):
        raise NotImplementedError("INSERT OR REPLACE needs an explicit ON CONFLICT clause.")

    out, pos = [], 0
    for match in _SEGMENT_RE.finditer(sql):
        out.append(_translate_code(sql[pos:match.start()], is_ddl, has_params))
        literal = match.group(0)
        if has_params and not match.group(3) and not match.group(4):
            literal = literal.replace("%", "%%")
        out.append(literal)
        pos = match.end()
    out.append(_translate_code(sql[pos:], is_ddl, has_params))
    sql = "".join(out).rstrip().rstrip(";")

    if ignore:
        sql += " ON CONFLICT DO NOTHING"
    return [sql]

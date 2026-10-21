"""Small helpers shared by the ORM-backed services."""


def to_float(value, default=None):
    """Form values arrive as strings; '' and junk become `default` instead of a DB error."""
    if value is None:
        return default
    text_value = str(value).strip().replace(",", "")
    if not text_value:
        return default
    try:
        return float(text_value)
    except ValueError:
        return default


def to_int(value, default=None):
    number = to_float(value)
    return default if number is None else int(number)


def blank_to_none(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None

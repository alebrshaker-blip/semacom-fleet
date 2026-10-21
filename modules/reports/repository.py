"""ORM data access for the report-owned tables (approved_documents, generated_reports)."""
import json
import uuid

from sqlalchemy import and_, delete, or_, select, update

from core.database import get_session
from modules.reports.models.report_orm import ApprovedDocument, GeneratedReport


def _latest_finalized_stmt(doc_type, item_ids):
    ids = [str(i) for i in item_ids if i is not None]
    return (
        select(ApprovedDocument)
        .where(
            ApprovedDocument.doc_type == doc_type,
            ApprovedDocument.item_id.in_(ids),
            ApprovedDocument.is_finalized == 1,
        )
        .order_by(ApprovedDocument.id.desc())
        .limit(1)
    )


def find_finalized(doc_type, item_ids, session=None):
    """Latest finalized document of `doc_type` whose item_id is any of `item_ids`."""
    if session is not None:
        row = session.scalars(_latest_finalized_stmt(doc_type, item_ids)).first()
        return row.to_dict() if row else None
    with get_session() as own:
        return find_finalized(doc_type, item_ids, own)


def lookup_approved_report(item_id, doc_type, approval_token=None):
    """(doc_number, qr_code_path) of the latest finalized report, or (None, None)."""
    stmt = _latest_finalized_stmt(doc_type, [item_id])
    if approval_token:
        stmt = stmt.where(ApprovedDocument.approval_token == approval_token)
    with get_session() as session:
        row = session.scalars(stmt).first()
        return (row.doc_number, row.qr_code_path) if row else (None, None)


def get_by_token(approval_token):
    with get_session() as session:
        row = session.scalars(
            select(ApprovedDocument).where(ApprovedDocument.approval_token == approval_token)
        ).first()
        return row.to_dict() if row else None


def get_document(doc_number):
    with get_session() as session:
        row = session.scalars(
            select(ApprovedDocument).where(ApprovedDocument.doc_number == doc_number)
        ).first()
        return row.to_dict() if row else None


def token_is_valid(doc_number, access_token):
    with get_session() as session:
        return session.scalars(
            select(ApprovedDocument.id).where(
                ApprovedDocument.doc_number == doc_number,
                ApprovedDocument.approval_token == access_token,
                ApprovedDocument.is_finalized == 1,
            )
        ).first() is not None


def latest_document_path(doc_type, item_id):
    with get_session() as session:
        return session.scalars(
            select(ApprovedDocument.file_path)
            .where(ApprovedDocument.doc_type == doc_type, ApprovedDocument.item_id == str(item_id))
            .order_by(ApprovedDocument.id.desc())
            .limit(1)
        ).first()


def generated_report_path(doc_number, module_name):
    with get_session() as session:
        return session.scalars(
            select(GeneratedReport.local_report_path)
            .where(GeneratedReport.doc_number == doc_number, GeneratedReport.module_name == module_name)
            .order_by(GeneratedReport.id.desc())
            .limit(1)
        ).first()


def file_path_for_number(doc_number):
    with get_session() as session:
        return session.scalars(
            select(ApprovedDocument.file_path).where(ApprovedDocument.doc_number == doc_number)
        ).first()


def set_final_pdf(doc_number, pdf_path):
    with get_session() as session:
        session.execute(
            update(ApprovedDocument)
            .where(ApprovedDocument.doc_number == doc_number)
            .values(final_pdf_path=pdf_path)
        )
        session.execute(
            update(GeneratedReport)
            .where(GeneratedReport.doc_number == doc_number)
            .values(final_pdf_path=pdf_path, local_pdf_path=pdf_path)
        )


# --- helpers that participate in a caller-managed transaction ---------------

def add_approved_document(session, *, doc_number, doc_type, item_id, file_path,
                          approval_token, final_pdf_path, qr_code_path):
    session.add(ApprovedDocument(
        doc_number=doc_number, doc_type=doc_type, item_id=str(item_id), file_path=file_path,
        approval_token=approval_token, is_finalized=1, final_pdf_path=final_pdf_path,
        reference_number=doc_number, qr_code_path=qr_code_path,
    ))
    session.flush()


def add_generated_report(session, *, doc_number, module_name, report_type, title,
                         template_key, parameters, report_path, qr_path):
    session.add(GeneratedReport(
        doc_uuid=str(uuid.uuid4()), doc_number=doc_number, module_name=module_name,
        report_type=report_type, title=title, template_key=template_key,
        parameters_json=json.dumps(parameters, ensure_ascii=False),
        local_report_path=report_path, local_qr_path=qr_path,
    ))
    session.flush()


def finalize_generated_report(session, doc_number, final_pdf_path, qr_url):
    session.execute(
        update(GeneratedReport)
        .where(GeneratedReport.doc_number == doc_number)
        .values(
            local_pdf_path=final_pdf_path, is_finalized=1, final_pdf_path=final_pdf_path,
            reference_number=doc_number, qr_code_path=qr_url,
        )
    )


def pop_documents(session, doc_type, item_id):
    """Delete the documents of one item; return [(stored_path, kind)] for file cleanup.

    kind is 'report' or 'qr' so callers can restrict deletion to the right folder.
    """
    documents = session.scalars(
        select(ApprovedDocument).where(
            ApprovedDocument.doc_type == doc_type, ApprovedDocument.item_id == str(item_id)
        )
    ).all()
    numbers = [d.doc_number for d in documents]
    generated = session.scalars(
        select(GeneratedReport).where(GeneratedReport.doc_number.in_(numbers))
    ).all() if numbers else []

    paths = []
    for d in documents:
        paths += [(d.file_path, 'report'), (d.final_pdf_path, 'report'), (d.qr_code_path, 'qr')]
    for g in generated:
        paths += [
            (g.local_report_path, 'report'), (g.local_pdf_path, 'report'),
            (g.final_pdf_path, 'report'), (g.local_qr_path, 'qr'), (g.qr_code_path, 'qr'),
        ]
    if numbers:
        session.execute(delete(GeneratedReport).where(GeneratedReport.doc_number.in_(numbers)))
        session.execute(delete(ApprovedDocument).where(ApprovedDocument.doc_number.in_(numbers)))
    return paths

from sqlalchemy import Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base, DictMixin

_NOW_TEXT = text("to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')")


class DocumentSequence(DictMixin, Base):
    __tablename__ = "document_sequence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    last_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class ApprovedDocument(DictMixin, Base):
    __tablename__ = "approved_documents"
    __table_args__ = (
        Index(
            "idx_approved_documents_approval_token", "approval_token",
            unique=True, postgresql_where=text("approval_token IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_number: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    doc_type: Mapped[str] = mapped_column(Text, nullable=False)
    item_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str | None] = mapped_column(Text, server_default=_NOW_TEXT)
    file_path: Mapped[str | None] = mapped_column(Text)
    approval_token: Mapped[str | None] = mapped_column(Text)
    is_finalized: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    final_pdf_path: Mapped[str | None] = mapped_column(Text)
    reference_number: Mapped[str | None] = mapped_column(Text)
    qr_code_path: Mapped[str | None] = mapped_column(Text)


class GeneratedReport(DictMixin, Base):
    __tablename__ = "generated_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_uuid: Mapped[str | None] = mapped_column(Text, unique=True)
    doc_number: Mapped[str | None] = mapped_column(Text, unique=True)
    module_name: Mapped[str | None] = mapped_column(Text)
    report_type: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    template_key: Mapped[str | None] = mapped_column(Text)
    parameters_json: Mapped[str | None] = mapped_column(Text)
    local_pdf_path: Mapped[str | None] = mapped_column(Text)
    local_report_path: Mapped[str | None] = mapped_column(Text)
    local_qr_path: Mapped[str | None] = mapped_column(Text)
    drive_file_id: Mapped[str | None] = mapped_column(Text)
    drive_web_url: Mapped[str | None] = mapped_column(Text)
    sync_status: Mapped[str | None] = mapped_column(Text, server_default="pending")
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text, server_default=_NOW_TEXT)
    is_finalized: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    final_pdf_path: Mapped[str | None] = mapped_column(Text)
    reference_number: Mapped[str | None] = mapped_column(Text)
    qr_code_path: Mapped[str | None] = mapped_column(Text)


class ReportTemplate(DictMixin, Base):
    __tablename__ = "report_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    module_name: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    template_path: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[int | None] = mapped_column(Integer, server_default="1")

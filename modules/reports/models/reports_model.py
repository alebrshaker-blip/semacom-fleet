from sqlalchemy import desc, select

from core.database import get_session
from modules.reports.models.report_orm import (
    ApprovedDocument,
    GeneratedReport,
    ReportTemplate,
)


class ReportsModel:
    def get_active_templates(self):
        with get_session() as session:
            rows = session.scalars(
                select(ReportTemplate).where(ReportTemplate.is_active == 1)
            ).all()
            return [row.to_dict() for row in rows]

    def get_template_by_key(self, template_key):
        with get_session() as session:
            row = session.scalars(
                select(ReportTemplate).where(ReportTemplate.template_key == template_key)
            ).first()
            return row.to_dict() if row else None

    def get_all_generated_reports(self):
        with get_session() as session:
            rows = session.scalars(
                select(GeneratedReport).order_by(desc(GeneratedReport.created_at))
            ).all()
            return [row.to_dict() for row in rows]

    def get_finalized_report_by_number(self, reference_number):
        with get_session() as session:
            row = session.scalars(
                select(ApprovedDocument).where(
                    ApprovedDocument.doc_number == reference_number,
                    ApprovedDocument.is_finalized == 1,
                )
            ).first()
            return row.to_dict() if row else None

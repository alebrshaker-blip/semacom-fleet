import logging
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr

from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError

from core.database import get_session, init_orm_schema, now_text
from modules.notifications.models.notifications_orm import EmailDeliveryRun
from modules.notifications.services.notifications_service import NotificationsService
from modules.settings import repository
from modules.settings.services.email_service import (
    EmailConfigurationError,
    get_email_setting,
    send_email,
)


logger = logging.getLogger(__name__)

_CLAIM_LOCK = 7420002


def _ensure_delivery_table():
    init_orm_schema()


def _parse_utc(value):
    try:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


def _claim_weekly_run(delivery_key):
    with get_session() as session:
        session.execute(select(func.pg_advisory_xact_lock(_CLAIM_LOCK)))
        run = session.get(EmailDeliveryRun, delivery_key)
        now = datetime.now(timezone.utc)
        if run is not None:
            if run.status == 'sent':
                return False
            if run.status == 'failed' and run.completed_at:
                if now - _parse_utc(run.completed_at) < timedelta(hours=1):
                    return False
            if run.status == 'sending':
                if now - _parse_utc(run.started_at) < timedelta(minutes=15):
                    return False
            run.status = 'sending'
            run.started_at = now_text()
            run.completed_at = None
        else:
            session.add(EmailDeliveryRun(
                delivery_key=delivery_key, status='sending', started_at=now_text(),
            ))
        return True


def _complete_weekly_run(delivery_key, status):
    with get_session() as session:
        session.execute(
            update(EmailDeliveryRun)
            .where(EmailDeliveryRun.delivery_key == delivery_key)
            .values(status=status, completed_at=now_text())
        )


def _active_admin_emails():
    rows = [(email,) for email in repository.list_active_user_emails('admin')]

    emails = []
    for (email,) in rows:
        address = parseaddr(str(email).strip())[1]
        if re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', address):
            if address.lower() not in {item.lower() for item in emails}:
                emails.append(address)
        else:
            logger.warning('Skipping administrator with invalid notification email address')
    return emails


def send_due_weekly_digest():
    now = datetime.now().astimezone()
    if get_email_setting('email_fleet_digest_enabled', '1') != '1':
        return
    if get_email_setting('smtp_enabled', '0') != '1':
        return
    try:
        digest_day = int(get_email_setting('email_fleet_digest_day', '0'))
        digest_hour = int(get_email_setting('email_fleet_digest_hour', '9'))
    except (TypeError, ValueError):
        logger.error('Invalid weekly fleet email schedule settings')
        return
    if not 0 <= digest_day <= 6 or not 0 <= digest_hour <= 23:
        logger.error('Weekly fleet email schedule settings are outside the valid range')
        return

    days_since_digest_day = (now.weekday() - digest_day) % 7
    scheduled_date = now.date() - timedelta(days=days_since_digest_day)
    scheduled_at = datetime.combine(
        scheduled_date,
        datetime.min.time(),
        tzinfo=now.tzinfo,
    ).replace(hour=digest_hour)
    if now < scheduled_at:
        return

    iso_year, iso_week, _ = scheduled_date.isocalendar()
    delivery_key = f'fleet-alert-weekly:{iso_year}-W{iso_week:02d}'
    _ensure_delivery_table()
    if not _claim_weekly_run(delivery_key):
        return

    try:
        recipients = _active_admin_emails()
        notifications = NotificationsService.get_notifications('email-weekly-digest')
        if not recipients or not notifications:
            _complete_weekly_run(delivery_key, 'sent')
            return

        lines = [
            'ملخص أسبوعي بتنبيهات المركبات والصيانة في نظام SEMACOM:',
            '',
        ]
        for notification in notifications[:100]:
            lines.extend((
                f"- {notification['category_label']}: {notification['title']}",
                f"  {notification['message']}",
                '',
            ))
        if len(notifications) > 100:
            lines.append(f'تم إظهار أول 100 تنبيه من أصل {len(notifications)}.')

        send_email(
            f'ملخص تنبيهات المركبات والمعدات الأسبوعي - SEMACOM - {scheduled_date.isoformat()}',
            '\n'.join(lines),
            recipients[0],
            bcc=recipients[1:],
        )
        _complete_weekly_run(delivery_key, 'sent')
        logger.info('Sent weekly fleet notification digest to %s administrator(s)', len(recipients))
    except (EmailConfigurationError, SQLAlchemyError, OSError, TimeoutError, smtplib.SMTPException):
        _complete_weekly_run(delivery_key, 'failed')
        logger.exception('Unable to send the weekly fleet notification digest')


def start_weekly_digest_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        send_due_weekly_digest,
        trigger='interval',
        minutes=15,
        id='weekly-fleet-alert-digest',
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(),
    )
    scheduler.start()
    return scheduler

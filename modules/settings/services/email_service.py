import re
import smtplib
import ssl
from modules.settings import repository
from config import settings
import os
from email.message import EmailMessage
from email.utils import formataddr
from urllib.parse import urlsplit



class EmailConfigurationError(ValueError):
    pass


def get_email_setting(key, default=None):
    return repository.get_setting(key, default)


def get_public_base_url():
    row_value = repository.get_setting('app_public_url')

    base_url = str(row_value or settings.PUBLIC_BASE_URL or '').strip().rstrip('/')
    try:
        parsed_url = urlsplit(base_url)
        public_port = parsed_url.port
    except ValueError as error:
        raise EmailConfigurationError('منفذ الرابط العام للنظام غير صالح') from error
    if (
        parsed_url.scheme not in {'http', 'https'}
        or not parsed_url.hostname
        or not re.fullmatch(r'[A-Za-z0-9.-]+', parsed_url.hostname)
        or (public_port is not None and not 1 <= public_port <= 65535)
        or parsed_url.username
        or parsed_url.password
        or parsed_url.path
        or parsed_url.query
        or parsed_url.fragment
        or any(char in base_url for char in '\r\n')
        or (
            settings.IS_PRODUCTION
            and parsed_url.scheme != 'https'
        )
    ):
        raise EmailConfigurationError('عيّن الرابط العام للنظام من تبويب البيانات العامة أولاً')
    return base_url


def _load_smtp_settings():
    return repository.get_settings((
        'smtp_server', 'smtp_port', 'smtp_email', 'smtp_username', 'smtp_password',
        'smtp_from_name', 'smtp_security', 'smtp_use_tls', 'smtp_enabled',
    ))


def send_email(subject, body, recipients, bcc=None, allow_when_disabled=False):
    settings = _load_smtp_settings()
    if not settings.get('smtp_server') or not settings.get('smtp_email'):
        raise EmailConfigurationError('أكمل خادم البريد وبريد الإرسال أولاً')
    if settings.get('smtp_enabled', '0') != '1' and not allow_when_disabled:
        raise EmailConfigurationError('إرسال البريد متوقف من الإعدادات')
    sender = str(settings.get('smtp_email') or '').strip()
    username = str(settings.get('smtp_username') or sender).strip()
    server = str(settings.get('smtp_server') or '').strip()
    password = str(settings.get('smtp_password') or '')
    from_name = str(settings.get('smtp_from_name') or 'SEMACOM')
    try:
        port = int(settings.get('smtp_port') or 0)
    except (TypeError, ValueError) as error:
        raise EmailConfigurationError('منفذ خادم البريد غير صالح') from error

    security = settings.get('smtp_security')
    if not security:
        security = 'starttls' if str(settings.get('smtp_use_tls', '1')) == '1' else ''
    if not server or len(server) > 253 or not re.fullmatch(r'[A-Za-z0-9.-]+', server):
        raise EmailConfigurationError('خادم البريد غير صالح')
    if not 1 <= port <= 65535:
        raise EmailConfigurationError('منفذ خادم البريد غير صالح')
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', sender):
        raise EmailConfigurationError('عنوان بريد الإرسال غير صالح')
    if security not in {'starttls', 'ssl'}:
        raise EmailConfigurationError('اختر تشفير STARTTLS أو SSL')
    if len(from_name) > 120 or any(char in from_name for char in '\r\n'):
        raise EmailConfigurationError('اسم مرسل البريد غير صالح')

    to_recipients = [recipients] if isinstance(recipients, str) else list(recipients)
    bcc_recipients = [] if bcc is None else ([bcc] if isinstance(bcc, str) else list(bcc))
    all_recipients = to_recipients + bcc_recipients
    if not to_recipients or any(
        not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', str(address).strip())
        for address in all_recipients
    ):
        raise EmailConfigurationError('عنوان البريد المستلم غير صالح')

    message = EmailMessage()
    message['Subject'] = ' '.join(str(subject).splitlines())
    message['From'] = formataddr((from_name, sender))
    message['To'] = ', '.join(str(address).strip() for address in to_recipients)
    if bcc_recipients:
        message['Bcc'] = ', '.join(str(address).strip() for address in bcc_recipients)
    message.set_content(body)

    context = ssl.create_default_context()
    if security == 'ssl':
        with smtplib.SMTP_SSL(server, port, timeout=15, context=context) as smtp:
            if password:
                smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(server, port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            if password:
                smtp.login(username, password)
            smtp.send_message(message)

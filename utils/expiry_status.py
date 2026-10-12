from datetime import date, datetime


def get_expiry_status(expiry_value, active_label, warning_label, expired_label, today=None):
    if not expiry_value:
        return "غير محدد"

    value = str(expiry_value).strip()
    try:
        try:
            expiry_date = date.fromisoformat(value[:10])
        except ValueError:
            expiry_date = datetime.fromisoformat(value).date()
    except ValueError:
        return "غير محدد"

    days_remaining = (expiry_date - (today or date.today())).days
    if days_remaining < 0:
        return expired_label
    if days_remaining < 30:
        return warning_label
    return active_label

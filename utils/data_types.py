import unicodedata


SQLITE_INTEGER_MAX = 9_223_372_036_854_775_807


def parse_non_negative_integer(value, field_label, *, required=False, minimum=0):
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError(f'حقل {field_label} مطلوب.')
        return None

    if isinstance(value, bool):
        raise ValueError(f'يجب إدخال {field_label} كعدد صحيح.')

    text = str(value).strip()
    try:
        normalized = ''.join(
            str(unicodedata.digit(character))
            if unicodedata.category(character) == 'Nd'
            else character
            for character in text
        )
        if not normalized.isascii() or not normalized.isdecimal():
            raise ValueError
        parsed = int(normalized)
    except (TypeError, ValueError):
        raise ValueError(f'يجب إدخال {field_label} كعدد صحيح موجب أو صفر.') from None

    if parsed < minimum:
        if minimum == 1:
            raise ValueError(f'يجب أن تكون قيمة {field_label} أكبر من صفر.')
        raise ValueError(f'لا يمكن أن تكون قيمة {field_label} سالبة.')
    if parsed > SQLITE_INTEGER_MAX:
        raise ValueError(f'قيمة {field_label} تتجاوز الحد الذي تدعمه قاعدة البيانات.')
    return parsed

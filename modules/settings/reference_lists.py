import json

from modules.settings import repository


REFERENCE_LISTS = {
    "vehicle_archive_reasons": {
        "label": "أسباب إخراج المركبات من الخدمة",
        "setting_key": "lookup_vehicle_archive_reasons",
        "defaults": ["بيع", "تلف أو عدم صلاحية", "فقدان", "أخرى"],
    },
    "vehicle_ownership": {
        "label": "ملكية المركبة",
        "setting_key": "lookup_vehicle_ownership",
        "defaults": ["شركة سيماكم", "شركة الذئب العربي", "شركة نبض", "شركة تالا", "اجار", "جهة خارجية"],
    },
    "insurance_types": {
        "label": "أنواع التأمين",
        "setting_key": "lookup_insurance_types",
        "defaults": ["شامل", "ضد الغير", "أخرى"],
    },
    "accident_types": {
        "label": "أنواع الحوادث",
        "setting_key": "lookup_accident_types",
        "defaults": ["صدم", "اصطدام", "انقلاب", "حت / احتكاك", "أخرى"],
    },
    "accident_closure_reasons": {
        "label": "أسباب إقفال الحوادث",
        "setting_key": "lookup_accident_closure_reasons",
        "defaults": ["تم الإصلاح والتسوية", "تعويض تأميني", "تحمل السائق", "حفظ لعدم الأهمية"],
    },
    "violation_issuers": {
        "label": "جهات إصدار المخالفات",
        "setting_key": "lookup_violation_issuers",
        "defaults": ["مرور", "ساهر", "أمن الطرق", "أخرى"],
    },
    "violation_statuses": {
        "label": "حالات المخالفات",
        "setting_key": "lookup_violation_statuses",
        "defaults": ["معلقة", "حتمية", "قيد الاعتراض"],
    },
    "violation_closure_reasons": {
        "label": "أسباب إقفال المخالفات",
        "setting_key": "lookup_violation_closure_reasons",
        "defaults": ["مسددة", "مسحوبة", "معفية", "قيد الاعتراض"],
    },
    "handover_purposes": {
        "label": "أغراض الاستلام والتسليم",
        "setting_key": "lookup_handover_purposes",
        "defaults": ["صرف", "مهمة عمل", "أخرى"],
    },
    "handover_fuel_levels": {
        "label": "مستويات الوقود",
        "setting_key": "lookup_handover_fuel_levels",
        "defaults": ["ممتلئ (Full)", "3/4 ثلاثة ارباع", "1/2 نصف", "1/4 ربع", "فارغ (Empty)"],
    },
    "store_categories": {
        "label": "تصنيفات أصناف المستودع",
        "setting_key": "store_categories",
        "defaults": ["قطع غيار محركات", "نظام الفرامل", "زيوت ومحروقات", "عُدد وأدوات ورشة", "فلترات وسيور"],
    },
    "store_units": {
        "label": "وحدات قياس أصناف المستودع",
        "setting_key": "lookup_store_units",
        "defaults": ["قطعة", "لتر", "طقم", "علبة", "متر"],
    },
    "external_workshops": {
        "label": "الورش الخارجية المعتمدة",
        "setting_key": "external_workshops",
        "defaults": ["ورشة المحرك الذهبي", "مركز الفحص الشامل", "ورشة الهيدروليك الوطنية"],
    },
    "maintenance_types": {
        "label": "أنواع الصيانة الداخلية",
        "setting_key": "lookup_maintenance_types",
        "defaults": ["تصحيحية", "وقائية", "طارئة", "دورية", "تعديل", "أخرى"],
    },
    "external_maintenance_types": {
        "label": "أنواع الصيانة الخارجية",
        "setting_key": "lookup_external_maintenance_types",
        "defaults": ["تصحيحية", "وقائية", "طارئة", "حوادث", "تأمين", "أخرى"],
    },
    "maintenance_severities": {
        "label": "درجات خطورة الصيانة",
        "setting_key": "lookup_maintenance_severities",
        "defaults": ["منخفضة", "متوسطة", "عالية", "خطيرة"],
    },
    "emergency_severities": {
        "label": "درجات خطورة البلاغات الطارئة",
        "setting_key": "lookup_emergency_severities",
        "defaults": ["لا يوجد", "منخفضة", "متوسطة", "عالية", "حرجة"],
    },
    "maintenance_closure_reasons": {
        "label": "أسباب إقفال أوامر الصيانة الداخلية",
        "setting_key": "lookup_maintenance_closure_reasons",
        "defaults": ["تمت المعالجة كلياً", "تمت المعالجة جزئياً", "تم الإلغاء لعدم الحاجة", "تحويل لورشة خارجية"],
    },
    "external_maintenance_closure_reasons": {
        "label": "أسباب إقفال أوامر الصيانة الخارجية",
        "setting_key": "lookup_external_maintenance_closure_reasons",
        "defaults": ["تم الاصلاح بالكامل واستلام المركبة", "تم الاصلاح جزئياً", "تعذر الاصلاح لعدم توفر قطع الغيار", "سحب المركبة لورشة أخرى", "إلغاء أمر الصيانة الخارجي"],
    },
}


def parse_reference_list(value, default):
    if isinstance(value, list):
        values = value
    else:
        try:
            values = json.loads(value) if value else default
        except (TypeError, ValueError):
            values = default
    if not isinstance(values, list):
        values = default
    return list(dict.fromkeys(
        item.strip() for item in values
        if isinstance(item, str) and item.strip()
    ))


def load_reference_lists(connection=None):
    saved = repository.get_group_settings('lookups')
    return {
        name: parse_reference_list(
            saved.get(definition["setting_key"]),
            definition["defaults"],
        )
        for name, definition in REFERENCE_LISTS.items()
    }

class WorkshopAsset:
    def __init__(self, id, asset_code, name, category, status, location, purchase_date, condition_status, notes):
        self.id = id
        self.asset_code = asset_code
        self.name = name
        self.category = category
        self.status = status
        self.location = location
        self.purchase_date = purchase_date
        self.condition_status = condition_status
        self.notes = notes

    @staticmethod
    def from_row(row):
        """تحويل صف قاعدة البيانات إلى كائن بايثون سلس"""
        return WorkshopAsset(
            id=row["id"],
            asset_code=row["asset_code"],
            name=row["name"],
            category=row["category"],
            status=row["status"] or "متاح",
            location=row["location"] or "-",
            purchase_date=row["purchase_date"] or "-",
            condition_status=row["condition_status"] or "جيد",
            notes=row["notes"] or ""
        )

    def to_dict(self):
        return {
            "id": self.id,
            "asset_code": self.asset_code,
            "name": self.name,
            "category": self.category,
            "status": self.status,
            "location": self.location,
            "purchase_date": self.purchase_date,
            "condition_status": self.condition_status,
            "notes": self.notes
        }
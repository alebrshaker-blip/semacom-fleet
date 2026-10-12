class StoreItem:
    def __init__(self, id=None, item_code=None, name=None, category=None, unit='قطعة', quantity=0, min_limit=5, location=None, unit_price=0.0, notes=None):
        self.id = id
        self.item_code = item_code
        self.name = name
        self.category = category
        self.unit = unit
        self.quantity = quantity
        self.min_limit = min_limit
        self.location = location
        self.unit_price = unit_price
        self.notes = notes

    @classmethod
    def from_row(cls, row):
        """تحويل صف قاعدة البيانات إلى كائن صنف مخزني"""
        if not row:
            return None
        return cls(
            id=row[0],
            item_code=row[1],
            name=row[2],
            category=row[3],
            unit=row[4],
            quantity=row[5],
            min_limit=row[6],
            location=row[7],
            unit_price=row[8],
            notes=row[9]
        )

    def to_dict(self):
        return {
            'id': self.id,
            'item_code': self.item_code,
            'name': self.name,
            'category': self.category,
            'unit': self.unit,
            'quantity': self.quantity,
            'min_limit': self.min_limit,
            'location': self.location,
            'unit_price': self.unit_price,
            'notes': self.notes,
            'is_low_stock': self.quantity <= self.min_limit
        }
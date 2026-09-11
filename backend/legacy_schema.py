"""Column mappings to existing tables; no extension schema."""
import json
import re

def array(value):
    if isinstance(value, list):
        return value
    if value in (None, ''):
        return []
    try:
        decoded = json.loads(str(value))
        if isinstance(decoded, list):
            return decoded
    except (ValueError, TypeError):
        pass
    return [x.strip() for x in re.split('[,，;；\n]', str(value)) if x.strip()]


ASSETS = {
    'vehicle': ('CarList', 'ID', 'license_plate', 'isdelete', {
        'model': 'car_type', 'client_id': 'client_id', 'holder': 'holder',
        'owner': 'owner', 'purchase_date': 'purchase_date', 'amount': 'amount',
        'passengers': 'passengers', 'notes': 'notes', 'manager': 'manager',
        'contact_person': 'contact_person', 'phone_number': 'phone_number',
        'equipment': 'equipment', 'type_code': 'type_code',
    }),
    'equipment': ('EquipmentList', 'id', 'equipment_id', 'is_deleted', {
        'name': 'equipment_name', 'location': 'equipment_loc',
        'brand': 'brand_manufacturer', 'holder': 'holder', 'quantity': 'quantity',
        'notes': 'notes', 'state': 'hold_adv', 'estimated_amount': 'estimated_amount',
        'accessories': 'equipment_plus', 'purpose': 'purpose',
        'purchase_manufacturer': 'purchase_manufacturer', 'fix_manufacturer': 'fix_manufacturer',
        'fix_date': 'fix_date', 'valid_period': 'valid_period',
    }),
}
RECORDS = {
    'insurance': ('insurance_records', {'company': 'company', 'expiry': 'validity_period',
        'phone': 'company_phone', 'employee': 'employee', 'employee_phone': 'employee_phone',
        'roadside_assistance': 'roadside_assistance'}),
    'cost': ('cost', {'type': 'type', 'reason': 'reason', 'amount': 'amount', 'notes': 'notes'}),
    'maintenance': ('vehicle_records', {'type': 'record_type', 'date': 'record_date', 'notes': 'notes'}),
    'garage': ('garage_files', {'notes': 'notes'}),
    'manager': ('vehicle_managers', {'name': 'manager_name', 'notes': 'notes'}),
}


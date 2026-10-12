from modules.drivers.models.drivers_model import (
    get_all_drivers, 
    add_driver, 
    delete_driver, 
    init_driver_db
)

def fetch_drivers(search_query=""):
    init_driver_db()
    return get_all_drivers(search_query)

def create_driver(form_data):
    init_driver_db()
    return add_driver(form_data)

def remove_driver(driver_id):
    delete_driver(driver_id)
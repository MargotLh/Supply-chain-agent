from tools import api_client


def find_alternative_supplier(sku: str) -> dict:
    """Alternative suppliers that can ship the SKU, with lead time and extra cost."""
    return api_client.get(f"/api/v1/system/suppliers/{sku}")

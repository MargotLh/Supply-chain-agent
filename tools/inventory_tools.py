from tools import api_client


def check_inventory(sku: str) -> dict:
    """Stock for a SKU across all warehouses, with reroute cost and transit time."""
    return api_client.get(f"/api/v1/system/inventory/{sku}")

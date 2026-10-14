from tools import api_client


def get_order(order_id: str) -> dict:
    """Fetch an order (customer, SKU, quantity, promised date) in canonical form."""
    return api_client.get(f"/api/v1/system/orders/{order_id}")


def get_shipment(order_id: str) -> dict:
    """Fetch the shipment tracking the order (carrier, ETA, delay reason)."""
    return api_client.get(f"/api/v1/system/shipments/{order_id}")


def update_order(order_id: str, action: str, detail: str = "",
                 extra_cost_gbp: float = 0, approval_id: str | None = None) -> dict:
    """Write a remediation action back to the ERP. Guarded: see governance/permissions.py."""
    return api_client.post(f"/api/v1/system/orders/{order_id}/actions", {
        "action": action, "detail": detail,
        "extra_cost_gbp": extra_cost_gbp, "approval_id": approval_id,
    })


def send_operations_message(message: str, channel: str = "ops-exceptions") -> dict:
    """Notify the operations team."""
    return api_client.post("/api/v1/system/notifications", {"text": message, "channel": channel})

from fastapi.testclient import TestClient

from integration.api import app


def test_rejects_missing_client_credentials():
    assert TestClient(app).get("/api/v1/system/orders/1842").status_code == 401


def test_translates_legacy_fields_to_canonical_model():
    from tools import api_client
    o = api_client.get("/api/v1/system/orders/1842")
    assert o["sku"] == "SKU-4471" and o["quantity"] == 400
    assert o["customer"]["tier"] == "PLATINUM"
    assert o["days_to_promise"] == 2
    assert "MATNR" not in o


def test_supplier_shape_matches_tool_contract():
    from tools.supplier_tools import find_alternative_supplier
    s = find_alternative_supplier("SKU-9020")["suppliers"][0]
    assert s == {"supplier_id": "V-200", "supplier": "Supplier B", "available_units": 500,
                 "lead_time_days": 2, "extra_cost": 1800}


def test_unknown_order_is_404():
    import pytest

    from tools import api_client
    with pytest.raises(api_client.IntegrationError, match="404"):
        api_client.get("/api/v1/system/orders/9999")

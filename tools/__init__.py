"""Tool registry. Every tool an agent (or MCP client) can invoke is listed here,
and every invocation goes through governance.permissions.ToolGateway."""
from tools.inventory_tools import check_inventory
from tools.order_tools import get_order, get_shipment, send_operations_message, update_order
from tools.supplier_tools import find_alternative_supplier

TOOLS = {
    "get_order": get_order,
    "get_shipment": get_shipment,
    "check_inventory": check_inventory,
    "find_alternative_supplier": find_alternative_supplier,
    "update_order": update_order,
    "send_operations_message": send_operations_message,
}

"""MCP server exposing the supply-chain tools to any MCP client
(Claude Desktop, Claude Code, Agentforce via MCP, ...).

    Agent / LLM  ->  MCP tool  ->  ToolGateway (permissions + audit)
                 ->  integration layer (MuleSoft stand-in)  ->  mock ERP

All six tools are advertised, but every call goes through the same ToolGateway
the internal agents use. The caller's role comes from MCP_AGENT_ROLE (default
"MCP Client" = read-only), so e.g. update_order is refused unless the server is
started with a role that holds that permission.

Run (stdio):   python -m mcp_server.server
Claude Code:   claude mcp add supply-chain -- python -m mcp_server.server
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from governance.permissions import PermissionDenied, ToolGateway  # noqa: E402
from tools.api_client import IntegrationError  # noqa: E402

ROLE = os.getenv("MCP_AGENT_ROLE", "MCP Client")
gateway = ToolGateway(ROLE)
server = _Server("supply-chain-exceptions",
                 instructions="Tools for investigating and resolving delayed customer orders. "
                              "Order-changing tools are permission-gated and may require human approval.")


def _call(tool: str, **kwargs) -> dict:
    try:
        return gateway.call(tool, **kwargs)
    except PermissionDenied as e:
        return {"error": "PERMISSION_DENIED", "role": ROLE, "tool": tool, "reason": e.reason}
    except IntegrationError as e:
        return {"error": "INTEGRATION_ERROR", "detail": str(e)}


@server.tool()
def get_order(order_id: str) -> dict:
    """Get an order: customer and tier, SKU, quantity, promised date, status."""
    return _call("get_order", order_id=order_id)


@server.tool()
def get_shipment(order_id: str) -> dict:
    """Get the shipment for an order: carrier, original vs current ETA, delay reason."""
    return _call("get_shipment", order_id=order_id)


@server.tool()
def check_inventory(sku: str) -> dict:
    """Stock levels for a SKU in every warehouse, with reroute cost (GBP) and transit days."""
    return _call("check_inventory", sku=sku)


@server.tool()
def find_alternative_supplier(sku: str) -> dict:
    """Alternative suppliers for a SKU with available units, lead time and extra cost (GBP)."""
    return _call("find_alternative_supplier", sku=sku)


@server.tool()
def update_order(order_id: str, action: str, detail: str = "",
                 extra_cost_gbp: float = 0, approval_id: str | None = None) -> dict:
    """Apply a remediation to an order (REROUTE_WAREHOUSE, ALTERNATIVE_SUPPLIER, WAIT, HOLD).
    Requires write permission; above the cost threshold an approved approval_id is mandatory."""
    return _call("update_order", order_id=order_id, action=action, detail=detail,
                 extra_cost_gbp=extra_cost_gbp, approval_id=approval_id)


@server.tool()
def send_operations_message(message: str) -> dict:
    """Post a message to the operations exceptions channel."""
    return _call("send_operations_message", message=message)


if __name__ == "__main__":
    server.run()

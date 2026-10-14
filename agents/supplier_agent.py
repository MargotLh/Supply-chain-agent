from agents.base import Agent


class SupplierAgent(Agent):
    """Finds alternative suppliers able to cover the full order quantity."""
    name = "Supplier Agent"

    def run(self, order: dict) -> dict:
        sku, needed = order["sku"], order["quantity"]
        result = self.tools.call("find_alternative_supplier", sku=sku)

        viable = [s for s in result["suppliers"] if s["available_units"] >= needed]
        if viable:
            names = ", ".join(f"{s['supplier']} ({s['lead_time_days']}d, +£{s['extra_cost']:,.0f})" for s in viable)
            self.log(f"Result: {len(viable)} supplier(s) can cover {needed} units: {names}")
        else:
            self.log(f"Result: no alternative supplier can cover {needed} x {sku}")
        return {"sku": sku, "suppliers": result["suppliers"], "viable": viable}

from agents.base import Agent


class InventoryAgent(Agent):
    """Looks for stock of the delayed SKU in *other* warehouses."""
    name = "Inventory Agent"

    def run(self, order: dict) -> dict:
        sku, needed = order["sku"], order["quantity"]
        stock = self.tools.call("check_inventory", sku=sku)

        candidates = [loc for loc in stock["locations"] if loc["warehouse_id"] != order["source_warehouse"]]
        viable = [loc for loc in candidates if loc["available_units"] >= needed]

        if viable:
            best = min(viable, key=lambda l: (l["reroute_cost_gbp"], l["transit_days"]))
            self.log(f"Result: {best['available_units']} units of {sku} in {best['warehouse_id']} "
                     f"({best['warehouse_name']}), need {needed}")
        else:
            total = sum(l["available_units"] for l in candidates)
            self.log(f"Result: no single warehouse can cover {needed} x {sku} ({total} units elsewhere in total)")
        return {"sku": sku, "required_units": needed, "locations": candidates, "viable": viable}

from governance.audit_log import audit
from governance.permissions import ToolGateway
from tools.api_client import correlation_id


class Agent:
    """Every agent has a name (its identity/role) and a permission-scoped tool gateway."""
    name: str = "Agent"

    def __init__(self):
        self.tools = ToolGateway(self.name)

    def log(self, summary: str, event: str = "FINDING", **data) -> None:
        audit.record(self.name, event, summary, correlation_id.get(), **data)

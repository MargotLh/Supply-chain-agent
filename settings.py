"""Central configuration. Everything can be overridden with environment variables."""
import os

# Where services live. When unset, calls run in-process (no servers needed).
ERP_URL = os.getenv("ERP_URL")                  # e.g. http://mock-erp:8001
INTEGRATION_URL = os.getenv("INTEGRATION_URL")  # e.g. http://integration:8002

# Client credentials the integration layer expects (MuleSoft client-id enforcement policy).
INTEGRATION_CLIENT_ID = os.getenv("INTEGRATION_CLIENT_ID", "agent-orchestrator")
INTEGRATION_CLIENT_SECRET = os.getenv("INTEGRATION_CLIENT_SECRET", "local-dev-secret")

# Human-in-the-loop threshold: actions costing more than this need approval.
APPROVAL_THRESHOLD_GBP = float(os.getenv("APPROVAL_THRESHOLD_GBP", "1000"))

# Estimated cost of each day late, by customer tier (SLA penalties + churn risk).
LATE_PENALTY_GBP_PER_DAY = {
    "PLATINUM": 1500,
    "GOLD": 600,
    "STANDARD": 150,
}

# Decision Agent reasoning: "auto" uses Claude when ANTHROPIC_API_KEY is set, else rules;
# "llm" requires Claude; "rules" never calls it.
DECISION_MODE = os.getenv("DECISION_MODE", "auto")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-opus-5-5")

AUDIT_LOG_PATH = os.getenv("AUDIT_LOG_PATH", "logs/audit.jsonl")

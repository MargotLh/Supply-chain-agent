"""Impact / Decision Agent.

Turns findings into scored options and recommends one. Scoring is deliberately
transparent so a human approver can follow it:

    score = extra_cost + days_late x late_penalty_per_day(customer_tier)

When Claude is available (see agents/llm_reasoner.py) it picks among those scored
options and writes the rationale. Its answer is checked, and if Claude errors,
refuses or picks an option that doesn't exist, the lowest score wins as before.
If Claude picks anything other than the lowest score, a human must approve it.

It has no tool permissions: it can recommend, never execute.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import settings
from agents.base import Agent


@dataclass
class Option:
    action: str              # WAIT | REROUTE_WAREHOUSE | ALTERNATIVE_SUPPLIER
    target: str | None
    extra_cost_gbp: float
    days_late: int
    late_penalty_gbp: float
    score: float
    description: str


@dataclass
class Recommendation:
    action: str
    target: str | None
    extra_cost_gbp: float
    days_late: int
    requires_approval: bool
    rationale: str
    options: list[Option] = field(default_factory=list)
    decided_by: str = "rules"   # "rules" or the Claude model id

    def to_dict(self) -> dict:
        return asdict(self)


class DecisionAgent(Agent):
    name = "Decision Agent"

    def __init__(self, reasoner=None):
        super().__init__()
        if reasoner is None:
            from agents.llm_reasoner import default_reasoner
            reasoner = default_reasoner()
        self.reasoner = reasoner

    def run(self, order: dict, delay_days: int, inventory: dict, suppliers: dict | None) -> Recommendation:
        tier = order["customer"]["tier"]
        per_day = settings.LATE_PENALTY_GBP_PER_DAY.get(tier, settings.LATE_PENALTY_GBP_PER_DAY["STANDARD"])
        slack = order["days_to_promise"]

        def option(action, target, cost, lead_days, desc):
            late = max(0, lead_days - slack) if action != "WAIT" else delay_days
            return Option(action, target, cost, late, late * per_day, cost + late * per_day, desc)

        options = [option("WAIT", None, 0, None, f"Accept the {delay_days}-day carrier delay")]
        for loc in inventory["viable"]:
            options.append(option("REROUTE_WAREHOUSE", loc["warehouse_id"], loc["reroute_cost_gbp"],
                                  loc["transit_days"],
                                  f"Reroute from {loc['warehouse_name']} ({loc['warehouse_id']})"))
        for s in (suppliers or {}).get("viable", []):
            options.append(option("ALTERNATIVE_SUPPLIER", s["supplier"], s["extra_cost"],
                                  s["lead_time_days"], f"Source from {s['supplier']}"))

        options.sort(key=lambda o: (o.score, o.extra_cost_gbp))
        wait = next(o for o in options if o.action == "WAIT")
        for o in options:
            self.log(f"  option {o.action:<21} {o.target or '-':<11} cost £{o.extra_cost_gbp:>6,.0f}  "
                     f"late {o.days_late}d  score {o.score:,.0f}", event="ANALYSIS")

        best, rationale, decided_by = options[0], self._rules_rationale(options[0], wait, tier), "rules"
        override = False
        if self.reasoner:
            choice = self._ask_llm(order, delay_days, options)
            if choice:
                idx, llm_rationale = choice
                override = idx != 0
                best, rationale, decided_by = options[idx], llm_rationale, self.reasoner.model

        rec = Recommendation(
            action=best.action, target=best.target, extra_cost_gbp=best.extra_cost_gbp,
            days_late=best.days_late,
            requires_approval=override or best.extra_cost_gbp > settings.APPROVAL_THRESHOLD_GBP,
            rationale=rationale, options=options, decided_by=decided_by,
        )
        if override:
            self.log(f"{decided_by} chose {best.action} over the lowest-score option "
                     f"({options[0].action}) -> human approval required", event="LLM_OVERRIDE")
        self.log(f"Recommended {rec.action}{f' ({rec.target})' if rec.target else ''} [{decided_by}]: {rationale}",
                 event="RECOMMENDATION", recommendation=rec.to_dict())
        return rec

    def _ask_llm(self, order: dict, delay_days: int, options: list[Option]) -> tuple[int, str] | None:
        """Claude's (option index, rationale), or None to fall back to the rules."""
        context = {
            "order": order, "delay_days": delay_days,
            "approval_threshold_gbp": settings.APPROVAL_THRESHOLD_GBP,
            "late_penalty_gbp_per_day": settings.LATE_PENALTY_GBP_PER_DAY,
            "options": [{"index": i, **asdict(o)} for i, o in enumerate(options)],
        }
        try:
            choice = self.reasoner.choose(context)
        except Exception as exc:
            self.log(f"Claude unavailable ({type(exc).__name__}: {exc}) -> using rule-based choice",
                     event="LLM_FALLBACK")
            return None
        if not 0 <= choice.option_index < len(options) or not choice.rationale.strip():
            self.log(f"Claude returned invalid option {choice.option_index} -> using rule-based choice",
                     event="LLM_FALLBACK")
            return None
        return choice.option_index, choice.rationale.strip()

    @staticmethod
    def _rules_rationale(best: Option, wait: Option, tier: str) -> str:
        if best.action == "WAIT":
            return (f"Waiting costs an estimated £{wait.late_penalty_gbp:,.0f} in {tier} late penalties, "
                    f"which is cheaper than any mitigation. Accept delay and inform customer.")
        return (f"{best.description}. Additional cost: £{best.extra_cost_gbp:,.0f}. "
                f"Arrives {best.days_late} day(s) late vs {wait.days_late} if we wait; avoids "
                f"~£{wait.late_penalty_gbp - best.late_penalty_gbp:,.0f} of {tier} late penalties "
                f"(net benefit £{wait.score - best.score:,.0f}).")

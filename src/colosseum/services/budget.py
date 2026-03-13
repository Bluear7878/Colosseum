from __future__ import annotations

from colosseum.core.models import BudgetLedger, BudgetPolicy, UsageMetrics


class BudgetManager:
    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def remaining_tokens(self, policy: BudgetPolicy, ledger: BudgetLedger) -> int:
        return max(0, policy.total_token_budget - ledger.total.total_tokens)

    def budget_pressure(self, policy: BudgetPolicy, ledger: BudgetLedger) -> float:
        if policy.total_token_budget <= 0:
            return 1.0
        return min(1.0, ledger.total.total_tokens / policy.total_token_budget)

    def can_start_round(self, policy: BudgetPolicy, ledger: BudgetLedger, next_round_index: int) -> bool:
        if next_round_index > policy.max_rounds:
            ledger.exhausted = True
            ledger.stop_reason = "maximum_rounds_reached"
            return False
        if ledger.total.total_tokens >= policy.total_token_budget:
            ledger.exhausted = True
            ledger.stop_reason = "token_budget_exhausted"
            return False
        return True

    def round_over_limit(self, policy: BudgetPolicy, round_index: int, ledger: BudgetLedger) -> bool:
        usage = ledger.by_round.get(str(round_index), UsageMetrics())
        return usage.total_tokens >= policy.per_round_token_limit

"""Request-scoped hard call/output reservations and a monotonic deadline."""

import time
from typing import Any


class BudgetExceeded(RuntimeError):
    """A bounded request must abstain or use deterministic answer rendering."""


class CallBudget:
    """Count every attempted model request, including failed or malformed outputs."""

    def __init__(self, calls: int, output_tokens: int, timeout: float) -> None:
        self.maximum,self.maximum_tokens = calls,output_tokens
        self.calls,self.reserved_tokens = 0,0
        self.deadline = time.monotonic()+timeout

    def remaining_seconds(self) -> float:
        """Return request time remaining or fail closed."""
        remaining = self.deadline-time.monotonic()
        if remaining<=0:
            raise BudgetExceeded("The request time budget was reached.")
        return remaining

    def take(self, tokens: int) -> None:
        """Reserve a call and its maximum output before contacting the provider."""
        self.remaining_seconds()
        if self.calls>=self.maximum or self.reserved_tokens+tokens>self.maximum_tokens:
            raise BudgetExceeded("The model-call or token budget was reached.")
        self.calls += 1
        self.reserved_tokens += tokens


class BudgetedModel:
    """Wrap all text-generation routes in one per-question counter."""

    def __init__(self, model: Any, budget: CallBudget, settings: Any) -> None:
        self.model,self.budget,self.settings = model,budget,settings

    def select(self, *args: Any) -> Any:
        """Reserve a function-selection call."""
        self.budget.take(self.settings.select_tokens)
        self._deadline()
        return self.model.select(*args)

    def answer(self, *args: Any) -> Any:
        """Reserve answer generation; callers may render deterministically if exhausted."""
        self.budget.take(self.settings.answer_tokens)
        self._deadline()
        return self.model.answer(*args)

    def judge(self, *args: Any) -> Any:
        """Reserve structured evidence judgement."""
        self.budget.take(self.settings.grade_tokens)
        self._deadline()
        return self.model.judge(*args)

    def rewrite(self, *args: Any) -> Any:
        """Reserve at most the orchestrator-authorized rewrite attempt."""
        self.budget.take(self.settings.rewrite_tokens)
        self._deadline()
        return self.model.rewrite(*args)

    def _deadline(self) -> None:
        if hasattr(self.model,"set_deadline"):
            self.model.set_deadline(self.budget.deadline)

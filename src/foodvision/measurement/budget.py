"""Per-scan budgets (plan §10 Reliability and retry policy)."""

from pydantic import BaseModel, ConfigDict, Field

from foodvision.contracts.errors import ErrorCode


class BudgetPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    deadline_s: float = Field(default=45.0, gt=0)
    max_model_calls: int = Field(default=2, ge=0)
    max_attempts: int = Field(default=8, ge=0)  # actual attempts, retries included
    max_retries_per_request: int = Field(default=1, ge=0)
    max_cost_usd: float | None = Field(default=None, ge=0)  # None = no dollar cap
    # With a dollar cap, an attempt of unknown cost could break it, so refuse it.
    refuse_unknown_cost_under_cap: bool = True


class BudgetExceeded(RuntimeError):
    code = ErrorCode.TIMEOUT

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
        if reason != "deadline":
            self.code = ErrorCode.QUOTA

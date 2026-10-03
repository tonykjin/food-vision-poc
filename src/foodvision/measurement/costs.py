"""Cost estimates with provenance. No prices are built in: an unpriced call stays unknown.

Prices must come from the provider's current pricing page on the day a budget is set
(docs/provider-readiness.md) and are loaded into a versioned PriceTable.
"""

from pydantic import BaseModel, ConfigDict, Field

from foodvision.measurement.events import CostEstimate, CostProvenance, ProviderUsage


class Price(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    input_usd_per_mtok: float | None = Field(default=None, ge=0)
    output_usd_per_mtok: float | None = Field(default=None, ge=0)
    per_call_usd: float | None = Field(default=None, ge=0)


class PriceTable(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    source_url: str
    prices: dict[str, Price] = Field(default_factory=dict)  # key: "provider/model"

    def estimate(
        self, provider: str, model: str | None, usage: ProviderUsage | None
    ) -> CostEstimate:
        price = self.prices.get(f"{provider}/{model}")
        if price is None:
            return CostEstimate.unknown()
        if price.per_call_usd is not None:
            amount = price.per_call_usd
        elif (
            usage is None
            or usage.input_tokens is None
            or usage.output_tokens is None
            or price.input_usd_per_mtok is None
            or price.output_usd_per_mtok is None
        ):
            return CostEstimate.unknown()
        else:
            amount = (
                usage.input_tokens * price.input_usd_per_mtok
                + usage.output_tokens * price.output_usd_per_mtok
            ) / 1_000_000
        return CostEstimate(
            amount_usd=amount,
            provenance=CostProvenance.PRICE_TABLE_ESTIMATE,
            price_table_version=self.version,
        )


def total_cost(estimates: list[CostEstimate]) -> tuple[float, float | None]:
    """Return (known sum, full total). The full total is None if any estimate is unknown."""
    known = sum(e.amount_usd for e in estimates if e.amount_usd is not None)
    complete = all(e.amount_usd is not None for e in estimates)
    return known, (known if complete else None)

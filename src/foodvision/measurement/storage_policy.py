"""Source-specific storage policy, applied before any persistence, export, log or fixture.

Each field is classified by data class, and the policy decides per (source, class, purpose).
fatsecret with pending rights (no written grant; docs/provider-readiness.md):
- payload-free metadata (timings, counts, codes, hashes, config IDs): allowed
- permitted IDs (`food_id`, `serving_id`; documented as storable): persist/export/log only
- restricted content (names, portions, nutrients, warnings, provider messages): in-memory
  transient evaluation only (Terms §1.5: remove within 24 h); never persisted or exported
- derived accuracy metrics: transient evaluation only, never persisted or exported
USDA (CC0) and our own model outputs carry no third-party restriction.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from foodvision.contracts.results import AnalysisResult
from foodvision.measurement.events import ScanRecord


class DataSource(StrEnum):
    FATSECRET = "fatsecret"
    USDA = "USDA"
    VISION_MODEL = "vision_model"
    INTERNAL = "internal"
    MOCK = "mock"


class DataClass(StrEnum):
    PAYLOAD_FREE_METADATA = "payload_free_metadata"
    PERMITTED_ID = "permitted_id"
    RESTRICTED_CONTENT = "restricted_content"
    DERIVED_METRIC = "derived_metric"


class Purpose(StrEnum):
    PERSIST = "persist"
    EXPORT = "export"
    LOG = "log"
    ERROR_REPORT = "error_report"
    FIXTURE = "fixture"
    TRANSIENT_EVALUATION = "transient_evaluation"  # in memory, within one run


class PolicyViolation(PermissionError):
    pass


# Written fatsecret grants, keyed by PROVIDER_OUTPUT_POLICY_VERSION. Empty: none received.
FATSECRET_GRANTS: dict[str, frozenset[tuple[DataClass, Purpose]]] = {}

_PENDING_FATSECRET: frozenset[tuple[DataClass, Purpose]] = frozenset(
    {(DataClass.PAYLOAD_FREE_METADATA, p) for p in Purpose}
    | {
        (DataClass.PERMITTED_ID, Purpose.PERSIST),
        (DataClass.PERMITTED_ID, Purpose.EXPORT),
        (DataClass.PERMITTED_ID, Purpose.LOG),
        (DataClass.PERMITTED_ID, Purpose.ERROR_REPORT),
        (DataClass.PERMITTED_ID, Purpose.TRANSIENT_EVALUATION),
        (DataClass.RESTRICTED_CONTENT, Purpose.TRANSIENT_EVALUATION),
        (DataClass.DERIVED_METRIC, Purpose.TRANSIENT_EVALUATION),
    }
)


class StoragePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = "pending"
    fatsecret_allowed: frozenset[tuple[DataClass, Purpose]] = _PENDING_FATSECRET

    @property
    def fatsecret_pending(self) -> bool:
        return self.fatsecret_allowed == _PENDING_FATSECRET

    def allows(self, source: DataSource, data_class: DataClass, purpose: Purpose) -> bool:
        if source is DataSource.FATSECRET:
            return (data_class, purpose) in self.fatsecret_allowed
        return True

    def require(self, source: DataSource, data_class: DataClass, purpose: Purpose) -> None:
        if not self.allows(source, data_class, purpose):
            raise PolicyViolation(
                f"policy {self.version}: {data_class} from {source} not allowed for {purpose}"
            )


def policy_from_settings(persist_provider_outputs: bool, policy_version: str) -> StoragePolicy:
    """Pending unless persistence is enabled AND a written grant is recorded for the version."""
    if not persist_provider_outputs or policy_version == "pending":
        return StoragePolicy(version=policy_version)
    grant = FATSECRET_GRANTS.get(policy_version)
    if grant is None:
        raise ValueError(
            f"PERSIST_PROVIDER_OUTPUTS=true but no written grant is recorded for "
            f"PROVIDER_OUTPUT_POLICY_VERSION={policy_version!r}"
        )
    return StoragePolicy(version=policy_version, fatsecret_allowed=_PENDING_FATSECRET | grant)


# --- Field classification for AnalysisResult ---------------------------------------------

_ITEM_FIELDS: dict[str, DataClass] = {
    "resolved": DataClass.PAYLOAD_FREE_METADATA,
    "portion_method": DataClass.PAYLOAD_FREE_METADATA,
    "food_source": DataClass.PAYLOAD_FREE_METADATA,
    "food_id": DataClass.PERMITTED_ID,
    "serving_id": DataClass.PERMITTED_ID,
    "name": DataClass.RESTRICTED_CONTENT,
    "preparation": DataClass.RESTRICTED_CONTENT,
    "portion_g": DataClass.RESTRICTED_CONTENT,
    "nutrients": DataClass.RESTRICTED_CONTENT,
    "uncertainty_reasons": DataClass.RESTRICTED_CONTENT,
    "portion_scenarios": DataClass.RESTRICTED_CONTENT,
    "alternatives": DataClass.RESTRICTED_CONTENT,
    "evidence": DataClass.RESTRICTED_CONTENT,
    "visible_brand": DataClass.RESTRICTED_CONTENT,
}
_RESULT_FIELDS: dict[str, DataClass] = {
    "schema_version": DataClass.PAYLOAD_FREE_METADATA,
    "scan_id": DataClass.PAYLOAD_FREE_METADATA,
    "pipeline_id": DataClass.PAYLOAD_FREE_METADATA,
    "configuration_id": DataClass.PAYLOAD_FREE_METADATA,
    "is_mock": DataClass.PAYLOAD_FREE_METADATA,
    "status": DataClass.PAYLOAD_FREE_METADATA,
    "nutrition_basis": DataClass.PAYLOAD_FREE_METADATA,
    "input": DataClass.PAYLOAD_FREE_METADATA,
    "metrics": DataClass.PAYLOAD_FREE_METADATA,
    "model_provenance": DataClass.PAYLOAD_FREE_METADATA,
    "warnings": DataClass.RESTRICTED_CONTENT,
    "confidence": DataClass.DERIVED_METRIC,
}
_TOTALS_FIELDS: dict[str, DataClass] = {
    "status": DataClass.PAYLOAD_FREE_METADATA,
    "included_items": DataClass.PAYLOAD_FREE_METADATA,
    "excluded_items": DataClass.PAYLOAD_FREE_METADATA,
    "nutrients": DataClass.RESTRICTED_CONTENT,
}
_ERROR_FIELDS: dict[str, DataClass] = {
    "code": DataClass.PAYLOAD_FREE_METADATA,
    "retryable": DataClass.PAYLOAD_FREE_METADATA,
    "message": DataClass.RESTRICTED_CONTENT,  # may echo provider text
}


def _filter(data: dict[str, Any], classes: dict[str, DataClass], keep, prefix: str, dropped):
    out = {}
    for key, value in data.items():
        data_class = classes.get(key, DataClass.RESTRICTED_CONTENT)  # unclassified: restrict
        if keep(data_class):
            out[key] = value
        else:
            dropped.append(f"{prefix}{key}")
    return out


def filter_result(
    result: AnalysisResult, source: DataSource, policy: StoragePolicy, purpose: Purpose
) -> dict[str, Any]:
    """Return only the fields this source's policy allows for `purpose`, plus what was dropped."""

    def keep(data_class: DataClass) -> bool:
        return policy.allows(source, data_class, purpose)

    data = result.model_dump(mode="json")
    dropped: list[str] = []
    out = _filter(
        {k: v for k, v in data.items() if k not in ("items", "totals", "error")},
        _RESULT_FIELDS,
        keep,
        "",
        dropped,
    )
    out["items"] = [
        _filter(item, _ITEM_FIELDS, keep, f"items[{i}].", dropped)
        for i, item in enumerate(data["items"])
    ]
    out["totals"] = _filter(data["totals"], _TOTALS_FIELDS, keep, "totals.", dropped)
    if data["error"] is not None:
        out["error"] = _filter(data["error"], _ERROR_FIELDS, keep, "error.", dropped)
    out["_policy"] = {"version": policy.version, "source": source.value, "dropped": dropped}
    return out


def export_scan_record(
    record: ScanRecord, source: DataSource, policy: StoragePolicy, purpose: Purpose
) -> dict[str, Any]:
    """ScanRecords are payload-free by construction; the gate still applies."""
    policy.require(source, DataClass.PAYLOAD_FREE_METADATA, purpose)
    return record.model_dump(mode="json")


def require_metric_storage(source: DataSource, policy: StoragePolicy, purpose: Purpose) -> None:
    """Call before persisting/exporting any accuracy metric derived from `source` outputs."""
    policy.require(source, DataClass.DERIVED_METRIC, purpose)

"""Relational schema (plan §5). Three access boundaries:

- food_catalog: permitted nutrition records. Inference may read.
- telemetry:    images metadata, configurations, runs, events, policy-filtered results.
                Inference may write run records.
- benchmark:    samples, hidden reference labels, evaluation metrics, calibration.
                Evaluator only: the inference role has no privileges on this schema.

No image bytes are stored here (object keys and hashes only). Unknown nutrients are NULL.
`is_synthetic` marks test/demo rows, which are never evidence of recognition accuracy.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID

CATALOG, TELEMETRY, BENCHMARK = "food_catalog", "telemetry", "benchmark"
SCHEMAS = (CATALOG, TELEMETRY, BENCHMARK)

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

SHA256 = String(64)


def created_at() -> Column:
    return Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now())


def synthetic() -> Column:
    return Column("is_synthetic", Boolean, nullable=False, server_default="false")


# --- food_catalog -----------------------------------------------------------------------

food_records = Table(
    "food_records",
    metadata,
    Column("food_id", BigInteger, primary_key=True, autoincrement=True),
    Column("provider", Text, nullable=False),
    Column("provider_food_id", Text, nullable=False),
    Column("source_version", Text, nullable=False),
    Column("data_type", Text),
    Column("name", Text, nullable=False),
    Column("preparation", Text),
    Column("brand", Text),
    Column("region", Text),
    Column("category", Text),
    # uncooked (raw/dry/uncooked), cooked, not_stated, ambiguous: parsed from the FDC name
    Column("preparation_state", Text, nullable=False, server_default="not_stated"),
    Column("published_date", Date),
    Column("retrieved_at", DateTime(timezone=True)),
    Column(
        "search_vector",
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(name, '') || ' ' || coalesce(category, '') "
            "|| ' ' || coalesce(brand, ''))",
            persisted=True,
        ),
    ),
    Column("basis_kind", Text, nullable=False),
    Column("basis_quantity", Numeric, nullable=False),
    Column("basis_unit", Text, nullable=False),
    Column("density_g_per_ml", Numeric),
    synthetic(),
    created_at(),
    UniqueConstraint("provider", "provider_food_id", "source_version"),
    CheckConstraint("basis_kind IN ('per_100g', 'per_100ml', 'per_serving')", name="basis_kind"),
    CheckConstraint("basis_unit IN ('g', 'ml')", name="basis_unit"),
    CheckConstraint("basis_quantity > 0", name="basis_quantity_positive"),
    CheckConstraint(
        "(basis_kind <> 'per_100g' OR (basis_quantity = 100 AND basis_unit = 'g')) AND "
        "(basis_kind <> 'per_100ml' OR (basis_quantity = 100 AND basis_unit = 'ml'))",
        name="basis_consistent",
    ),
    CheckConstraint("density_g_per_ml IS NULL OR density_g_per_ml > 0", name="density_positive"),
    CheckConstraint(
        "preparation_state IN ('uncooked', 'cooked', 'not_stated', 'ambiguous')",
        name="preparation_state",
    ),
    Index("ix_food_records_search_vector", "search_vector", postgresql_using="gin"),
    schema=CATALOG,
)

food_nutrients = Table(
    "food_nutrients",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "food_id",
        BigInteger,
        ForeignKey(f"{CATALOG}.food_records.food_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("nutrient", Text, nullable=False),
    Column("amount", Numeric),  # NULL = unknown, never 0
    Column("unit", Text, nullable=False),
    Column("source_nutrient_id", Integer),  # e.g. FDC nutrient id 2048, 1003
    Column("source_nutrient_name", Text),
    UniqueConstraint("food_id", "nutrient"),
    CheckConstraint("amount IS NULL OR amount >= 0", name="amount_non_negative"),
    schema=CATALOG,
)

food_portions = Table(
    "food_portions",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "food_id",
        BigInteger,
        ForeignKey(f"{CATALOG}.food_records.food_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("portion_name", Text, nullable=False),
    Column("quantity", Numeric),
    Column("measure_unit", Text),
    Column("modifier", Text),
    Column("gram_weight", Numeric, nullable=False),  # only from source data, never inferred
    Column("portion_source", Text, nullable=False, server_default="source_data"),
    UniqueConstraint("food_id", "portion_name"),
    CheckConstraint("gram_weight > 0", name="gram_weight_positive"),
    schema=CATALOG,
)

# --- telemetry --------------------------------------------------------------------------

images = Table(
    "images",
    metadata,
    Column("image_id", UUID(as_uuid=True), primary_key=True),
    Column("object_key", Text, nullable=False, unique=True),
    Column("original_sha256", SHA256, nullable=False),
    Column("processed_sha256", SHA256),
    Column("width_px", Integer),
    Column("height_px", Integer),
    Column("consent_basis", Text, nullable=False),
    Column("retention_until", DateTime(timezone=True), nullable=False),
    Column("deleted_at", DateTime(timezone=True)),
    synthetic(),
    created_at(),
    CheckConstraint("consent_basis <> ''", name="consent_required"),
    schema=TELEMETRY,
)

configurations = Table(
    "configurations",
    metadata,
    Column("config_id", Text, primary_key=True),
    Column("pipeline_id", Text, nullable=False),
    Column("model", Text),
    Column("parameters", JSONB, nullable=False, server_default="{}"),
    Column("prompt_hash", SHA256),
    Column("data_version", Text),
    Column("preprocessing_version", Text),
    Column("git_commit", String(40)),
    Column("locked", Boolean, nullable=False, server_default="false"),
    created_at(),
    schema=TELEMETRY,
)

RUN_STATUSES = "('complete', 'partial', 'abstained', 'failed')"

runs = Table(
    "runs",
    metadata,
    Column("run_id", Text, primary_key=True),  # = scan_id
    Column("pipeline_id", Text, nullable=False),
    Column(
        "config_id", Text, ForeignKey(f"{TELEMETRY}.configurations.config_id", ondelete="RESTRICT")
    ),
    Column(
        "image_id",
        UUID(as_uuid=True),
        ForeignKey(f"{TELEMETRY}.images.image_id", ondelete="SET NULL"),
    ),
    Column("batch_id", Text, index=True),
    Column("sample_id", Text, index=True),  # opaque here; labels live in benchmark
    Column("status", Text, nullable=False),
    Column("error_code", Text),
    Column("is_mock", Boolean, nullable=False),
    synthetic(),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True), nullable=False),
    Column("server_total_ms", Float, nullable=False),
    Column("logical_requests", Integer, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("model_calls", Integer, nullable=False),
    Column("retries", Integer, nullable=False),
    Column("timeouts", Integer, nullable=False),
    Column("blocked_attempts", Integer, nullable=False),
    Column("known_cost_usd", Numeric, nullable=False),
    Column("estimated_cost_usd", Numeric),  # NULL when any attempt cost is unknown
    CheckConstraint(f"status IN {RUN_STATUSES}", name="status"),
    CheckConstraint("finished_at >= started_at", name="time_order"),
    schema=TELEMETRY,
)

stage_events = Table(
    "stage_events",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "run_id",
        Text,
        ForeignKey(f"{TELEMETRY}.runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("span_id", Text, nullable=False),
    Column("parent_span_id", Text),
    Column("stage", Text, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("duration_ms", Float, nullable=False),
    Column("status", Text, nullable=False),
    Column("error_code", Text),
    Column("cache_state", Text, nullable=False),
    UniqueConstraint("run_id", "span_id"),
    CheckConstraint("duration_ms >= 0", name="duration_non_negative"),
    schema=TELEMETRY,
)

attempt_events = Table(
    "attempt_events",
    metadata,
    Column("attempt_id", Text, primary_key=True),
    Column(
        "run_id",
        Text,
        ForeignKey(f"{TELEMETRY}.runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("span_id", Text),
    Column("logical_request_id", Text, nullable=False),
    Column("attempt_number", Integer, nullable=False),
    Column("provider", Text, nullable=False),
    Column("operation", Text, nullable=False),
    Column("is_model_call", Boolean, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("duration_ms", Float, nullable=False),
    Column("timeout_s", Float, nullable=False),
    Column("outcome", Text, nullable=False),
    Column("http_status_class", Text),
    Column("retry_reason", Text),
    Column("retry_after_s", Float),
    Column("input_tokens", Integer),
    Column("output_tokens", Integer),
    Column("provider_model", Text),
    Column("cost_usd", Numeric),
    Column("cost_provenance", Text, nullable=False),
    Column("price_table_version", Text),
    UniqueConstraint("logical_request_id", "attempt_number"),
    schema=TELEMETRY,
)

permitted_results = Table(
    "permitted_results",
    metadata,
    Column(
        "run_id", Text, ForeignKey(f"{TELEMETRY}.runs.run_id", ondelete="CASCADE"), primary_key=True
    ),
    Column("source", Text, nullable=False),
    Column("policy_version", Text, nullable=False),
    Column("result", JSONB, nullable=False),  # already filtered by the storage policy
    Column("dropped_fields", JSONB, nullable=False),
    Column("expires_at", DateTime(timezone=True)),
    created_at(),
    schema=TELEMETRY,
)

corrections = Table(
    "corrections",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "run_id",
        Text,
        ForeignKey(f"{TELEMETRY}.runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("field", Text, nullable=False),
    Column("before", JSONB),
    Column("after", JSONB),
    Column("reason", Text),
    Column("author", Text, nullable=False),
    created_at(),
    schema=TELEMETRY,
)

# --- benchmark (evaluator only) ----------------------------------------------------------

samples = Table(
    "samples",
    metadata,
    Column("sample_id", Text, primary_key=True),
    Column(
        "image_id",
        UUID(as_uuid=True),
        ForeignKey(f"{TELEMETRY}.images.image_id", ondelete="RESTRICT"),  # locked manifests
        nullable=False,
    ),
    Column("group_id", Text, nullable=False, index=True),
    Column("category", Text, nullable=False),
    Column("split", Text, nullable=False),
    # 'abstain' marks inputs where abstaining is the correct answer (plan §11 difficult inputs).
    Column("expected_outcome", Text, nullable=False, server_default="estimate"),
    Column("reference_version", Text, nullable=False),
    synthetic(),
    created_at(),
    CheckConstraint("split IN ('development', 'calibration', 'test')", name="split"),
    CheckConstraint("expected_outcome IN ('estimate', 'abstain')", name="expected_outcome"),
    schema=BENCHMARK,
)

reference_items = Table(
    "reference_items",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "sample_id",
        Text,
        ForeignKey(f"{BENCHMARK}.samples.sample_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("verified_identity", Text, nullable=False),
    Column("preparation", Text),
    Column("edible_grams", Numeric, nullable=False),
    Column("reference_source", Text, nullable=False),
    Column("reviewer", Text, nullable=False),
    CheckConstraint("edible_grams > 0", name="edible_grams_positive"),
    schema=BENCHMARK,
)

reference_nutrients = Table(
    "reference_nutrients",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "sample_id",
        Text,
        ForeignKey(f"{BENCHMARK}.samples.sample_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("nutrient", Text, nullable=False),
    Column("amount", Numeric),
    Column("unit", Text, nullable=False),
    Column("method", Text, nullable=False),
    Column("quality_grade", String(1), nullable=False),
    UniqueConstraint("sample_id", "nutrient"),
    CheckConstraint("amount IS NULL OR amount >= 0", name="amount_non_negative"),
    CheckConstraint("quality_grade IN ('A', 'B', 'C')", name="quality_grade"),
    schema=BENCHMARK,
)

evaluation_metrics = Table(
    "evaluation_metrics",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "run_id",
        Text,
        ForeignKey(f"{TELEMETRY}.runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("reference_version", Text, nullable=False),
    Column("metric", Text, nullable=False),
    Column("value", Float),
    Column("unit", Text),
    Column("source", Text, nullable=False),
    Column("policy_version", Text, nullable=False),
    UniqueConstraint("run_id", "reference_version", "metric"),
    schema=BENCHMARK,
)

calibration_versions = Table(
    "calibration_versions",
    metadata,
    Column("version", Text, primary_key=True),
    Column("fitting_split", Text, nullable=False),
    Column("success_definition", Text, nullable=False),
    Column("bin_counts", JSONB, nullable=False),
    Column("rates", JSONB, nullable=False),
    Column("uncertainty", JSONB),
    created_at(),
    CheckConstraint("fitting_split <> 'test'", name="not_test_split"),
    schema=BENCHMARK,
)

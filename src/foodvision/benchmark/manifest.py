"""Benchmark reference manifest, version 1 (plan §11, POC-12).

One JSON document per meal/product **group**: every photo of one meal and every repeat of one
product shares a group, and groups of one recipe or product family share a `family_id`, so a
split can never separate them. A manifest is a directory of `<group_id>.json` files or a JSONL
file with one group per line.

Reference nutrients are never typed in: they are calculated in code from each component's
edible grams and its source values (with an explicit basis), or from a recipe's ingredients,
cooked yield and served weight. Unknown source values stay unknown (None), never 0.

Real manifests hold hidden evaluation labels. They live outside Git and are read only by
evaluator tooling; inference code never imports this package.
"""

import json
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from foodvision.contracts.results import FoodSource, Nutrients, Positive
from foodvision.nutrition.calculator import (
    BasisKind,
    FoodRecord,
    Portion,
    ReferenceBasis,
    SourceNutrient,
    calculate_item,
)
from foodvision.nutrition.units import NutritionError, QuantityUnit
from foodvision.recognition.hypotheses import Preparation

MANIFEST_VERSION = "benchmark-manifest-v1"
DEVELOPMENT_TARGET = 30  # first collection milestone (plan §11)
Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")]
Text = Annotated[str, Field(min_length=1, max_length=500)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Category(StrEnum):
    """Plan §11 dataset categories."""

    SINGLE_GENERIC = "single_generic"
    SEPARATED_PLATE = "separated_plate"
    COMPOSITE_DISH = "composite_dish"
    BRANDED_PACKAGED = "branded_packaged"
    DIFFICULT_UNSUPPORTED = "difficult_unsupported"


class Split(StrEnum):
    DEVELOPMENT = "development"
    CALIBRATION = "calibration"
    TEST = "test"


class Grade(StrEnum):
    A = "A"  # weighed components or recipe, reviewed source values
    B = "B"  # exact label/menu values with a reliable consumed amount
    C = "C"  # reviewer estimate: qualitative only, excluded from primary numeric accuracy


class Rights(StrEnum):
    OWNED = "owned"  # photographed by the team
    CONSENTED = "consented"  # photographed by a participant who signed consent
    # Stock, web or other third-party images are deliberately not representable.


class Measurement(StrEnum):
    WEIGHED = "weighed"  # edible grams weighed on a scale
    LABEL_DECLARED = "label_declared"  # net amount printed on a package, fully eaten
    ESTIMATED = "estimated"  # reviewer estimate (grade C only)


class SourceType(StrEnum):
    USDA_FDC = "usda_fdc"
    LABEL = "label"
    MENU = "menu"
    OTHER_REVIEWED = "other_reviewed"


class ExpectedOutcome(StrEnum):
    ESTIMATE = "estimate"  # a nutrition estimate is the correct behavior
    ABSTAIN = "abstain"  # e.g. a label-only photo or non-food: abstaining is correct


class Photo(Strict):
    photo_id: Identifier
    file: Text  # relative to the private benchmark data directory
    sha256: Sha256
    rights: Rights
    consent_reference: Text  # e.g. "self (Tony Jin)" or "consent form 2026-10-12 #3"
    retain_until: date


class NutrientValue(Strict):
    amount: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None
    unit: Literal["kcal", "kJ", "g", "mg"]


class SourceValues(Strict):
    """Nutrients of the source record per stated basis (never pre-scaled to the portion)."""

    source: SourceType
    source_ref: Text  # FDC ID ("fdc:168878"), label photo ID, menu URL/version, ...
    source_version: Text  # FDC release, label print date, menu date
    basis: BasisKind
    serving_quantity: Positive | None = None  # required for per_serving
    serving_unit: QuantityUnit | None = None
    density_g_per_ml: Positive | None = None  # needed when grams meet an ml basis
    energy: NutrientValue | None = None
    protein: NutrientValue | None = None
    carbohydrate: NutrientValue | None = None
    fat: NutrientValue | None = None

    @model_validator(mode="after")
    def _units_and_basis(self) -> Self:
        if self.energy is not None and self.energy.unit not in ("kcal", "kJ"):
            raise ValueError("energy must be in kcal or kJ")
        for name in ("protein", "carbohydrate", "fat"):
            value = getattr(self, name)
            if value is not None and value.unit not in ("g", "mg"):
                raise ValueError(f"{name} must be in g or mg")
        if self.basis is BasisKind.PER_SERVING:
            if self.serving_quantity is None or self.serving_unit is None:
                raise ValueError("per_serving values need serving_quantity and serving_unit")
        elif self.serving_quantity is not None or self.serving_unit is not None:
            raise ValueError(f"{self.basis} values must not set a serving size")
        return self

    def record(self) -> FoodRecord:
        basis = {
            BasisKind.PER_100G: (100.0, QuantityUnit.G),
            BasisKind.PER_100ML: (100.0, QuantityUnit.ML),
        }.get(self.basis, (self.serving_quantity, self.serving_unit))
        nutrients = {
            name: SourceNutrient(amount=value.amount, unit=value.unit)
            for name in ("energy", "protein", "carbohydrate", "fat")
            if (value := getattr(self, name)) is not None
        }
        source = FoodSource.USDA if self.source is SourceType.USDA_FDC else FoodSource.NONE
        return FoodRecord(
            food_id=self.source_ref,
            source=source,
            basis=ReferenceBasis(kind=self.basis, quantity=basis[0], unit=basis[1]),
            nutrients=nutrients,
            density_g_per_ml=self.density_g_per_ml,
        )


class Component(Strict):
    """One separately weighed, eaten food (or one recipe ingredient)."""

    identity: Text
    preparation: Preparation
    edible_grams: Positive
    measurement: Measurement
    values: SourceValues | None = None  # None: no reference values yet (reported as missing)


class Recipe(Strict):
    """Composite dish: ingredients as weighed raw, the cooked yield, and the grams served."""

    dish_identity: Text
    ingredients: list[Component] = Field(min_length=1)
    cooked_yield_grams: Positive
    served_grams: Positive

    @model_validator(mode="after")
    def _served_within_yield(self) -> Self:
        if self.served_grams > self.cooked_yield_grams:
            raise ValueError("served_grams cannot exceed cooked_yield_grams")
        return self


class Reviewer(Strict):
    reviewer: Text
    reviewed_on: date


class Review(Strict):
    status: Literal["draft", "reviewed"]
    reviewers: list[Reviewer] = Field(default_factory=list)
    disagreements_resolved: bool = True
    notes: str = ""

    @model_validator(mode="after")
    def _reviewed_needs_reviewer(self) -> Self:
        if self.status == "reviewed" and not self.reviewers:
            raise ValueError("a reviewed group needs at least one reviewer")
        if self.status == "reviewed" and not self.disagreements_resolved:
            raise ValueError("resolve reviewer disagreements before marking reviewed")
        return self


class Group(Strict):
    manifest_version: Literal["benchmark-manifest-v1"]
    group_id: Identifier
    family_id: Identifier | None = None  # recipe/product family; defaults to the group
    is_synthetic: bool
    category: Category
    region: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
    collected_on: date
    split: Split | None = None  # None until `foodvision assign-splits`
    quality_grade: Grade
    expected_outcome: ExpectedOutcome = ExpectedOutcome.ESTIMATE
    photos: list[Photo] = Field(min_length=1)
    components: list[Component] = Field(default_factory=list)
    recipe: Recipe | None = None
    review: Review

    @model_validator(mode="after")
    def _one_reference_method(self) -> Self:
        if self.expected_outcome is ExpectedOutcome.ABSTAIN:
            if self.components or self.recipe:
                raise ValueError("an abstain-expected group carries no nutrient reference")
            return self
        if bool(self.components) == (self.recipe is not None):
            raise ValueError("give either components or a recipe (exactly one)")
        return self

    @property
    def family_key(self) -> str:
        return self.family_id or self.group_id


class ReferenceTotals(BaseModel):
    """Reference nutrients for the whole eaten group, calculated in code."""

    nutrients: Nutrients
    missing_components: list[str]  # components without source values
    errors: list[str]  # unit/basis problems that block calculation
    method: str

    @property
    def complete(self) -> bool:
        return not self.missing_components and not self.errors and not self.nutrients.missing()


def _sum(values: list[Nutrients | None]) -> Nutrients:
    totals = {}
    for key in Nutrients.model_fields:
        amounts = [getattr(v, key) if v is not None else None for v in values]
        totals[key] = None if any(a is None for a in amounts) else sum(amounts)
    return Nutrients(**totals)


def _component_nutrients(component: Component, errors: list[str]) -> Nutrients | None:
    if component.values is None:
        return None
    try:
        return calculate_item(component.values.record(), Portion(amount=component.edible_grams))
    except NutritionError as exc:
        errors.append(f"{component.identity}: {exc}")
        return None


def reference_totals(group: Group) -> ReferenceTotals | None:
    """None for abstain-expected groups (no nutrient reference applies)."""
    if group.expected_outcome is ExpectedOutcome.ABSTAIN:
        return None
    errors: list[str] = []
    if group.recipe is not None:
        parts = group.recipe.ingredients
        fraction = group.recipe.served_grams / group.recipe.cooked_yield_grams
        method = "recipe: ingredients x served/cooked yield"
    else:
        parts, fraction, method = group.components, 1.0, "components: edible grams x source basis"
    values = [_component_nutrients(c, errors) for c in parts]
    missing = [c.identity for c in parts if c.values is None]
    total = _sum(values)
    scaled = Nutrients(
        **{k: None if v is None else v * fraction for k, v in total.model_dump().items()}
    )
    return ReferenceTotals(
        nutrients=scaled, missing_components=missing, errors=errors, method=method
    )


class ManifestFormatError(ValueError):
    pass


def load_groups(path: Path) -> tuple[list[Group], list[str]]:
    """Read a directory of group JSON files or a JSONL file. Returns (groups, errors)."""
    sources: list[tuple[str, str]] = []
    if path.is_dir():
        for file in sorted(path.glob("*.json")):
            sources.append((file.name, file.read_text(encoding="utf-8")))
    elif path.suffix == ".jsonl":
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                sources.append((f"{path.name}:{number}", line))
    else:
        raise ManifestFormatError(f"{path}: expected a directory of .json files or a .jsonl file")
    groups, errors = [], []
    for where, raw in sources:
        try:
            groups.append(Group.model_validate(json.loads(raw)))
        except json.JSONDecodeError as exc:
            errors.append(f"{where}: not valid JSON ({exc.msg}, line {exc.lineno})")
        except ValidationError as exc:
            for e in exc.errors(include_url=False, include_input=False):
                location = ".".join(str(p) for p in e["loc"]) or "<group>"
                errors.append(f"{where}: {location}: {e['msg']}")
    return groups, errors

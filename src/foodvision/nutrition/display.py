"""Display-only formatting. Calculation never rounds; only presentation does."""

DECIMALS: dict[str, int] = {"energy_kcal": 0, "protein_g": 1, "carbohydrate_g": 1, "fat_g": 1}
UNITS: dict[str, str] = {
    "energy_kcal": "kcal",
    "protein_g": "g",
    "carbohydrate_g": "g",
    "fat_g": "g",
}


def format_nutrient(key: str, value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:.{DECIMALS[key]}f} {UNITS[key]}"

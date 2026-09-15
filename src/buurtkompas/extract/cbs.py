"""Extract Kerncijfers wijken en buurten indicators for Eindhoven from the CBS StatLine OData v4 API."""

from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://datasets.cbs.nl/odata/v1/CBS"
TABLE_CODE = "85984NED"
GEMEENTE_CODE = "GM0772"  # Eindhoven

# measure_code -> (category, human-readable label)
MEASURES: dict[str, tuple[str, str]] = {
    "D000045": ("schools", "Afstand tot school"),
    "D000025": ("amenities", "Afstand tot grote supermarkt"),
    "D000029": ("amenities", "Afstand tot kinderdagverblijf"),
    "D000028": ("amenities", "Afstand tot huisartsenpraktijk"),
    "ST0001": ("quiet_nature", "Mate van stedelijkheid"),
    "M001642": ("housing", "Gemiddelde WOZ-waarde van woningen"),
    "1014800": ("housing", "Koopwoningen (%)"),
    "1014850_2": ("housing", "Huurwoningen totaal (%)"),
    "M000224": ("income", "Gemiddeld inkomen per inwoner"),
}

# Resident population per buurt. Deliberately kept out of MEASURES: it's a
# normalization denominator (e.g. politie.py's crimes-per-1,000 indicator),
# not itself a ranked indicator, so it's never tagged with a category or
# written to fact_indicator — see load/loader.py's dim_region.population.
POPULATION_MEASURE_CODE = "AantalInwoners_5"


def fetch_buurt_codes(gemeente_code: str) -> list[str]:
    """Return all buurt (neighborhood) codes belonging to the given gemeente."""
    response = requests.get(
        f"{BASE_URL}/{TABLE_CODE}/WijkenEnBuurtenCodes",
        params={"$filter": f"DimensionGroupId eq '{gemeente_code}'"},
    )
    response.raise_for_status()
    data = response.json()
    return [
        item["Identifier"]
        for item in data["value"]
        if item["Identifier"].startswith("BU")
    ]


def fetch_observations(measure_code: str, region_codes: list[str]) -> list[dict]:
    """Return {region_id, value} pairs for one measure across the given regions."""
    region_filter = ",".join(f"'{code}'" for code in region_codes)
    url = f"{BASE_URL}/{TABLE_CODE}/Observations"
    params = {
        "$filter": f"Measure eq '{measure_code}' and WijkenEnBuurten in ({region_filter})"
    }

    results = []
    while url:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        results.extend(
            {"region_id": obs["WijkenEnBuurten"], "value": obs["Value"]}
            for obs in data["value"]
        )
        # @odata.nextLink already contains a full query string, so params
        # must not be attached again on subsequent iterations.
        url = data.get("@odata.nextLink")
        params = None

    return results


def fetch_population(region_codes: list[str]) -> dict[str, int]:
    """Return {region_id: resident population} for the given buurt codes."""
    return {
        obs["region_id"]: obs["value"]
        for obs in fetch_observations(POPULATION_MEASURE_CODE, region_codes)
    }


def extract_population() -> pd.DataFrame:
    """Extract resident population per Eindhoven buurt, as its own table
    (region_id, population) rather than a long-format indicator row — this
    lands on dim_region, not fact_indicator, since it's a denominator, not
    a ranked indicator.
    """
    region_codes = fetch_buurt_codes(GEMEENTE_CODE)
    population = fetch_population(region_codes)
    return pd.DataFrame(
        [
            {"region_id": region_id, "population": value}
            for region_id, value in population.items()
        ]
    )


def extract_all() -> pd.DataFrame:
    """Extract all configured measures for Eindhoven's buurten into one long-format table."""
    region_codes = fetch_buurt_codes(GEMEENTE_CODE)

    rows = []
    for measure_code, (category, label) in MEASURES.items():
        for obs in fetch_observations(measure_code, region_codes):
            rows.append(
                {
                    "region_id": obs["region_id"],
                    "indicator_id": measure_code,
                    "indicator_label": label,
                    "category": category,
                    "value": obs["value"],
                }
            )

    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = extract_all()
    output_path = Path("data/raw/cbs_eindhoven.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"Wrote {len(df)} rows to {output_path}")

    population_df = extract_population()
    population_path = Path("data/raw/cbs_population_eindhoven.csv")
    population_df.to_csv(population_path, index=False)
    print(f"Wrote {len(population_df)} rows to {population_path}")

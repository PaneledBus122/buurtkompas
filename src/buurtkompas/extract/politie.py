"""Extract registered-crime counts (safety indicator) for Eindhoven and
Veldhoven from the CBS StatLine OData v3 API, table 47018NED ("Geregistreerde
misdrijven; soort misdrijf, wijk, buurt, jaarcijfers"), served from
dataderden.cbs.nl.

This is a different API generation from the OData v4 source in cbs.py
(85984NED): field names, response shape, and pagination-link key all
differ, so nothing is shared beyond the Eindhoven/Veldhoven buurt-code lookup
(`cbs.fetch_buurt_codes`), reused as-is to keep both sources joined against
the same 2024-vintage region set.

Per-region filtering happens client-side rather than via a `WijkenEnBuurten
in (...)` server-side filter (the pattern cbs.py uses): OData v3 doesn't
support the `in` operator, so the `$filter` here only uses simple scalar
equality (crime type + period), which is safe across both API generations.
"""

from pathlib import Path
from time import sleep

import pandas as pd
import requests

from buurtkompas.extract.cbs import GEMEENTE_CODES, fetch_buurt_codes

BASE_URL = "https://dataderden.cbs.nl/ODataFeed/odata/47018NED"
PERIOD = "2024JJ00"

# crime_type_code (SoortMisdrijf, including its trailing space) -> (category, label)
MEASURES: dict[str, tuple[str, str]] = {
    "0.0.0 ": ("safety", "Geregistreerde misdrijven (totaal aantal)"),
}

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.0


def _get_with_retry(url: str, params: dict | None = None) -> requests.Response:
    """GET with retry-on-transient-failure: connection errors and 5xx
    responses are retried with linear backoff; 4xx responses (a bad query)
    fail immediately since retrying won't help.
    """
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, params=params)
            if response.status_code < 500:
                response.raise_for_status()
                return response
            last_error = requests.exceptions.HTTPError(
                f"{response.status_code} error from {url}", response=response
            )
        except requests.exceptions.ConnectionError as exc:
            last_error = exc
        if attempt < MAX_RETRIES - 1:
            sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    assert last_error is not None
    raise last_error


def fetch_crime_counts(crime_type_code: str, region_codes: list[str]) -> list[dict]:
    """Return {region_id, value} pairs for one crime type across the given
    buurten, for the fixed PERIOD.

    Fetches the whole country for this (crime type, period) slice and
    filters to the wanted buurt codes client-side (see module docstring for
    why). CBS's crime data suppresses low-count buurten for privacy; a
    buurt simply absent from TypedDataSet surfaces here as a buurt missing
    from the result, handled downstream the same way as any other
    indicator's missing rows (no special-casing needed).
    """
    wanted = {code.strip() for code in region_codes}
    url = f"{BASE_URL}/TypedDataSet"
    params = {
        "$filter": f"SoortMisdrijf eq '{crime_type_code}' and Perioden eq '{PERIOD}'",
        # OData v3 defaults to Atom/XML (unlike v4, used by cbs.py, which
        # defaults to JSON) — without this, response.json() below raises
        # JSONDecodeError on the XML body.
        "$format": "json",
    }

    results = []
    while url:
        response = _get_with_retry(url, params=params)
        data = response.json()
        for row in data["value"]:
            region_id = row["WijkenEnBuurten"].strip()
            if region_id in wanted:
                results.append(
                    {"region_id": region_id, "value": row["GeregistreerdeMisdrijven_1"]}
                )
        # CBS's OData v3 feed uses the unprefixed "odata.nextLink" key
        # (v4, used by cbs.py, uses "@odata.nextLink" instead).
        url = data.get("odata.nextLink")
        params = None

    return results


def extract_all() -> pd.DataFrame:
    """Extract all configured crime-type measures for Eindhoven's and
    Veldhoven's buurten into one long-format table, matching cbs.py's extract_all() column
    shape so loader.py can load both sources uniformly.

    Values here are raw registered-crime counts, not yet normalized per
    1,000 residents — that normalization is done in dbt (see
    int_indicator_percentile.sql), which joins dim_region.population.
    """
    region_codes = fetch_buurt_codes(GEMEENTE_CODES)

    rows = []
    for crime_type_code, (category, label) in MEASURES.items():
        for obs in fetch_crime_counts(crime_type_code, region_codes):
            rows.append(
                {
                    "region_id": obs["region_id"],
                    "indicator_id": crime_type_code.strip(),
                    "indicator_label": label,
                    "category": category,
                    "value": obs["value"],
                }
            )

    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = extract_all()
    output_path = Path("data/raw/politie_eindhoven.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"Wrote {len(df)} rows to {output_path}")

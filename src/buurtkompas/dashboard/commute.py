"""Live, request-time commute-time computation via OpenRouteService (ORS).

Architecturally different from extract/*.py: those run as a batch ahead of
time and land in fact_indicator via load/loader.py; this module runs
synchronously against a user-supplied destination address on every dashboard
request, so there's no CSV/loader step at all — app.py calls
geocode_address()/fetch_commute_minutes() directly, behind st.cache_data
keyed on the address string so Streamlit's rerun-on-every-interaction model
doesn't silently re-burn ORS quota.

Field names below were verified against ORS's own live API and backend docs
before writing this, not assumed — see the feat/commute-time PR description
for the verification run. This project has twice shipped a bug from an
unverified field-name assumption (CBS's population measure code, politie's
missing $format=json), so this module in particular treats "looks like a
standard routing API" as not good enough:

- Geocoding (`GET /geocode/search`, Pelias-based): auth is the `api_key`
  query parameter (not a header); the response is a GeoJSON
  FeatureCollection ordered by relevance, so `features[0]` is the best
  match; `geometry.coordinates` is `[lon, lat]`, standard GeoJSON order.
- Matrix (`POST /v2/matrix/{profile}`): auth is an `Authorization` header
  (not a query parameter — different from Geocoding); `durations` in the
  response are in seconds and `null` for an unreachable pair.
"""

from __future__ import annotations

import os

import requests

GEOCODE_URL = "https://api.openrouteservice.org/geocode/search"
MATRIX_URL = "https://api.openrouteservice.org/v2/matrix/driving-car"

# ORS Matrix's hard cap is 3,500 origins x destinations per request. This
# module always queries all loaded buurten (Eindhoven + Veldhoven, 133) against exactly one
# destination, so it never comes close — this guard is here so a future
# change (e.g. multiple destinations) fails loudly instead of silently
# hitting ORS's 400.
_MATRIX_MAX_CELLS = 3500


def _api_key() -> str:
    """No default: a request signed with a placeholder/empty key would fail
    at ORS with a confusing 403, not here with a clear message pointing at
    the actual missing setting.
    """
    try:
        return os.environ["ORS_API_KEY"]
    except KeyError as exc:
        raise RuntimeError(
            "ORS_API_KEY environment variable is not set. Get a free "
            "OpenRouteService API key at "
            "https://openrouteservice.org/dev/#/signup and set it in the "
            "environment before using the commute-time feature."
        ) from exc


def geocode_address(address: str) -> tuple[float, float] | None:
    """Forward-geocode a free-text address via ORS's Geocoding API.

    Returns the best match's (lon, lat), or None if ORS recognized no
    location at all for this text (an empty `features` list) — the caller
    is expected to turn that into a user-facing "address not found" message
    rather than treating it as an exception.
    """
    response = requests.get(
        GEOCODE_URL,
        params={"api_key": _api_key(), "text": address},
        timeout=10,
    )
    response.raise_for_status()
    features = response.json().get("features", [])
    if not features:
        return None
    lon, lat = features[0]["geometry"]["coordinates"]
    return (lon, lat)


def fetch_commute_minutes(
    destination: tuple[float, float], origins: list[tuple[float, float]]
) -> list[float | None]:
    """Drive-time (profile "driving-car") from each of `origins` to the
    single `destination`, in minutes, in the same order as `origins` —
    one ORS Matrix request for all of them, not one request per origin.

    A None entry means ORS found no route for that origin (e.g. a buurt
    point ORS's road network can't reach) — not treated as an error, since
    it's the same "missing data" shape the rest of the project already
    handles (see fct_category_score's coverage-threshold gating).
    """
    if len(origins) > _MATRIX_MAX_CELLS:
        raise ValueError(
            f"{len(origins)} origins x 1 destination exceeds ORS Matrix's "
            f"{_MATRIX_MAX_CELLS}-cell limit for a single request."
        )

    locations = [[lon, lat] for lon, lat in origins] + [
        [destination[0], destination[1]]
    ]
    destination_index = len(origins)

    response = requests.post(
        MATRIX_URL,
        json={
            "locations": locations,
            "sources": list(range(len(origins))),
            "destinations": [destination_index],
            "metrics": ["duration"],
        },
        headers={
            "Authorization": _api_key(),
            "Content-Type": "application/json; charset=utf-8",
        },
        timeout=30,
    )
    response.raise_for_status()
    durations = response.json()["durations"]  # seconds; one row per origin
    return [None if row[0] is None else row[0] / 60 for row in durations]


def _percent_rank_ascending(values: list[float]) -> list[float]:
    """Postgres `percent_rank()` semantics: tied values share the rank of
    the first element in their tie group, and percent_rank = (rank - 1) /
    (n - 1) (0.0 for every row when n <= 1). Reimplemented here in plain
    Python because this module has no SQL window function to lean on — the
    commute score is computed live, not by a dbt model.
    """
    n = len(values)
    if n <= 1:
        return [0.0] * n

    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = i
        i = j + 1

    return [rank / (n - 1) for rank in ranks]


def compute_commute_percentiles(
    durations_by_region: dict[str, float | None],
) -> dict[str, float | None]:
    """Percentile-rank commute minutes across regions: 1.0 = best (shortest
    commute), 0.0 = worst — same lower_is_better convention, and the same
    exclude-then-map-back handling of missing values, as dbt's
    int_indicator_percentile/fct_category_score models use for every other
    indicator. Computed in Python instead of SQL because commute time isn't
    a stored fact_indicator row; it only exists for the lifetime of one
    dashboard lookup.

    A region with a None duration (ORS found no route) gets a None score
    here too, and isn't counted toward the other regions' ranks — same
    "doesn't clear coverage" shape as a category score, not silently
    dropped from the output and not scored as if it were 0.
    """
    usable = {
        region_id: minutes
        for region_id, minutes in durations_by_region.items()
        if minutes is not None
    }
    if not usable:
        return dict.fromkeys(durations_by_region, None)

    region_ids = list(usable.keys())
    # Lower minutes = better, so negate before ranking ascending — same
    # sign-flip int_indicator_percentile.sql applies for any
    # lower_is_better indicator, e.g. distance to school.
    sort_values = [-usable[region_id] for region_id in region_ids]
    percentiles = _percent_rank_ascending(sort_values)

    scores: dict[str, float | None] = dict.fromkeys(durations_by_region, None)
    for region_id, score in zip(region_ids, percentiles):
        scores[region_id] = score
    return scores

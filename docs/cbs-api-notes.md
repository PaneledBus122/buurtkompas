# CBS StatLine API — buurtkompas usage notes

## Dataset
- Name: Kerncijfers wijken en buurten 2024
- Table code: **85984NED**
- Official page: https://www.cbs.nl/nl-nl/cijfers/detail/85984NED
- Note: a 2025 edition also exists ([data.overheid.nl](https://data.overheid.nl/dataset/66299-kerncijfers-wijken-en-buurten-2025)) — re-check the latest table code before actual implementation

## API basics
- Protocol: OData v4
- Official docs:
  - [Snelstartgids OData v4](https://www.cbs.nl/nl-nl/onze-diensten/open-data/statline-als-open-data/snelstartgids-odata-v4)
  - [Informatie voor ontwikkelaars](https://www.cbs.nl/nl-nl/statline/dataportaal/informatie/informatie-voor-ontwikkelaars)
- Base URL: `https://datasets.cbs.nl/odata/v1/CBS/<table-code>`
- Sub-entity sets:
  - `Properties` (Singleton) — dataset-level metadata
  - `Dimensions` — the dataset's dimension structure
  - `MeasureGroups` / `MeasureCodes` — indicator taxonomy and codes
  - `WijkenEnBuurtenGroups` / `WijkenEnBuurtenCodes` — region taxonomy and codes
  - `Observations` — actual data values
- Pagination: responses exceeding 100,000 cells include `@odata.nextLink` — loop until fully fetched
- Filter syntax: `$filter=contains(<field>,'<string>')`; equality uses `eq` (e.g. `$filter=DimensionGroupId eq 'GM0772'`)

## Gotcha: region code lookup
- ❌ `$filter=contains(Title,'Eindhoven')` — text matching on the name produces **false positives** (matched a street name in an unrelated municipality that happened to contain "Eindhoven")
- ✅ `$filter=DimensionGroupId eq 'GM0772'` — filtering by parent region code is accurate
- Eindhoven municipality (gemeente) code: **`GM0772`**
- Code scheme: `GM`+4 digits (municipality) / `WK`+6 digits (district) / `BU`+8 digits (neighborhood)
- MVP comparison unit: **buurt** (finest-grained level)

## Phase 1 MVP indicator selection (Eindhoven only)

| Category | Measure ID | Title |
|---|---|---|
| Schools/education | `D000045` | Afstand tot school (distance to school) |
| Safety | — | Not in this table → sourced from 47018NED instead, see below |
| Amenities | `D000025` | Afstand tot grote supermarkt (distance to large supermarket) |
| Amenities | `D000029` | Afstand tot kinderdagverblijf (distance to daycare) |
| Amenities | `D000028` | Afstand tot huisartsenpraktijk (distance to GP practice) |
| Quiet/nature | `ST0001` | Mate van stedelijkheid (urbanity level 1–5, proxy) |
| Transport/commute | — | Not in this table → excluded from Phase 1 MVP, to be computed later from PDOK transit-stop data |
| Housing | `M001642` | Gemiddelde WOZ-waarde van woningen (average assessed home value) |
| Housing | `1014800` | Koopwoningen (% owner-occupied) |
| Housing | `1014850_2` | Huurwoningen totaal (% rented) |
| (Unassigned, reference only) | `M000224` | Gemiddeld inkomen per inwoner (average income per resident) |

## Next steps
- Query the `Observations` endpoint to confirm the actual data shape
- Write extraction code mapping region code × indicator code → value (`src/buurtkompas/extract/cbs.py`)

## Safety indicator: 47018NED (a different API generation)
- Name: Geregistreerde misdrijven; soort misdrijf, wijk, buurt, jaarcijfers
- Table code: **47018NED**, served from `dataderden.cbs.nl` (not `datasets.cbs.nl`)
- Protocol: **OData v3** — a different shape from the OData v4 API above:
  - Base URL: `https://dataderden.cbs.nl/ODataFeed/odata/47018NED`
  - Entity sets: `TypedDataSet`, `UntypedDataSet`, `TableInfos`, `DataProperties`, `CategoryGroups`, `SoortMisdrijf`, `WijkenEnBuurten`, `Perioden`
  - Pagination link key is the unprefixed `odata.nextLink` (v4 uses `@odata.nextLink`)
  - No `in (...)` filter support — per-region filtering is done client-side in `politie.py` rather than server-side like `cbs.py`'s `Observations` query
- `TypedDataSet` row shape (confirmed live sample):
  ```json
  {"ID":0,"SoortMisdrijf":"0.0.0 ","WijkenEnBuurten":"NL00      ","Perioden":"2012JJ00","GeregistreerdeMisdrijven_1":1127693,"Gemeentenaam_2":"...","SoortRegio_3":"..."}
  ```
  `GeregistreerdeMisdrijven_1` is a raw count (unit "aantal"), hence the per-1,000-residents normalization done in dbt.
- `SoortMisdrijf` key `"0.0.0 "` (note the trailing space) = total registered crimes; v1 uses only this total, no subtype breakdown.
- Period used: `"2024JJ00"`, matching the vintage year of the 85984NED kerncijfers extract.
- Gotcha: `WijkenEnBuurten` in 47018NED uses the 2025 wijk/buurt boundary classification, while `dim_region` (from PDOK/85984NED) uses the 2024 classification. Expect a small number of buurt-code mismatches from boundary changes — these surface as ordinary coverage gaps (a buurt missing from the crime data), not errors.
- Population denominator: CBS 85984NED, measure code `T001036` ("Aantal inwoners") — fetched by `cbs.py`, stored on `dim_region.population`, not as a second population figure from 47018NED. Verified live: `Observations?$filter=Measure eq 'T001036' and WijkenEnBuurten eq 'GM0772'` returns 246417, matching Eindhoven's actual population. (Note: `AantalInwoners_5` — a human-facing StatLine variable name, not the OData v4 Measure identifier — was the wrong value used in an earlier revision of this extractor.)
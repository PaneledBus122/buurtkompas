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
| Safety | — | Not in this table → separate source needed (politieopendata.cbs.nl) |
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
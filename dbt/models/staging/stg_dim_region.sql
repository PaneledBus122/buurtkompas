-- Thin passthrough from the raw Load-step table. No renaming or filtering
-- needed yet; kept as its own model (rather than querying the source
-- directly from downstream models) so a future cleanup step has one place
-- to land, and so intermediate/marts models never reference `source()`
-- directly.
select
    region_id,
    region_level,
    name,
    gemeente_code,
    geometry
from {{ source('buurtkompas_raw', 'dim_region') }}

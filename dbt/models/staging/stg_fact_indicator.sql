-- `where value is not null` is defensive, not load-bearing: loader.py
-- currently writes every extracted row regardless of nullness, so a NULL
-- value here means CBS itself withheld the figure (e.g. small-population
-- privacy suppression) rather than an extraction bug. Filtering here means
-- every downstream model can treat "the row exists" as "the value is usable"
-- without repeating the null check everywhere.
select
    region_id,
    indicator_id,
    year,
    value
from {{ source('buurtkompas_raw', 'fact_indicator') }}
where value is not null

select
    indicator_id,
    category,
    unit,
    source,
    description
from {{ source('buurtkompas_raw', 'dim_indicator') }}

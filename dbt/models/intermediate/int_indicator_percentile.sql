-- Per-indicator percentile rank, partitioned by gemeente_code (city).
--
-- Ranking within a city rather than nationally is a deliberate design
-- choice — see eindhoven-dashboard-plan.md, "Phase 3/7 스코어링 방법론".
-- With only Eindhoven loaded so far this partition is a no-op (one
-- gemeente_code value), but it's already correct for when a second city's
-- data lands: a buurt should never be judged against a completely
-- different city's supermarket/school geography.
--
-- percentile_score is defined so that 1.0 is always "best" and 0.0 is
-- always "worst", regardless of the indicator's raw direction: for a
-- lower_is_better indicator (e.g. distance to school), the sign is flipped
-- before ranking so a short distance still ends up near 1.0.

with fact as (
    select * from {{ ref('stg_fact_indicator') }}
),

region as (
    select region_id, gemeente_code, population from {{ ref('stg_dim_region') }}
),

direction as (
    select * from {{ ref('indicator_direction') }}
),

joined as (
    select
        fact.region_id,
        fact.indicator_id,
        fact.year,
        -- politie.py's crime indicator ('0.0.0') stores a raw registered-
        -- crime count in fact.value; buurt population varies too much to
        -- rank on that directly (it would just reward small buurten), so
        -- it's normalized to crimes per 1,000 residents here — the one
        -- place indicator values become comparable across regions. Every
        -- other indicator's value passes through unchanged.
        case
            when fact.indicator_id = '0.0.0'
                then (fact.value / nullif(region.population, 0)) * 1000
            else fact.value
        end as value,
        region.gemeente_code,
        direction.direction
    from fact
    inner join region on fact.region_id = region.region_id
    inner join direction on fact.indicator_id = direction.indicator_id
    where fact.year = {{ var('data_year') }}
),

-- A NULL/zero population turns the case above into a NULL value for the
-- crime indicator, same shape of missingness as any other suppressed
-- CBS figure — filtered out here for the same reason stg_fact_indicator
-- filters `value is not null`: so downstream can treat "row exists" as
-- "value is usable" without repeating the check.
usable as (
    select * from joined where value is not null
),

sortable as (
    select
        *,
        case
            when direction = 'lower_is_better' then -1 * value
            else value
        end as sort_value
    from usable
)

select
    region_id,
    indicator_id,
    year,
    gemeente_code,
    value,
    direction,
    percent_rank() over (
        partition by gemeente_code, indicator_id, year
        order by sort_value
    ) as percentile_score
from sortable

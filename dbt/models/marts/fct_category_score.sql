-- Per-region, per-category score, re-ranked as a percentile within the
-- region's own gemeente (city).
--
-- Two design decisions from the Check je wijk benchmarking discussion
-- (see eindhoven-dashboard-plan.md, decision log) are implemented here:
--
-- 1. Coverage threshold: a category score only exists for a region if a
--    *majority* of that category's indicators have real data for it
--    (>= ceil(total/2)). A region below the threshold gets an explicit
--    NULL, not a score quietly averaged over 1-of-3 indicators.
--
-- 2. Re-ranking: averaging several independent percentile scores clumps
--    the result toward the median (a weighted-average composite is not
--    itself uniformly distributed), so the raw averaged score is
--    re-ranked with its own percent_rank() to restore a meaningful,
--    uniformly-spread "top X%" scale. `category_score` below is this
--    re-ranked value; `raw_category_score` is kept alongside it for
--    debugging/transparency, not for display.

{% set data_year = var('data_year') %}

with categories as (
    select distinct category
    from {{ ref('stg_dim_indicator') }}
),

category_indicator_counts as (
    select
        category,
        count(distinct indicator_id) as total_indicators
    from {{ ref('stg_dim_indicator') }}
    group by category
),

-- Explicitly enumerate every (region, category) pair that *should* exist,
-- so a region with zero data in a category surfaces as a real NULL row
-- below instead of silently vanishing from a plain GROUP BY.
region_category as (
    select
        region.region_id,
        region.gemeente_code,
        categories.category
    from {{ ref('stg_dim_region') }} as region
    cross join categories
),

indicator_scores as (
    select
        percentile.region_id,
        indicator.category,
        avg(percentile.percentile_score) as raw_category_score,
        count(distinct percentile.indicator_id) as available_indicators
    from {{ ref('int_indicator_percentile') }} as percentile
    inner join {{ ref('stg_dim_indicator') }} as indicator
        on percentile.indicator_id = indicator.indicator_id
    group by percentile.region_id, indicator.category
),

gated as (
    select
        region_category.region_id,
        region_category.gemeente_code,
        region_category.category,
        {{ data_year }} as year,
        case
            when indicator_scores.available_indicators
                >= ceil(category_indicator_counts.total_indicators / 2.0)
                then indicator_scores.raw_category_score
            else null
        end as raw_category_score
    from region_category
    left join indicator_scores
        on region_category.region_id = indicator_scores.region_id
        and region_category.category = indicator_scores.category
    inner join category_indicator_counts
        on region_category.category = category_indicator_counts.category
),

-- percent_rank() is computed only over the non-NULL (gated) rows, then
-- left-joined back onto the full `gated` set — otherwise Postgres would
-- sort NULLs last by default and hand them a real (wrong) percentile
-- instead of leaving them NULL.
ranked as (
    select
        region_id,
        gemeente_code,
        category,
        year,
        percent_rank() over (
            partition by gemeente_code, category, year
            order by raw_category_score
        ) as category_score
    from gated
    where raw_category_score is not null
)

select
    gated.region_id,
    gated.gemeente_code,
    gated.category,
    gated.year,
    gated.raw_category_score,
    ranked.category_score
from gated
left join ranked
    on gated.region_id = ranked.region_id
    and gated.category = ranked.category
    and gated.year = ranked.year

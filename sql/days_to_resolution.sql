-- Days-to-resolution summary over delinquency episodes (see delinquency_episodes.sql).
SELECT
    CASE WHEN max_dpd <= 30 THEN '1-30' WHEN max_dpd <= 60 THEN '31-60'
         WHEN max_dpd <= 90 THEN '61-90' ELSE '90+' END            AS worst_bucket,
    count(*)                                                        AS episodes,
    avg(CASE WHEN resolved THEN 1.0 ELSE 0 END)                     AS resolved_share,
    median(days_to_resolution)                                      AS median_days,
    quantile_cont(days_to_resolution, 0.9)                          AS p90_days
FROM episodes
GROUP BY 1
ORDER BY 1;

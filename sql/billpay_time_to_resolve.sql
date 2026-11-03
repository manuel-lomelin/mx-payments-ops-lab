-- Time to resolve transfers that had at least one return, split by how they were resolved.
SELECT
    CASE WHEN final_status = 'settled' THEN 'auto-retry recovered'
         ELSE 'needs human' END                AS resolution_path,
    count(*)                                   AS payments,
    median(resolution_s) / 3600.0              AS median_hours,
    quantile_cont(resolution_s, 0.9) / 3600.0  AS p90_hours,
    sum(amount_mxn)                            AS amount_mxn
FROM payments
WHERE had_return
GROUP BY 1
ORDER BY 1;

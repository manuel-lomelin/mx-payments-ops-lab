-- Cure rate: share of accounts delinquent (DPD > 0) at month t that are current at t+1.
WITH t AS (
    SELECT
        account_id,
        statement_month,
        dpd_bucket,
        status,
        lead(dpd_bucket) OVER (PARTITION BY account_id ORDER BY statement_month) AS next_bucket
    FROM statements
)
SELECT
    statement_month,
    count(*)                                                             AS delinquent_accounts,
    avg(CASE WHEN next_bucket = 'current' THEN 1.0 ELSE 0 END)           AS cure_rate,
    avg(CASE WHEN dpd_bucket = '1-30'
             THEN (next_bucket = 'current')::INTEGER END)                AS cure_rate_1_30,
    avg(CASE WHEN dpd_bucket <> '1-30'
             THEN (next_bucket = 'current')::INTEGER END)                AS cure_rate_31_plus
FROM t
WHERE dpd_bucket <> 'current' AND status = 'active' AND next_bucket IS NOT NULL
GROUP BY 1
ORDER BY 1;

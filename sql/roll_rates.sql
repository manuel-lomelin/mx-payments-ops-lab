-- Month-over-month roll-rate matrix: share of accounts in bucket X at month t
-- that sit in bucket Y at month t+1. Pooled over every consecutive month pair.
WITH states AS (
    SELECT
        account_id,
        statement_month,
        CASE WHEN status = 'charged_off' THEN 'charged_off' ELSE dpd_bucket END AS bucket
    FROM statements
),
transitions AS (
    SELECT
        bucket AS from_bucket,
        lead(bucket) OVER (PARTITION BY account_id ORDER BY statement_month) AS to_bucket
    FROM states
)
SELECT
    from_bucket,
    to_bucket,
    count(*)                                                     AS accounts,
    count(*) / sum(count(*)) OVER (PARTITION BY from_bucket)     AS roll_rate
FROM transitions
WHERE to_bucket IS NOT NULL AND from_bucket <> 'charged_off'
GROUP BY 1, 2
ORDER BY 1, 2;

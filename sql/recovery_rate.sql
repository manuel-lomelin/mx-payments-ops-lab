-- Recovery rate on accounts that reached 90+ DPD inside the window:
-- cash collected from the first 90+ month onward / balance at first 90+ month.
WITH first_90 AS (
    SELECT account_id, min(statement_month) AS entered_90_at
    FROM statements
    WHERE dpd > 90
    GROUP BY 1
),
exposure AS (
    SELECT f.account_id, f.entered_90_at, s.balance AS balance_at_90
    FROM first_90 f
    JOIN statements s ON s.account_id = f.account_id AND s.statement_month = f.entered_90_at
),
recovered AS (
    SELECT e.account_id, coalesce(sum(s.paid_amount), 0) AS recovered_mxn
    FROM exposure e
    JOIN statements s ON s.account_id = e.account_id AND s.statement_month > e.entered_90_at
    GROUP BY 1
)
SELECT
    a.segment,
    count(*)                                          AS accounts_90_plus,
    sum(e.balance_at_90)                              AS exposure_mxn,
    sum(coalesce(r.recovered_mxn, 0))                 AS recovered_mxn,
    sum(coalesce(r.recovered_mxn, 0)) / nullif(sum(e.balance_at_90), 0) AS recovery_rate
FROM exposure e
JOIN accounts a USING (account_id)
LEFT JOIN recovered r USING (account_id)
GROUP BY ROLLUP (a.segment)
ORDER BY a.segment NULLS LAST;

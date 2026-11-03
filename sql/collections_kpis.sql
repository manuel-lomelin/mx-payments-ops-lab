-- Headline collections KPIs at the latest statement month.
WITH latest AS (
    SELECT * FROM statements WHERE statement_month = (SELECT max(statement_month) FROM statements)
)
SELECT
    max(statement_month)                                             AS as_of,
    count(*)                                                         AS accounts,
    sum(balance)                                                     AS balance_mxn,
    avg(CASE WHEN dpd > 0 THEN 1.0 ELSE 0 END)                       AS delinquency_rate,
    avg(CASE WHEN dpd > 30 THEN 1.0 ELSE 0 END)                      AS dpd_30_plus_rate,
    sum(CASE WHEN dpd > 30 THEN balance ELSE 0 END) / sum(balance)   AS balance_30_plus_share,
    sum(past_due_amount)                                             AS past_due_mxn
FROM latest;

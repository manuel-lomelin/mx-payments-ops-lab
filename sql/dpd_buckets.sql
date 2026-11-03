-- Portfolio by DPD bucket and statement month (accounts and balance).
SELECT
    statement_month,
    CASE WHEN status = 'charged_off' THEN 'charged_off' ELSE dpd_bucket END AS bucket,
    count(*)                                                AS accounts,
    sum(balance)                                            AS balance_mxn,
    count(*) / sum(count(*)) OVER (PARTITION BY statement_month)          AS share_accounts,
    sum(balance) / sum(sum(balance)) OVER (PARTITION BY statement_month)  AS share_balance
FROM statements
GROUP BY 1, 2
ORDER BY 1, CASE bucket WHEN 'current' THEN 0 WHEN '1-30' THEN 1 WHEN '31-60' THEN 2
                        WHEN '61-90' THEN 3 WHEN '90+' THEN 4 ELSE 5 END;

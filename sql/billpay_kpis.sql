-- Headline BillPay KPIs for one simulated run.
-- payments: one row per payment instruction sent (see core/spei_sim.py).
SELECT
    count(*)                                                        AS payments,
    avg(CASE WHEN final_status = 'settled' THEN 1.0 ELSE 0 END)     AS success_rate,
    avg(CASE WHEN final_status = 'settled' AND attempts = 1
             THEN 1.0 ELSE 0 END)                                   AS first_attempt_success_rate,
    avg(CASE WHEN had_return THEN 1.0 ELSE 0 END)                   AS payments_with_return_rate,
    median(settlement_s)                                            AS median_settlement_s,
    quantile_cont(settlement_s, 0.9)                                AS p90_settlement_s,
    median(resolution_s) FILTER (WHERE had_return) / 3600.0         AS median_hours_to_resolve_failed,
    quantile_cont(resolution_s, 0.9) FILTER (WHERE had_return) / 3600.0
                                                                    AS p90_hours_to_resolve_failed,
    sum(amount_mxn) FILTER (WHERE final_status = 'settled')         AS settled_amount_mxn
FROM payments;

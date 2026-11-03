-- Promise-to-pay outcomes: kept / broken / pending, overall and by DPD bucket at promise.
SELECT
    CASE WHEN dpd_at_promise <= 30 THEN '1-30' WHEN dpd_at_promise <= 60 THEN '31-60'
         WHEN dpd_at_promise <= 90 THEN '61-90' ELSE '90+' END                AS bucket_at_promise,
    count(*)                                                                  AS promises,
    count(*) FILTER (WHERE outcome = 'kept')                                  AS kept,
    count(*) FILTER (WHERE outcome = 'broken')                                AS broken,
    count(*) FILTER (WHERE outcome = 'pending')                               AS pending,
    count(*) FILTER (WHERE outcome = 'kept')
        / nullif(count(*) FILTER (WHERE outcome IN ('kept', 'broken')), 0)    AS kept_rate,
    sum(promised_amount)                                                      AS promised_mxn,
    sum(paid_amount_next) FILTER (WHERE outcome = 'kept')                     AS paid_next_statement_mxn
FROM promises
GROUP BY ROLLUP (1)
ORDER BY 1 NULLS LAST;

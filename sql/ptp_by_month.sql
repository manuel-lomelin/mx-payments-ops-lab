-- Promise-to-pay kept rate by the month the promise was made.
SELECT
    created_at                                                                AS promise_month,
    count(*)                                                                  AS promises,
    count(*) FILTER (WHERE outcome = 'kept')
        / nullif(count(*) FILTER (WHERE outcome IN ('kept', 'broken')), 0)    AS kept_rate
FROM promises
GROUP BY 1
ORDER BY 1;

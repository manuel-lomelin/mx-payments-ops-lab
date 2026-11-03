-- Returns (devoluciones) by reason, over all send attempts.
WITH totals AS (SELECT count(*) AS attempts FROM attempts)
SELECT
    reason,
    reason_label,
    count(*)                                   AS returns,
    count(*) / max(totals.attempts)            AS return_rate_per_attempt,
    count(*) / sum(count(*)) OVER ()           AS share_of_returns,
    avg(CASE WHEN was_pending THEN 1.0 ELSE 0 END) AS share_after_pending
FROM attempts, totals
WHERE status = 'returned'
GROUP BY reason, reason_label
ORDER BY returns DESC;

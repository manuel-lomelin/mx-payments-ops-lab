-- Delinquency episodes (gaps and islands): a run of consecutive statements with DPD > 0.
-- Episode start = first delinquent statement date minus its DPD (the missed due date).
-- Resolution = date of the payment that brought the account current.
-- Episodes still open at the end of the window are right-censored (resolved = false).
WITH flagged AS (
    SELECT
        account_id,
        statement_month,
        dpd,
        dpd > 0 AS delinquent,
        lag(dpd > 0, 1, false) OVER w AS prev_delinquent
    FROM statements
    WINDOW w AS (PARTITION BY account_id ORDER BY statement_month)
),
islands AS (
    SELECT
        *,
        sum(CASE WHEN delinquent AND NOT prev_delinquent THEN 1 ELSE 0 END) OVER (
            PARTITION BY account_id ORDER BY statement_month
        )::INTEGER AS episode_no
    FROM flagged
),
episodes AS (
    SELECT
        account_id,
        episode_no,
        min(statement_month) FILTER (WHERE delinquent) AS start_month,
        arg_min(dpd, statement_month) FILTER (WHERE delinquent) AS first_dpd,
        min(statement_month) FILTER (WHERE NOT delinquent) AS cured_month,
        max(dpd) AS max_dpd
    FROM islands
    WHERE episode_no > 0
    GROUP BY 1, 2
),
cure_payment AS (
    SELECT e.account_id, e.episode_no, max(p.paid_at) AS cured_at
    FROM episodes e
    JOIN payments p
        ON p.account_id = e.account_id
       AND date_trunc('month', p.paid_at) = date_trunc('month', e.cured_month)
    GROUP BY 1, 2
)
SELECT
    e.account_id,
    e.episode_no,
    (e.start_month - to_days(e.first_dpd))::DATE AS delinquent_since,
    c.cured_at::DATE AS cured_at,
    e.max_dpd,
    e.cured_month IS NOT NULL AS resolved,
    date_diff('day', e.start_month - to_days(e.first_dpd), c.cured_at) AS days_to_resolution
FROM episodes e
LEFT JOIN cure_payment c USING (account_id, episode_no)
ORDER BY e.account_id, e.episode_no;

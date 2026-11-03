-- Vintage curves: share of each origination cohort that has EVER been 30+ DPD
-- (DPD > 30) by months on book. Cohorts are left-truncated: only months on book that fall
-- inside the 12-month statement window are observed.
WITH ever AS (
    SELECT
        s.account_id,
        a.cohort,
        s.months_on_book,
        max(CASE WHEN s.dpd > 30 THEN 1 ELSE 0 END) OVER (
            PARTITION BY s.account_id ORDER BY s.months_on_book
        ) AS ever_30_plus
    FROM statements s
    JOIN accounts a USING (account_id)
)
SELECT
    cohort,
    months_on_book,
    count(*)            AS accounts,
    avg(ever_30_plus)   AS ever_30_plus_rate
FROM ever
GROUP BY 1, 2
HAVING count(*) >= 10
ORDER BY 1, 2;

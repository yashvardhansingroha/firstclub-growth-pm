-- FirstClub analysis queries (run on firstclub.db: users, sessions, orders).
-- PostgreSQL + SQLite compatible: only CTEs, CASE WHEN, COUNT(DISTINCT), LAG(), NTILE(3).

-- QUERY 1 — FUNNEL & QUALITY-BADGE DROP-OFF. Explain it as: walk the funnel left to right
-- (catalog view -> cart -> order), then split by badge click to show trust lifts conversion.
WITH funnel AS (
    SELECT category,
           clicked_quality_badge,
           COUNT(DISTINCT session_id) AS sessions,   -- every session viewed the catalog (=1)
           SUM(added_to_cart)        AS carts,
           SUM(completed_order)      AS orders_done
    FROM sessions
    GROUP BY category, clicked_quality_badge
)
SELECT category,
       clicked_quality_badge,
       sessions,
       carts,
       orders_done,
       ROUND(100.0 * (sessions - carts)    / sessions,         1) AS catalog_to_cart_dropoff_pct,
       ROUND(100.0 * (carts - orders_done) / NULLIF(carts, 0), 1) AS cart_to_order_dropoff_pct
FROM funnel
ORDER BY category, clicked_quality_badge;

-- QUERY 2 — D1/D7/D30 RETENTION & INTER-ORDER LATENCY. Explain it as: dates become plain day
-- numbers (portable), LAG() gives each order's gap to the previous one, and we flag returns
-- within 1/7/30 days of each user's Order #3, the milestone set by each user's first order.
WITH o AS (
    SELECT s.user_id,
           u.initial_category_width,
           s.order_date,
           s.order_seq_num,
           -- day number = year*365 + days-before-month + day (non-leap year, 2025 data)
           CAST(SUBSTR(CAST(s.order_date AS VARCHAR), 1, 4) AS INT) * 365
         + CASE CAST(SUBSTR(CAST(s.order_date AS VARCHAR), 6, 2) AS INT)
               WHEN 1 THEN 0   WHEN 2 THEN 31  WHEN 3 THEN 59  WHEN 4 THEN 90
               WHEN 5 THEN 120 WHEN 6 THEN 151 WHEN 7 THEN 181 WHEN 8 THEN 212
               WHEN 9 THEN 243 WHEN 10 THEN 273 WHEN 11 THEN 304 ELSE 334 END
         + CAST(SUBSTR(CAST(s.order_date AS VARCHAR), 9, 2) AS INT) AS day_num
    FROM orders s
    JOIN users u ON u.user_id = s.user_id
),
seq AS (
    SELECT *,
           -- LAG over the user's order stream = days since the previous order (NULL on first)
           day_num - LAG(day_num) OVER (PARTITION BY user_id ORDER BY order_date, order_seq_num) AS gap_days,
           MIN(day_num) OVER (PARTITION BY user_id) AS first_day,
           MIN(CASE WHEN order_seq_num = 3 THEN day_num END) OVER (PARTITION BY user_id) AS third_day
    FROM o
),
per_user AS (
    SELECT user_id,
           initial_category_width,
           MIN(order_date) AS first_order_date,   -- each user's first order date (cohort anchor)
           AVG(gap_days)   AS avg_days_between_orders,
           MAX(CASE WHEN day_num > third_day AND day_num <= third_day + 1  THEN 1 ELSE 0 END) AS d1,
           MAX(CASE WHEN day_num > third_day AND day_num <= third_day + 7  THEN 1 ELSE 0 END) AS d7,
           MAX(CASE WHEN day_num > third_day AND day_num <= third_day + 30 THEN 1 ELSE 0 END) AS d30
    FROM seq
    GROUP BY user_id, initial_category_width
)
SELECT initial_category_width,
       COUNT(DISTINCT user_id)                AS users,
       MIN(first_order_date)                  AS cohort_started,
       ROUND(100.0 * AVG(d1),  1)             AS d1_retention_pct,
       ROUND(100.0 * AVG(d7),  1)             AS d7_retention_pct,
       ROUND(100.0 * AVG(d30), 1)             AS d30_retention_pct,
       ROUND(AVG(avg_days_between_orders), 1) AS avg_days_between_orders
FROM per_user
GROUP BY initial_category_width;

-- QUERY 3 — 8-SEGMENT RFM LIFECYCLE MODEL. Explain it as: score every user on Recency, Frequency
-- and Monetary into NTILE(3) tertiles (1 = best), then the CASE maps scores to CRM actions.
WITH rfm AS (
    SELECT user_id,
           COUNT(DISTINCT order_id) AS frequency,      -- total orders
           SUM(order_value)         AS monetary,       -- total spend (INR)
           MAX(order_date)          AS last_order_date -- recency: NTILE only needs the ordering
    FROM orders
    GROUP BY user_id
),
scored AS (
    SELECT *,
           NTILE(3) OVER (ORDER BY last_order_date DESC) AS r_score, -- 1 = most recent
           NTILE(3) OVER (ORDER BY frequency DESC)       AS f_score, -- 1 = most frequent
           NTILE(3) OVER (ORDER BY monetary DESC)        AS m_score  -- 1 = biggest spender
    FROM rfm
)
SELECT user_id, frequency, monetary, last_order_date, r_score, f_score, m_score,
       CASE  -- ordered rules: each of the 27 score combos lands in exactly one segment
           WHEN r_score = 1 AND f_score = 1 THEN 'Champions'          -- recent + frequent
           WHEN r_score = 2 AND f_score = 1 THEN 'Loyalists'          -- frequent, cooling off
           WHEN r_score = 1 AND f_score = 2 THEN 'Promising'          -- recent, growing frequency
           WHEN r_score = 1                THEN 'New Trialists'       -- recent but infrequent
           WHEN r_score = 3 AND m_score = 1 THEN 'At-Risk High Value' -- lapsed big spenders
           WHEN r_score = 2 AND f_score = 2 THEN 'Need Attention'     -- middling on everything
           WHEN r_score = 2                THEN 'About to Sleep'      -- drifting away
           ELSE 'Hibernating'                                          -- lapsed, low value
       END AS segment
FROM scored;

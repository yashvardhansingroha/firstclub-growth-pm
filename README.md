# FirstClub Growth & Lifecycle CRM Case Study

Quick-commerce analytics for a premium groceries player in Bangalore & Hyderabad,
built on a synthetic FirstClub dataset (15,000 users, 100,000 sessions, 120,000 orders
across Fresh Produce, Dairy, Bakery, Eggs, Staples and Snacks). Fully deterministic
(seed 42): every number below is reproducible by re-running the generator.

## 1. Problem Statement

FirstClub burns contribution margin on blanket discounts even though its catalog of
artisanal bakery, A2 dairy and farm-fresh staples is the real differentiator buyers
can't get on Blinkit or Zepto. The data shows users stay (and reorder in ~3 days) only
once they build a 3+ category habit, yet most new users never widen past their first
category and quietly churn within weeks. Growth therefore has to come from category
cross-pollination and trust-led conversion (quality badges, free trials), not from
deepening the discount hole.

## 2. Campaign Hypothesis

If we nudge 1-category buyers toward a 3+ category basket using trust signals
(quality badges and a free artisanal trial pack) instead of flat discounts, we will
lift D30 retention and repeat conversion while *improving* net contribution margin per
order.

## 3. Key SQL Findings

- **Catalog-to-cart friction is the leak, and trust fixes it.** Overall drop-off is
  ~36% (36.2% measured) and tiered by category: Fresh Produce & Dairy drop 28% without
  the quality badge vs 18% with it, Bakery & Eggs 35% vs 20%, Staples/Snacks 41.5% vs
  ~17% — a 25 pp lift from a free trust signal (`queries.sql`, Query 1).
- **3+ categories by Order #3 is the habit threshold.** D30 retention jumps from
  19.3% (1-category buyers, 9.4 days between orders) to 57.9% (3+ category buyers,
  3.1 days between orders) — a 3x retention multiplier driven by basket width, not
  discount depth (Query 2). D7 sits at 37.1% vs 6.0%: habit formation is visible
  inside week one, not just at day 30.
- **An 8-segment RFM engine (Recency/Frequency/Monetary, NTILE(3) tertiles) ranks the
  base from Champions to Hibernating**, flagging e.g. 583 At-Risk High Value users
  (avg spend ~₹10.6k) for concierge winback while suppressing paid spend on 4,417
  Hibernating users (Query 3).
- **Offer A/B (Tab 4 of the dashboard):** arms are sized live from the mid-funnel RFM
  pool (3,714 Promising/Need-Attention/New-Trialist users → n = 1,200 per arm); a free
  ₹42-COGS trial pack beat a flat ₹125 discount by +14.8 pp D30 repeat conversion
  (31.2% vs 46.0%, Z = 7.5, p < 0.001) while saving ₹68/order in net contribution
  margin.

## 4. How to Run

```bash
pip install -r requirements.txt
python generate_data.py     # builds firstclub.db + users.csv, sessions.csv, orders.csv (seed 42)
streamlit run app.py        # 4-tab dashboard (auto-runs the generator if the DB is missing)
pytest -q                   # 12 tests: generator determinism, fix regressions, app smoke
```

Optional: run the analysis directly with `sqlite3 firstclub.db < queries.sql`
(all queries are PostgreSQL-compatible too).

## 5. Repo Layout

| File | Role |
|---|---|
| `generate_data.py` | Seeded synthetic-data generator → `firstclub.db` + 3 CSVs |
| `queries.sql` | 3 standalone analysis queries (funnel, retention, RFM) |
| `app.py` | 4-tab Streamlit dashboard; self-bootstraps its data |
| `tests/test_firstclub.py` | Determinism, D7/D30 split, badge contrast, app smoke tests |

Data disclosure: the dataset is synthetic, generated to carry realistic quick-commerce
dynamics; it is a portfolio demonstration, not real FirstClub telemetry.

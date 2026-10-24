"""Tests for the flat FirstClub growth case-study pipeline (generator, SQL, dashboard)."""

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "firstclub.db"
SEGMENTS = {"Champions", "Loyalists", "Promising", "New Trialists", "Need Attention",
            "About to Sleep", "At-Risk High Value", "Hibernating"}
LINE_CAPS = {"generate_data.py": 100, "app.py": 140, "queries.sql": 115, "README.md": 95}


@pytest.fixture(scope="session", autouse=True)
def database():
    """All tests share one deterministic DB (seed 42); build it if missing."""
    if not DB.exists():
        subprocess.run([sys.executable, "generate_data.py"], cwd=ROOT, check=True)
    with sqlite3.connect(DB) as con:
        yield con


def run_queries(con):
    qs = [q for q in (ROOT / "queries.sql").read_text().split(";") if q.strip()]
    return [pd.read_sql(q, con) for q in qs]


def test_repo_line_caps():
    for name, cap in LINE_CAPS.items():
        n = len((ROOT / name).read_text(encoding="utf-8").splitlines())
        assert n <= cap, f"{name} has {n} physical lines, cap is {cap}"


def test_generator_deterministic(tmp_path):
    runs = []
    for _ in range(2):
        subprocess.run([sys.executable, str(ROOT / "generate_data.py")], cwd=tmp_path, check=True)
        runs.append([(tmp_path / f).read_bytes()
                     for f in ("users.csv", "sessions.csv", "orders.csv")])
    assert runs[0] == runs[1]        # fixed seed -> byte-identical artifacts every run
    assert (tmp_path / "firstclub.db").exists()


def test_table_shapes_and_columns():
    users, sess, orders = (pd.read_csv(ROOT / f) for f in ("users.csv", "sessions.csv", "orders.csv"))
    assert (len(users), len(sess), len(orders)) == (15000, 100000, 120000)
    assert set(users) == {"user_id", "city", "signup_date", "initial_category_width"}
    assert set(sess) == {"session_id", "user_id", "category", "viewed_catalog",
                         "clicked_quality_badge", "added_to_cart", "completed_order"}
    assert set(orders) == {"order_id", "user_id", "order_date", "order_seq_num",
                           "categories_in_basket", "order_value", "offer_type"}
    assert set(orders.offer_type) == {"control", "flat_125_discount", "free_quality_trial"}
    assert orders.categories_in_basket.between(1, 4).all() and (orders.order_value > 0).all()


def test_order_stream_per_user(database):
    o = pd.read_sql("SELECT user_id, order_seq_num, order_date FROM orders", database,
                    parse_dates=["order_date"])
    contiguous = o.groupby("user_id").order_seq_num.apply(lambda s: s.tolist() == list(range(1, len(s) + 1)))
    assert contiguous.all()                      # every user: orders 1..n with no holes
    assert o.groupby("user_id").order_date.apply(lambda s: s.is_monotonic_increasing).all()


def test_order4_latency_split(database):
    """Fix 1: 3plus Order #4 returns split ~65% in 2-7d / ~35% in 8-22d."""
    o = pd.read_sql("SELECT user_id, order_seq_num, order_date FROM orders", database,
                    parse_dates=["order_date"])
    u = pd.read_sql("SELECT user_id, initial_category_width FROM users", database)
    piv = o.merge(u, on="user_id").pivot(index="user_id", columns="order_seq_num", values="order_date")
    gap4 = (piv[4] - piv[3]).dt.days.dropna()
    wide = u.set_index("user_id").initial_category_width.eq("3plus_categories")
    g = gap4[wide.reindex(gap4.index)]
    fast = g.le(7)
    assert 0.58 < fast.mean() < 0.72             # ~65% of returns land inside D7
    assert 3.5 < g[fast].mean() < 5.5            # D7-class gap ~ Uniform(2, 7)
    assert 12 < g[~fast].mean() < 18             # D30-class gap ~ Uniform(8, 22)


def test_query2_d7_separated_from_d30(database):
    """Fix 1 end-to-end: D7 ~38% strictly below D30 ~58.2%; cohort gaps 3.1d vs 9.4d."""
    cohorts = run_queries(database)[1].set_index("initial_category_width")
    one, plus = cohorts.loc["1_category"], cohorts.loc["3plus_categories"]
    assert 30 < plus.d7_retention_pct < 45 and 50 < plus.d30_retention_pct < 65
    assert plus.d7_retention_pct < plus.d30_retention_pct - 15   # the D7==D30 bug stays fixed
    assert 15 < one.d30_retention_pct < 25 and one.d7_retention_pct < 10
    assert 2.5 <= plus.avg_days_between_orders <= 3.7            # D7-class buyers ~3.1 days
    assert 8.5 <= one.avg_days_between_orders <= 10.5            # D30-class buyers ~9.4 days


def test_badge_contrast_by_category(database):
    """Fix 2: no-badge drop-off tiers 28/35/41.5% vs badge tiers 18/20/16.8%, overall ~36%."""
    f = pd.read_sql(
        """SELECT category, clicked_quality_badge AS b,
                  100.0 * AVG(1 - added_to_cart) AS dropoff
           FROM sessions GROUP BY category, clicked_quality_badge""", database)
    d = f.set_index(["category", "b"]).dropoff
    no_badge = {"Fresh Produce": (24, 32), "Dairy": (24, 32), "Bakery": (32, 40),
                "Eggs": (32, 40), "Staples": (38, 45), "Snacks": (38, 45)}
    with_badge = {"Fresh Produce": (13, 23), "Dairy": (13, 23), "Bakery": (13, 27),
                  "Eggs": (13, 27), "Staples": (11, 22), "Snacks": (11, 22)}
    for cat, (lo, hi) in no_badge.items():
        assert lo <= d[cat, 0] <= hi, (cat, "no badge", d[cat, 0])
    for cat, (lo, hi) in with_badge.items():
        assert lo <= d[cat, 1] <= hi, (cat, "badge", d[cat, 1])
    overall = 100 * (1 - pd.read_sql("SELECT AVG(added_to_cart) AS c FROM sessions",
                                     database).iloc[0].c)
    assert 33 < overall < 39


def test_queries_structure_and_coverage(database):
    funnel, cohorts, rfm = run_queries(database)
    assert len(funnel) == 12                     # 6 categories x 2 badge states
    assert {"sessions", "carts", "orders_done", "catalog_to_cart_dropoff_pct",
            "cart_to_order_dropoff_pct"} <= set(funnel.columns)
    assert set(cohorts.initial_category_width) == {"1_category", "3plus_categories"}
    assert set(rfm.segment) == SEGMENTS and rfm.user_id.is_unique and len(rfm) == 15000


def test_midfunnel_pool_sizes_ab_test(database):
    """Fix 3: Tab 4 sizes its arms from the RFM mid-funnel pool queried at runtime."""
    rfm = run_queries(database)[2]
    pool = int(rfm.segment.isin(["Promising", "New Trialists", "Need Attention"]).sum())
    assert pool >= 2400                          # pool must cover 2 arms x 1,200 users


def test_app_renders_all_metrics(database, monkeypatch):
    import streamlit.testing.v1 as stt
    monkeypatch.chdir(ROOT)
    at = stt.AppTest.from_file("app.py").run(timeout=300)
    assert not at.exception
    vals = [m.value for m in at.metric]
    n_sess = pd.read_sql("SELECT COUNT(*) AS n FROM sessions", database).iloc[0].n
    assert f"{int(n_sess):,}" in vals            # Total Sessions comes from the DB, not a literal
    assert len(vals) == 10                       # 3 funnel + 4 cohort + 3 A/B metrics


def test_app_self_bootstraps_in_empty_dir(tmp_path, monkeypatch):
    for f in ("app.py", "generate_data.py", "queries.sql"):
        shutil.copy(ROOT / f, tmp_path / f)
    monkeypatch.chdir(tmp_path)
    import streamlit.testing.v1 as stt
    at = stt.AppTest.from_file("app.py").run(timeout=300)
    assert not at.exception
    assert (tmp_path / "firstclub.db").exists() and (tmp_path / "orders.csv").exists()


def test_app_has_no_hardcoded_results():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    for lit in ("31.2", "46.0", "14.8", "36.2", "57.9", "19.3", "37.1", "20.1", "100,000"):
        assert lit not in src, f"hardcoded result {lit!r} leaked into app.py"

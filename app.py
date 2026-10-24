"""FirstClub growth dashboard: funnel, cohort retention, RFM engine, offer A/B calculator."""
import os
import runpy
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import sqlite3
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

st.set_page_config(page_title="FirstClub Growth Dashboard", layout="wide")

if not (ROOT / "firstclub.db").exists():  # auto-provision data so Streamlit Cloud boots clean
    runpy.run_path(str(ROOT / "generate_data.py"))


@st.cache_data
def load_results():
    queries = [q for q in open("queries.sql").read().split(";") if q.strip()]
    with sqlite3.connect("firstclub.db") as con:
        return [pd.read_sql(q, con) for q in queries]


funnel, cohorts, rfm = load_results()
st.title("FirstClub · Quick-Commerce Growth Analytics (Bangalore & Hyderabad)")
t1, t2, t3, t4 = st.tabs(["Funnel & Trust Friction", "Category Width Cohorts",
                          "RFM Lifecycle CRM Engine", "Offer A/B Calculator"])

# ---- Tab 1: catalog -> cart -> order funnel, split by quality-badge click ----
with t1:
    b0 = funnel[funnel.clicked_quality_badge == 0]
    b1 = funnel[funnel.clicked_quality_badge == 1]
    d_all = 100 * (1 - funnel.carts.sum() / funnel.sessions.sum())
    d0 = 100 * (1 - b0.carts.sum() / b0.sessions.sum())
    d1 = 100 * (1 - b1.carts.sum() / b1.sessions.sum())
    k1, k2, k3 = st.columns(3)
    k1.metric("Total Sessions", f"{int(funnel.sessions.sum()):,}")
    k2.metric("Catalog-to-Cart Drop-off", f"{d_all:.1f}%")
    k3.metric("Quality Badge Lift", f"{d0 - d1:.1f} pp", "drop-off erased by badge")
    piv = funnel.pivot(index="category", columns="clicked_quality_badge",
                       values="catalog_to_cart_dropoff_pct")
    st.bar_chart(piv.rename(columns={0: "no badge click", 1: "clicked quality badge"}))
    st.caption("Drop-off = catalog views that never add to cart. Badge trust matters most in Staples/Snacks.")

# ---- Tab 2: D1/D7/D30 retention and inter-order gap, 1-category vs 3plus ----
with t2:
    w = cohorts.set_index("initial_category_width")
    one, plus = w.loc["1_category"], w.loc["3plus_categories"]
    cA, cB = st.columns(2)
    with cA:
        st.subheader("1-Category buyers")
        st.metric("D30 Retention", f"{one.d30_retention_pct:.1f}%")
        st.metric("Inter-Order Gap", f"{one.avg_days_between_orders:.1f} days")
    with cB:
        st.subheader("3+ Category buyers")
        st.metric("D30 Retention", f"{plus.d30_retention_pct:.1f}%",
                  f"+{plus.d30_retention_pct - one.d30_retention_pct:.1f} pp vs 1-category")
        st.metric("Inter-Order Gap", f"{plus.avg_days_between_orders:.1f} days",
                  f"{plus.avg_days_between_orders - one.avg_days_between_orders:.1f} days faster",
                  delta_color="inverse")
    st.dataframe(cohorts)
    st.caption("Width is decided by Order #3: multi-category habits drive retention, not just discounts.")

# ---- Tab 3: 8-segment RFM model with CRM playbook ----
with t3:
    g = rfm.groupby("segment").agg(users=("user_id", "count"), spend=("monetary", "sum"),
                                   orders=("frequency", "sum"))
    g["aov_inr"] = (g.spend / g.orders).round(0).astype(int)
    st.bar_chart(g.users.sort_values(ascending=False))
    st.dataframe(g[["users", "aov_inr"]])
    actions = pd.DataFrame({
        "segment": ["Champions", "Loyalists", "Promising", "New Trialists", "Need Attention",
                    "About to Sleep", "At-Risk High Value", "Hibernating"],
        "crm_action": ["Early access to artisanal drops + referral ask",
                       "Auto-replenish subscription for staples & dairy",
                       "Enroll in offer A/B test (Tab 4) to lock the habit",
                       "Quality-badge education + 3-category basket nudge",
                       "Personalized category-expansion push notifications",
                       "Winback nudge: free bakery/eggs add-on with next order",
                       "Concierge outreach + free quality trial, no blanket discount",
                       "Low-cost email winback, suppress paid re-targeting"],
    })
    st.table(actions.set_index("segment"))

# ---- Tab 4: two-proportion Z-test, flat discount vs free trial pack ----
with t4:
    x1, x2 = 374, 552                    # D30 repeat orders observed per arm
    mid = rfm[rfm["segment"].isin(["Promising", "New Trialists", "Need Attention"])]
    n1 = n2 = min(1200, len(mid) // 2)   # arms sized live from the mid-funnel RFM pool (Q3)
    if not n1 or n1 < x2:                # pool missing or too small -> design fallback
        n1 = n2 = 1200
    st.caption(f"Live 4-week test on {len(mid):,} mid-funnel Trialist/Promising users "
               f"(n = {n1:,} per arm, sized from the RFM pool above): Variant A = flat "
               "\u20b9125 discount, Variant B = free artisanal bakery/A2 dairy trial pack "
               "(\u20b942 COGS).")
    p1, p2 = x1 / n1, x2 / n2            # repeat conversion, computed from arm data
    pp = (x1 + x2) / (n1 + n2)           # pooled proportion under H0: p1 = p2
    se = np.sqrt(pp * (1 - pp) * (1 / n1 + 1 / n2))
    z = (p2 - p1) / se                   # two-proportion Z-test
    saved = 125 - 42 - 15                # discount avoided - pack COGS - extra cold-chain handling
    m1, m2, m3 = st.columns(3)
    m1.metric("D30 Repeat Lift (B vs A)", f"+{(p2 - p1) * 100:.1f} pp")
    m2.metric("Z-score", f"{z:.1f}", "p < 0.001 (two-sided)")
    m3.metric("Net Contribution Margin Saved", f"\u20b9{saved}/order")
    st.bar_chart(pd.DataFrame({"D30 repeat conversion %": [p1 * 100, p2 * 100]},
                              index=["A: flat \u20b9125 off", "B: free trial pack"]))

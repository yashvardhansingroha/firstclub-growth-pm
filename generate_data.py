"""FirstClub synthetic quick-commerce data: builds firstclub.db + 3 CSVs with built-in patterns."""
import numpy as np
import pandas as pd
import sqlite3

rng = np.random.default_rng(42)
CATS = ["Fresh Produce", "Dairy", "Bakery", "Eggs", "Staples", "Snacks"]

# ---------- USERS: 15,000 signups Jan-Apr 2025; 45% start with 3+ categories ----------
users = pd.DataFrame({
    "user_id": np.arange(1, 15001),
    "city": rng.choice(["Bangalore", "Hyderabad"], 15000, p=[0.60, 0.40]),
    "signup_date": pd.Timestamp("2025-01-01") + pd.to_timedelta(rng.integers(0, 120, 15000), unit="D"),
    "initial_category_width": rng.choice(["1_category", "3plus_categories"], 15000, p=[0.55, 0.45]),
})

# ---------- ORDERS: everyone buys 3x, then retained users keep buying ----------
# D30 retention after Order #3 is hardcoded: 58.2% for 3plus vs 19.4% for 1_category.
wide_u = users["initial_category_width"].eq("3plus_categories").to_numpy()
retained = rng.random(15000) < np.where(wide_u, 0.582, 0.194)
extra = np.where(retained, rng.poisson(np.where(wide_u, 15.5, 8.8)), 0)  # repeat orders
diff = 75000 - extra.sum()  # pad/trim so total = 45,000 base + 75,000 repeat = 120,000
if diff:
    picks = np.flatnonzero(retained)[rng.integers(0, retained.sum(), abs(diff))]
    np.add.at(extra, picks, np.sign(diff))  # add.at accumulates repeated picks
orders = pd.DataFrame({"user_id": np.repeat(users["user_id"].to_numpy(), 3 + extra)})
orders["order_seq_num"] = orders.groupby("user_id").cumcount() + 1
orders = orders.merge(users[["user_id", "signup_date", "initial_category_width"]], on="user_id")
wide = orders["initial_category_width"].eq("3plus_categories")
seq = orders["order_seq_num"]

# Cadence: 3plus reorder every ~3.1 days, 1_category every ~9.4 days. After Order #3, 65% of
# retained 3plus users return in 2-7 days and 35% in 8-22 days (so D7 ~38% < D30 ~58.2%);
# seq>=5 repeats run ~2.75 days so the cohort's overall mean gap still lands at ~3.1 days.
mu = np.where(wide, np.where(seq.ge(5), 2.75, 3.1), 9.4)
gap = np.where(seq.eq(1), rng.uniform(1, 4, len(orders)),
               rng.normal(mu, np.where(wide, 1.2, 4.0))).clip(1)
slow = seq.eq(4) & wide & (rng.random(len(orders)) < 0.35)  # 35% take 8-22 days
gap = np.where(slow, rng.uniform(8, 22, len(orders)),
               np.where(seq.eq(4) & wide, rng.uniform(2, 7, len(orders)), gap))
orders["order_date"] = orders["signup_date"] + pd.to_timedelta(
    orders.assign(g=gap.round()).groupby("user_id")["g"].cumsum().astype(int), unit="D")

# Baskets follow width: 3plus buy 3-4 categories per order, 1_category stays at 1-2.
orders["categories_in_basket"] = np.where(wide, 3 + (rng.random(len(orders)) < 0.55),
                                          1 + (rng.random(len(orders)) < 0.45)).astype(int)
orders["order_value"] = (150 + 140 * orders["categories_in_basket"]
                         + rng.normal(0, 60, len(orders))).clip(80).round().astype(int)
orders["offer_type"] = rng.choice(["control", "flat_125_discount", "free_quality_trial"],
                                  len(orders), p=[0.60, 0.25, 0.15])
orders = orders.sort_values("order_date").reset_index(drop=True)
orders["order_id"] = np.arange(1, len(orders) + 1)

# ---------- SESSIONS: 100,000 catalog views, staples/snacks-heavy replenishment traffic ----------
# No-badge cart tiers: FP/Dairy .72, Bakery/Eggs .64, Staples/Snacks .585 (= 41.5% drop-off);
# badge lift +.10/+.16/+.247 (S/S with badge = .832 = 16.8% drop-off). Overall ~36%.
badge_p = {"Fresh Produce": .07, "Dairy": .07, "Bakery": .08, "Eggs": .08, "Staples": .10, "Snacks": .10}
cart_p = {"Fresh Produce": .72, "Dairy": .72, "Bakery": .64, "Eggs": .64, "Staples": .585, "Snacks": .585}
lift_p = {"Fresh Produce": .10, "Dairy": .10, "Bakery": .16, "Eggs": .16, "Staples": .247, "Snacks": .247}
sess = pd.DataFrame({
    "session_id": np.arange(1, 100001),
    "user_id": rng.choice(users["user_id"], 100000, p=(3 + extra) / (3 + extra).sum()),
    "category": rng.choice(CATS, 100000, p=[.09, .09, .09, .09, .32, .32]),
})
sess["viewed_catalog"] = 1
sess["clicked_quality_badge"] = (rng.random(100000) < sess["category"].map(badge_p)).astype(int)
sess["added_to_cart"] = (rng.random(100000) < sess["category"].map(cart_p)
                         + sess["category"].map(lift_p) * sess["clicked_quality_badge"]).astype(int)
sess["completed_order"] = ((sess["added_to_cart"] == 1) & (rng.random(100000) < 0.62)).astype(int)

# ---------- sanity checks for the built-in patterns ----------
d34 = (orders[orders["order_seq_num"].eq(4)].set_index("user_id")["order_date"]
       - orders[orders["order_seq_num"].eq(3)].set_index("user_id")["order_date"]).dt.days
ss = sess[sess["category"].isin(["Staples", "Snacks"])]
print("rows:", len(users), len(sess), len(orders), "| overall cart drop-off:", round(1 - sess["added_to_cart"].mean(), 3))
print("staples/snacks drop-off by badge:", ss.groupby("clicked_quality_badge")["added_to_cart"].agg(lambda s: round(1 - s.mean(), 3)).to_dict())
print("D7/D30 retention by width:", users.set_index("user_id").join(d34.rename("g")).groupby("initial_category_width")["g"]
      .agg(d7=lambda s: round((s <= 7).mean(), 3), d30=lambda s: round((s <= 30).mean(), 3)).to_dict("index"))
print("mean days between orders:", orders.assign(gd=orders.groupby("user_id")["order_date"].diff().dt.days).groupby("initial_category_width")["gd"].mean().round(1).to_dict())

# ---------- write CSVs and the SQLite database ----------
orders = orders[["order_id", "user_id", "order_date", "order_seq_num",
                 "categories_in_basket", "order_value", "offer_type"]]
users.to_csv("users.csv", index=False)
sess.to_csv("sessions.csv", index=False)
orders.to_csv("orders.csv", index=False)
with sqlite3.connect("firstclub.db") as con:
    users.to_sql("users", con, if_exists="replace", index=False)
    sess.to_sql("sessions", con, if_exists="replace", index=False)
    orders.to_sql("orders", con, if_exists="replace", index=False)

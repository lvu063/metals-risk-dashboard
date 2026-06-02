"""
generate_mock_data.py
---------------------
Generates synthetic metals trading data for the Metals Risk Dashboard project.
Produces: trades, positions, market prices, and PnL records as CSV files.

Usage:
    python generate_mock_data.py
    python generate_mock_data.py --rows 500 --seed 99
"""

import argparse
import random
import math
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

METALS = {
    "Gold":     {"symbol": "XAU", "unit": "troy oz", "base_price": 2350.00, "vol": 0.012},
    "Silver":   {"symbol": "XAG", "unit": "troy oz", "base_price":  28.50,  "vol": 0.018},
    "Platinum": {"symbol": "XPT", "unit": "troy oz", "base_price": 980.00,  "vol": 0.015},
    "Palladium":{"symbol": "XPD", "unit": "troy oz", "base_price":1050.00,  "vol": 0.020},
    "Copper":   {"symbol": "HG",  "unit": "lbs",     "base_price":   4.15,  "vol": 0.022},
    "Aluminium":{"symbol": "AL",  "unit": "MT",      "base_price":2450.00,  "vol": 0.014},
    "Zinc":     {"symbol": "ZN",  "unit": "MT",      "base_price":2800.00,  "vol": 0.019},
    "Nickel":   {"symbol": "NI",  "unit": "MT",      "base_price":17500.00, "vol": 0.025},
}

COUNTERPARTIES = [
    "Scotiabank", "HSBC Metals", "Standard Chartered", "Citibank NA",
    "JPMorgan Commodities", "UBS AG", "Deutsche Bank", "TD Securities",
    "Barclays Metals", "Goldman Sachs", "Morgan Stanley", "BNP Paribas",
]

TRADERS = [
    "J. Kowalski", "M. Patel", "S. Okonkwo", "L. Chen",
    "A. Dubois",   "R. Nakamura", "P. O'Brien", "T. Vasquez",
]

DESKS = ["Precious Metals", "Base Metals"]

BOOKS = {
    "Precious Metals": ["PM-PROP-01", "PM-HEDGE-01", "PM-CLIENT-01"],
    "Base Metals":     ["BM-PROP-01", "BM-HEDGE-01", "BM-CLIENT-01"],
}

PRECIOUS = {"Gold", "Silver", "Platinum", "Palladium"}

TRADE_TYPES = ["Spot", "Forward", "Option", "Swap"]
BUY_SELL    = ["Buy", "Sell"]
CURRENCIES  = ["USD", "CAD", "GBP", "EUR"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def business_days(start: date, end: date):
    """Return list of weekdays between start and end inclusive."""
    days, current = [], start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def gbm_path(S0: float, vol: float, n: int, seed: int):
    """Geometric Brownian Motion price path (daily steps, 0% drift)."""
    rng = random.Random(seed)
    prices, price = [S0], S0
    for _ in range(n - 1):
        z = rng.gauss(0, 1)
        price *= math.exp(-0.5 * vol ** 2 + vol * z)
        prices.append(round(price, 4))
    return prices


def rand_qty(metal: str, rng: random.Random) -> float:
    """Return a realistic trade quantity for the metal."""
    if metal in PRECIOUS:
        return round(rng.randint(1, 500) * 100, 0)    # 100–50,000 oz
    else:
        return round(rng.randint(1, 200) * 25, 0)     # 25–5,000 MT / lbs lots


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

def generate_price_history(start: date, end: date, seed: int = 42) -> list[dict]:
    """Daily spot prices for every metal over the date range."""
    days = business_days(start, end)
    rows = []
    for metal, meta in METALS.items():
        prices = gbm_path(meta["base_price"], meta["vol"], len(days), seed + hash(metal) % 1000)
        for d, p in zip(days, prices):
            rows.append({
                "price_date":   d.isoformat(),
                "metal":        metal,
                "symbol":       meta["symbol"],
                "spot_price":   p,
                "currency":     "USD",
                "unit":         meta["unit"],
                "source":       "LME" if metal not in PRECIOUS else "LBMA",
            })
    return rows


def generate_trades(n: int, start: date, end: date, seed: int = 42) -> list[dict]:
    """Synthetic trade blotter."""
    rng = random.Random(seed)
    days = business_days(start, end)
    rows = []
    for i in range(1, n + 1):
        metal      = rng.choice(list(METALS.keys()))
        desk       = "Precious Metals" if metal in PRECIOUS else "Base Metals"
        book       = rng.choice(BOOKS[desk])
        trade_date = rng.choice(days)
        settle_lag = rng.choice([2, 2, 2, 5, 30, 90])          # spot = T+2
        settle     = trade_date + timedelta(days=settle_lag)
        meta       = METALS[metal]
        spot       = meta["base_price"] * rng.uniform(0.95, 1.05)
        qty        = rand_qty(metal, rng)
        buy_sell   = rng.choice(BUY_SELL)
        trade_type = rng.choices(TRADE_TYPES, weights=[50, 30, 10, 10])[0]
        premium    = round(spot * rng.uniform(-0.002, 0.005), 4)  # bid/ask spread
        price      = round(spot + premium, 4)
        notional   = round(price * qty, 2)
        rows.append({
            "trade_id":        f"TRD-{i:06d}",
            "trade_date":      trade_date.isoformat(),
            "settlement_date": settle.isoformat(),
            "metal":           metal,
            "symbol":          meta["symbol"],
            "desk":            desk,
            "book":            book,
            "trader":          rng.choice(TRADERS),
            "counterparty":    rng.choice(COUNTERPARTIES),
            "buy_sell":        buy_sell,
            "trade_type":      trade_type,
            "quantity":        qty,
            "unit":            meta["unit"],
            "trade_price":     price,
            "spot_at_trade":   round(spot, 4),
            "currency":        "USD",
            "notional_usd":    notional,
            "status":          rng.choices(
                                   ["Confirmed", "Pending", "Settled", "Cancelled"],
                                   weights=[60, 15, 20, 5])[0],
        })
    return rows


def generate_positions(trades: list[dict], as_of: date) -> list[dict]:
    """
    Net position per (book, metal) based on confirmed/settled trades
    on or before as_of date.
    """
    net: dict[tuple, dict] = {}
    for t in trades:
        if t["status"] == "Cancelled":
            continue
        if date.fromisoformat(t["trade_date"]) > as_of:
            continue
        key = (t["book"], t["metal"], t["symbol"], t["desk"], t["unit"])
        if key not in net:
            net[key] = {"quantity": 0.0, "cost_basis_usd": 0.0, "trade_count": 0}
        sign = 1 if t["buy_sell"] == "Buy" else -1
        net[key]["quantity"]       += sign * t["quantity"]
        net[key]["cost_basis_usd"] += sign * t["notional_usd"]
        net[key]["trade_count"]    += 1

    rows = []
    for (book, metal, symbol, desk, unit), v in net.items():
        qty = round(v["quantity"], 4)
        cost = round(v["cost_basis_usd"], 2)
        avg_cost = round(cost / qty, 4) if qty != 0 else 0.0
        rows.append({
            "as_of_date":      as_of.isoformat(),
            "book":            book,
            "desk":            desk,
            "metal":           metal,
            "symbol":          symbol,
            "net_quantity":    qty,
            "unit":            unit,
            "avg_cost_usd":    avg_cost,
            "total_cost_usd":  cost,
            "trade_count":     v["trade_count"],
            "long_short":      "Long" if qty > 0 else ("Short" if qty < 0 else "Flat"),
        })
    return rows


def generate_pnl(positions: list[dict], prices: list[dict], as_of: date) -> list[dict]:
    """Daily MTM PnL for each position."""
    price_map = {
        (r["price_date"], r["metal"]): r["spot_price"]
        for r in prices
        if r["price_date"] == as_of.isoformat()
    }
    rows = []
    for pos in positions:
        spot = price_map.get((as_of.isoformat(), pos["metal"]))
        if spot is None or pos["net_quantity"] == 0:
            continue
        mtm_value   = round(pos["net_quantity"] * spot, 2)
        unrealised  = round(mtm_value - pos["total_cost_usd"], 2)
        pnl_pct     = round(unrealised / abs(pos["total_cost_usd"]) * 100, 4) \
                      if pos["total_cost_usd"] != 0 else 0.0
        rows.append({
            "pnl_date":        as_of.isoformat(),
            "book":            pos["book"],
            "desk":            pos["desk"],
            "metal":           pos["metal"],
            "symbol":          pos["symbol"],
            "net_quantity":    pos["net_quantity"],
            "unit":            pos["unit"],
            "spot_price_usd":  spot,
            "mtm_value_usd":   mtm_value,
            "cost_basis_usd":  pos["total_cost_usd"],
            "unrealised_pnl":  unrealised,
            "pnl_pct":         pnl_pct,
            "long_short":      pos["long_short"],
        })
    return rows


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def write_csv(rows: list[dict], path: Path):
    if not rows:
        print(f"  [skip] no rows for {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        f.write(",".join(headers) + "\n")
        for row in rows:
            f.write(",".join(str(row[h]) for h in headers) + "\n")
    print(f"  [ok]   {path}  ({len(rows):,} rows)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate mock metals trading data.")
    parser.add_argument("--rows",  type=int, default=300,  help="Number of trades (default 300)")
    parser.add_argument("--seed",  type=int, default=42,   help="Random seed (default 42)")
    parser.add_argument("--start", type=str, default="2024-01-02", help="Start date YYYY-MM-DD")
    parser.add_argument("--end",   type=str, default="2024-12-31", help="End date YYYY-MM-DD")
    parser.add_argument("--out",   type=str, default="data",        help="Output directory")
    args = parser.parse_args()

    start  = date.fromisoformat(args.start)
    end    = date.fromisoformat(args.end)
    as_of  = end
    outdir = Path(args.out)

    print(f"\nGenerating metals trading data  |  trades={args.rows}  seed={args.seed}")
    print(f"Date range: {start} → {end}\n")

    prices    = generate_price_history(start, end, args.seed)
    trades    = generate_trades(args.rows, start, end, args.seed)
    positions = generate_positions(trades, as_of)
    pnl       = generate_pnl(positions, prices, as_of)

    write_csv(prices,    outdir / "price_history.csv")
    write_csv(trades,    outdir / "trades.csv")
    write_csv(positions, outdir / "positions.csv")
    write_csv(pnl,       outdir / "pnl_summary.csv")

    print(f"\nDone. {len(trades)} trades → {len(positions)} net positions → {len(pnl)} PnL records.")


if __name__ == "__main__":
    main()

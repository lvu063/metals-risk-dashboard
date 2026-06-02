"""
analysis.py
-----------
Metals Risk Dashboard — Data Analysis Module

Demonstrates OOP design with pandas/numpy for data handling.
Encapsulates all analytical operations as a reusable class hierarchy:

    DataLoader          — loads and validates CSV data into DataFrames
    MetalsAnalyser      — core analytics: PnL, exposure, volatility
    RiskReporter        — generates formatted summary reports
    MetalsDashboard     — facade that composes all three (main entry point)

Usage:
    python python/analysis.py
    python python/analysis.py --data-dir data --report all
    python python/analysis.py --report pnl
    python python/analysis.py --report risk
    python python/analysis.py --report vol
    python python/analysis.py --export          # saves reports to CSV
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
log = logging.getLogger("analysis")


# =============================================================================
# Data classes — typed containers for analysis results
# =============================================================================

@dataclass
class PnLSummary:
    """Aggregated PnL result for a desk or metal."""
    label:          str
    total_mtm:      float
    total_cost:     float
    unrealised_pnl: float
    pnl_pct:        float
    position_count: int
    long_count:     int
    short_count:    int

    def __repr__(self) -> str:
        direction = "▲" if self.unrealised_pnl >= 0 else "▼"
        return (
            f"PnLSummary({self.label!r}  "
            f"PnL={direction}${abs(self.unrealised_pnl):,.0f}  "
            f"({self.pnl_pct:+.2f}%)  "
            f"positions={self.position_count})"
        )


@dataclass
class VolatilityResult:
    """Rolling volatility statistics for one metal."""
    symbol:        str
    metal:         str
    annualised_vol: float          # % annualised
    rolling_30d:   pd.Series       # daily vol series
    high_52w:      float
    low_52w:       float
    price_range_pct: float         # (high - low) / low * 100

    def __repr__(self) -> str:
        return (
            f"VolatilityResult({self.symbol}  "
            f"vol={self.annualised_vol:.1f}%ann  "
            f"52w_range={self.price_range_pct:.1f}%)"
        )


@dataclass
class ExposureSnapshot:
    """Gross/net exposure for one metal."""
    metal:          str
    symbol:         str
    gross_long:     float
    gross_short:    float
    net_exposure:   float
    trade_count:    int
    concentration:  float          # as fraction of portfolio total

    def __repr__(self) -> str:
        direction = "Long" if self.net_exposure > 0 else "Short"
        return (
            f"ExposureSnapshot({self.symbol}  "
            f"net=${abs(self.net_exposure):,.0f} {direction}  "
            f"conc={self.concentration:.1%})"
        )


# =============================================================================
# DataLoader — Extract & validate CSVs into typed DataFrames
# =============================================================================

class DataLoader:
    """
    Loads CSV files from a data directory into validated pandas DataFrames.

    Responsibilities:
      - File existence checks with clear error messages
      - Column presence validation
      - Type casting (dates, numerics)
      - Basic null checks with warnings
    """

    REQUIRED_COLUMNS: dict[str, list[str]] = {
        "trades": [
            "trade_id","trade_date","metal","symbol","desk","book",
            "buy_sell","quantity","trade_price","notional_usd","status"
        ],
        "price_history": ["price_date","metal","symbol","spot_price"],
        "positions":     ["as_of_date","book","metal","symbol","net_quantity","long_short"],
        "pnl":           ["pnl_date","book","metal","symbol","unrealised_pnl","mtm_value_usd","cost_basis_usd"],
    }

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self._log     = logging.getLogger("analysis.loader")
        self._cache: dict[str, pd.DataFrame] = {}

    def __repr__(self) -> str:
        loaded = list(self._cache.keys())
        return f"DataLoader(data_dir={self.data_dir!r}, loaded={loaded})"

    def _load(self, filename: str, dataset_key: str) -> pd.DataFrame:
        """Internal: load one CSV, validate columns, cache result."""
        if dataset_key in self._cache:
            return self._cache[dataset_key]

        path = self.data_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Data file not found: {path}")

        df = pd.read_csv(path, low_memory=False)
        self._log.info(f"Loaded {filename}: {len(df):,} rows × {len(df.columns)} cols")

        # Column validation
        required = self.REQUIRED_COLUMNS.get(dataset_key, [])
        missing  = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"{filename} missing required columns: {missing}")

        # Null warnings
        null_counts = df[required].isnull().sum()
        for col, count in null_counts[null_counts > 0].items():
            self._log.warning(f"  {filename}: {count} nulls in '{col}'")

        self._cache[dataset_key] = df
        return df

    # ------------------------------------------------------------------
    # Public loaders — each applies domain-specific type casting
    # ------------------------------------------------------------------

    def trades(self) -> pd.DataFrame:
        df = self._load("trades.csv", "trades").copy()
        df["trade_date"]      = pd.to_datetime(df["trade_date"],      errors="coerce")
        df["settlement_date"] = pd.to_datetime(df["settlement_date"], errors="coerce")
        df["quantity"]        = pd.to_numeric(df["quantity"],     errors="coerce")
        df["trade_price"]     = pd.to_numeric(df["trade_price"],  errors="coerce")
        df["notional_usd"]    = pd.to_numeric(df["notional_usd"], errors="coerce")
        return df

    def price_history(self) -> pd.DataFrame:
        df = self._load("price_history.csv", "price_history").copy()
        df["price_date"] = pd.to_datetime(df["price_date"], errors="coerce")
        df["spot_price"] = pd.to_numeric(df["spot_price"],  errors="coerce")
        return df.sort_values(["symbol", "price_date"])

    def positions(self) -> pd.DataFrame:
        df = self._load("positions.csv", "positions").copy()
        df["as_of_date"]    = pd.to_datetime(df["as_of_date"],    errors="coerce")
        df["net_quantity"]  = pd.to_numeric(df["net_quantity"],   errors="coerce")
        df["total_cost_usd"]= pd.to_numeric(df["total_cost_usd"], errors="coerce")
        return df

    def pnl(self) -> pd.DataFrame:
        # pnl_summary.csv maps to the pnl dataset
        path_options = ["pnl_summary.csv", "pnl_daily.csv"]
        filename = next(
            (f for f in path_options if (self.data_dir / f).exists()),
            "pnl_summary.csv"
        )
        df = self._load(filename, "pnl").copy()
        df["pnl_date"]       = pd.to_datetime(df["pnl_date"],       errors="coerce")
        df["unrealised_pnl"] = pd.to_numeric(df["unrealised_pnl"],  errors="coerce")
        df["mtm_value_usd"]  = pd.to_numeric(df["mtm_value_usd"],   errors="coerce")
        df["cost_basis_usd"] = pd.to_numeric(df["cost_basis_usd"],  errors="coerce")
        df["spot_price_usd"] = pd.to_numeric(df.get("spot_price_usd", pd.Series(dtype=float)), errors="coerce")
        return df

    def all(self) -> dict[str, pd.DataFrame]:
        """Load all datasets at once. Returns dict keyed by dataset name."""
        return {
            "trades":        self.trades(),
            "price_history": self.price_history(),
            "positions":     self.positions(),
            "pnl":           self.pnl(),
        }


# =============================================================================
# MetalsAnalyser — Core analytics engine
# =============================================================================

class MetalsAnalyser:
    """
    Core analytical engine for metals trading data.

    Takes loaded DataFrames and produces:
      - PnL summaries (by desk, by metal)
      - Exposure snapshots (gross/net)
      - Volatility calculations (log returns, rolling vol, annualised)
      - Correlation matrix across metals
      - Trade activity statistics

    All methods return pandas DataFrames or typed dataclasses —
    never mutates input data.
    """

    TRADING_DAYS_PER_YEAR = 252

    def __init__(self, loader: DataLoader):
        self._loader = loader
        self._log    = logging.getLogger("analysis.analyser")
        self._data   = loader.all()

    def __repr__(self) -> str:
        shapes = {k: v.shape for k, v in self._data.items()}
        return f"MetalsAnalyser(datasets={shapes})"

    # ------------------------------------------------------------------
    # PnL Analysis
    # ------------------------------------------------------------------

    def pnl_by_desk(self) -> list[PnLSummary]:
        """Aggregate unrealised PnL by trading desk."""
        df = self._data["pnl"]
        results = []

        for desk, group in df.groupby("desk"):
            results.append(PnLSummary(
                label          = desk,
                total_mtm      = group["mtm_value_usd"].sum(),
                total_cost     = group["cost_basis_usd"].sum(),
                unrealised_pnl = group["unrealised_pnl"].sum(),
                pnl_pct        = (
                    group["unrealised_pnl"].sum() /
                    abs(group["cost_basis_usd"].sum()) * 100
                    if group["cost_basis_usd"].sum() != 0 else 0.0
                ),
                position_count = len(group),
                long_count     = (group["long_short"] == "Long").sum(),
                short_count    = (group["long_short"] == "Short").sum(),
            ))

        return sorted(results, key=lambda x: abs(x.unrealised_pnl), reverse=True)

    def pnl_by_metal(self) -> pd.DataFrame:
        """
        PnL contribution breakdown per metal.
        Returns DataFrame sorted by absolute PnL descending.
        """
        df = self._data["pnl"]

        summary = (
            df.groupby(["metal", "symbol"])
            .agg(
                total_mtm      = ("mtm_value_usd",  "sum"),
                total_cost     = ("cost_basis_usd", "sum"),
                unrealised_pnl = ("unrealised_pnl", "sum"),
                position_count = ("symbol",         "count"),
            )
            .reset_index()
        )

        summary["pnl_pct"] = np.where(
            summary["total_cost"] != 0,
            summary["unrealised_pnl"] / summary["total_cost"].abs() * 100,
            0.0
        )
        summary["pnl_direction"] = np.where(
            summary["unrealised_pnl"] >= 0, "Gain", "Loss"
        )
        summary["abs_pnl"] = summary["unrealised_pnl"].abs()

        return (
            summary
            .sort_values("abs_pnl", ascending=False)
            .drop(columns="abs_pnl")
            .round(2)
        )

    def win_loss_ratio(self) -> dict[str, float]:
        """Fraction of positions in gain vs loss."""
        df = self._data["pnl"]
        winners = (df["unrealised_pnl"] > 0).sum()
        losers  = (df["unrealised_pnl"] < 0).sum()
        total   = len(df)
        return {
            "winners":       int(winners),
            "losers":        int(losers),
            "win_rate":      round(winners / total * 100, 2) if total else 0.0,
            "avg_win_usd":   round(df[df["unrealised_pnl"] > 0]["unrealised_pnl"].mean(), 2),
            "avg_loss_usd":  round(df[df["unrealised_pnl"] < 0]["unrealised_pnl"].mean(), 2),
        }

    # ------------------------------------------------------------------
    # Exposure Analysis
    # ------------------------------------------------------------------

    def exposure_by_metal(self) -> list[ExposureSnapshot]:
        """
        Gross long, gross short, net exposure per metal.
        Excludes cancelled trades.
        """
        trades = self._data["trades"]
        active = trades[trades["status"] != "Cancelled"].copy()

        total_notional = active["notional_usd"].sum()

        snapshots = []
        for (metal, symbol), grp in active.groupby(["metal", "symbol"]):
            long_mask  = grp["buy_sell"] == "Buy"
            short_mask = grp["buy_sell"] == "Sell"

            gross_long  = grp.loc[long_mask,  "notional_usd"].sum()
            gross_short = grp.loc[short_mask, "notional_usd"].sum()
            net         = gross_long - gross_short
            conc        = (gross_long + gross_short) / total_notional if total_notional else 0

            snapshots.append(ExposureSnapshot(
                metal         = metal,
                symbol        = symbol,
                gross_long    = round(gross_long,  2),
                gross_short   = round(gross_short, 2),
                net_exposure  = round(net,  2),
                trade_count   = len(grp),
                concentration = round(conc, 4),
            ))

        return sorted(snapshots, key=lambda x: abs(x.net_exposure), reverse=True)

    def concentration_flags(self, threshold: float = 0.40) -> pd.DataFrame:
        """
        Flag metals where concentration exceeds threshold.
        Uses pandas cut() to bin into risk tiers.
        """
        exposures = self.exposure_by_metal()
        df = pd.DataFrame([
            {
                "metal":        e.metal,
                "symbol":       e.symbol,
                "gross_long":   e.gross_long,
                "gross_short":  e.gross_short,
                "net_exposure": e.net_exposure,
                "concentration":e.concentration,
            }
            for e in exposures
        ])

        bins   = [0, 0.10, 0.25, 0.40, 1.0]
        labels = ["Normal", "Elevated", "Medium", "HIGH"]
        df["risk_tier"] = pd.cut(
            df["concentration"], bins=bins, labels=labels, right=True
        )
        df["breach"] = df["concentration"] > threshold
        return df.sort_values("concentration", ascending=False)

    # ------------------------------------------------------------------
    # Volatility Analysis
    # ------------------------------------------------------------------

    def log_returns(self) -> pd.DataFrame:
        """
        Compute daily log returns for each metal.
        log_return = ln(P_t / P_{t-1})
        """
        prices = self._data["price_history"].copy()

        prices["log_return"] = (
            prices
            .groupby("symbol")["spot_price"]
            .transform(lambda s: np.log(s / s.shift(1)))
        )
        return prices.dropna(subset=["log_return"])

    def rolling_volatility(self, window: int = 30) -> pd.DataFrame:
        """
        Rolling annualised volatility for each metal.
        vol = std(log_returns, window) * sqrt(252) * 100
        """
        returns = self.log_returns()

        vol_df = (
            returns
            .groupby("symbol")["log_return"]
            .rolling(window=window, min_periods=max(5, window // 2))
            .std()
            .reset_index()
            .rename(columns={"log_return": "rolling_std"})
        )
        vol_df["annualised_vol_pct"] = (
            vol_df["rolling_std"] * np.sqrt(self.TRADING_DAYS_PER_YEAR) * 100
        ).round(4)

        # Merge back price dates
        vol_df = vol_df.merge(
            returns[["symbol", "price_date"]].reset_index(drop=True),
            left_index=True,
            right_index=True,
            suffixes=("","_r")
        )
        if "symbol_r" in vol_df.columns:
            vol_df = vol_df.drop(columns=["symbol_r"])

        return vol_df[["symbol","price_date","annualised_vol_pct"]].dropna()

    def volatility_summary(self) -> list[VolatilityResult]:
        """
        Per-metal volatility summary with 52-week high/low and current annualised vol.
        """
        prices  = self._data["price_history"]
        vol_df  = self.rolling_volatility()
        results = []

        for symbol, price_grp in prices.groupby("symbol"):
            metal_name = price_grp["metal"].iloc[0]

            # Current vol (latest value)
            sym_vol = vol_df[vol_df["symbol"] == symbol]
            current_vol = (
                sym_vol["annualised_vol_pct"].iloc[-1]
                if not sym_vol.empty else np.nan
            )

            high_52w = price_grp["spot_price"].max()
            low_52w  = price_grp["spot_price"].min()
            price_range_pct = (
                (high_52w - low_52w) / low_52w * 100
                if low_52w > 0 else 0.0
            )

            results.append(VolatilityResult(
                symbol          = symbol,
                metal           = metal_name,
                annualised_vol  = round(current_vol, 2) if not np.isnan(current_vol) else 0.0,
                rolling_30d     = sym_vol.set_index("price_date")["annualised_vol_pct"],
                high_52w        = round(high_52w, 4),
                low_52w         = round(low_52w,  4),
                price_range_pct = round(price_range_pct, 2),
            ))

        return sorted(results, key=lambda x: x.annualised_vol, reverse=True)

    def correlation_matrix(self) -> pd.DataFrame:
        """
        Pearson correlation of daily log returns across all metals.
        Useful for portfolio diversification analysis.
        """
        returns = self.log_returns()

        pivot = returns.pivot_table(
            index="price_date", columns="symbol", values="log_return"
        )
        corr = pivot.corr(method="pearson").round(4)
        return corr

    # ------------------------------------------------------------------
    # Trade Activity
    # ------------------------------------------------------------------

    def monthly_activity(self) -> pd.DataFrame:
        """Trade count and notional volume aggregated by month."""
        trades = self._data["trades"].copy()
        active = trades[trades["status"] != "Cancelled"]

        active = active.copy()
        active["month"] = active["trade_date"].dt.to_period("M")

        monthly = (
            active.groupby(["month", "desk", "buy_sell"])
            .agg(
                trade_count    = ("trade_id",     "count"),
                total_notional = ("notional_usd", "sum"),
                avg_size       = ("notional_usd", "mean"),
            )
            .reset_index()
            .sort_values(["month", "desk"])
        )
        monthly["total_notional"] = monthly["total_notional"].round(2)
        monthly["avg_size"]       = monthly["avg_size"].round(2)
        return monthly

    def top_counterparties(self, n: int = 5) -> pd.DataFrame:
        """Top N counterparties by gross exposure."""
        trades = self._data["trades"]
        active = trades[trades["status"] != "Cancelled"]

        return (
            active.groupby("counterparty")
            .agg(
                trade_count    = ("trade_id",     "count"),
                gross_exposure = ("notional_usd", "sum"),
                avg_trade_size = ("notional_usd", "mean"),
            )
            .reset_index()
            .sort_values("gross_exposure", ascending=False)
            .head(n)
            .round(2)
        )


# =============================================================================
# RiskReporter — Formats and prints analytical output
# =============================================================================

class RiskReporter:
    """
    Formats MetalsAnalyser results into console reports and CSV exports.

    Separates presentation logic from analysis logic — the analyser
    computes, the reporter communicates.
    """

    SEP  = "─" * 70
    SEP2 = "═" * 70

    def __init__(self, analyser: MetalsAnalyser):
        self._analyser = analyser
        self._log      = logging.getLogger("analysis.reporter")

    def __repr__(self) -> str:
        return f"RiskReporter(analyser={self._analyser!r})"

    def _header(self, title: str):
        print(f"\n{self.SEP2}")
        print(f"  {title}")
        print(self.SEP2)

    def _fmt_usd(self, val: float) -> str:
        sign = "▲ +" if val > 0 else ("▼ " if val < 0 else "  ")
        return f"{sign}${abs(val):>14,.2f}"

    def print_pnl_report(self):
        self._header("PnL SUMMARY")

        # Desk level
        print(f"\n{'DESK':20s}  {'MTM VALUE':>16}  {'COST BASIS':>16}  {'UNREALISED PnL':>18}  {'PnL%':>8}  {'POSITIONS':>10}")
        print(self.SEP)
        for s in self._analyser.pnl_by_desk():
            print(
                f"{s.label:20s}  "
                f"${s.total_mtm:>15,.2f}  "
                f"${s.total_cost:>15,.2f}  "
                f"{self._fmt_usd(s.unrealised_pnl):>18}  "
                f"{s.pnl_pct:>+7.2f}%  "
                f"{s.position_count:>4} pos ({s.long_count}L/{s.short_count}S)"
            )

        # Metal level
        print(f"\n{'METAL':12s}  {'SYMBOL':7s}  {'MTM VALUE':>16}  {'UNREALISED PnL':>18}  {'PnL%':>8}  {'DIR':6}")
        print(self.SEP)
        for _, row in self._analyser.pnl_by_metal().iterrows():
            print(
                f"{row['metal']:12s}  "
                f"{row['symbol']:7s}  "
                f"${row['total_mtm']:>15,.2f}  "
                f"{self._fmt_usd(row['unrealised_pnl']):>18}  "
                f"{row['pnl_pct']:>+7.2f}%  "
                f"{row['pnl_direction']:6s}"
            )

        # Win/loss
        wl = self._analyser.win_loss_ratio()
        print(f"\n  Win rate: {wl['win_rate']}%  "
              f"({wl['winners']} winners / {wl['losers']} losers)  "
              f"Avg win: ${wl['avg_win_usd']:,.0f}  "
              f"Avg loss: ${wl['avg_loss_usd']:,.0f}")

    def print_risk_report(self):
        self._header("RISK EXPOSURE & CONCENTRATION")

        conc_df = self._analyser.concentration_flags()
        print(f"\n{'METAL':12s}  {'SYMBOL':7s}  {'GROSS LONG':>16}  {'GROSS SHORT':>16}  {'NET EXPOSURE':>16}  {'CONC%':>7}  {'TIER':8}")
        print(self.SEP)
        for _, row in conc_df.iterrows():
            flag = "  ⚠" if row["breach"] else ""
            print(
                f"{row['metal']:12s}  "
                f"{row['symbol']:7s}  "
                f"${row['gross_long']:>15,.0f}  "
                f"${row['gross_short']:>15,.0f}  "
                f"{self._fmt_usd(row['net_exposure']):>16}  "
                f"{row['concentration']:>6.1%}  "
                f"{str(row['risk_tier']):8}{flag}"
            )

        print(f"\n  TOP 5 COUNTERPARTIES BY EXPOSURE")
        print(f"  {'COUNTERPARTY':25s}  {'TRADES':>6}  {'GROSS EXPOSURE':>16}  {'AVG SIZE':>14}")
        print(f"  {self.SEP}")
        for _, row in self._analyser.top_counterparties(5).iterrows():
            print(
                f"  {row['counterparty']:25s}  "
                f"{row['trade_count']:>6}  "
                f"  ${row['gross_exposure']:>14,.0f}  "
                f"  ${row['avg_trade_size']:>12,.0f}"
            )

    def print_volatility_report(self):
        self._header("VOLATILITY SUMMARY")

        print(f"\n{'METAL':12s}  {'SYMBOL':7s}  {'ANN VOL%':>9}  {'52W HIGH':>12}  {'52W LOW':>12}  {'RANGE%':>8}")
        print(self.SEP)
        for v in self._analyser.volatility_summary():
            print(
                f"{v.metal:12s}  "
                f"{v.symbol:7s}  "
                f"{v.annualised_vol:>8.2f}%  "
                f"${v.high_52w:>11,.2f}  "
                f"${v.low_52w:>11,.2f}  "
                f"{v.price_range_pct:>7.1f}%"
            )

        print(f"\n  RETURN CORRELATION MATRIX (Pearson, log returns)")
        corr = self._analyser.correlation_matrix()
        print(corr.to_string())

    def export_to_csv(self, output_dir: str | Path):
        """Export all analytical outputs to CSV files."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        exports = {
            "analysis_pnl_by_metal.csv":       self._analyser.pnl_by_metal(),
            "analysis_exposure.csv":            self._analyser.concentration_flags(),
            "analysis_volatility.csv":          self._analyser.rolling_volatility(),
            "analysis_correlation.csv":         self._analyser.correlation_matrix(),
            "analysis_monthly_activity.csv":    self._analyser.monthly_activity(),
            "analysis_top_counterparties.csv":  self._analyser.top_counterparties(10),
        }

        for filename, df in exports.items():
            path = out / filename
            df.to_csv(path, index=True)
            self._log.info(f"Exported {filename} ({len(df)} rows)")

        print(f"\n  Exported {len(exports)} files to {out}/")


# =============================================================================
# MetalsDashboard — Facade composing all three components
# =============================================================================

class MetalsDashboard:
    """
    Facade class — single entry point for the entire analysis pipeline.

    Composes DataLoader + MetalsAnalyser + RiskReporter.
    Demonstrates the Facade design pattern: callers only need this one
    class to run any analysis.

    Usage:
        dashboard = MetalsDashboard("data/")
        dashboard.run_all()
        dashboard.run(["pnl", "risk"])
    """

    AVAILABLE_REPORTS = ["pnl", "risk", "vol", "all"]

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self._log     = logging.getLogger("analysis.dashboard")

        self._log.info(f"Initialising MetalsDashboard  data_dir={self.data_dir}")

        self.loader   = DataLoader(data_dir)
        self.analyser = MetalsAnalyser(self.loader)
        self.reporter = RiskReporter(self.analyser)

        self._log.info(f"Ready: {self.analyser}")

    def __repr__(self) -> str:
        return f"MetalsDashboard(data_dir={self.data_dir!r})"

    def run(self, reports: list[str], export: bool = False):
        """Run selected reports. reports can include 'pnl', 'risk', 'vol', 'all'."""
        run_all = "all" in reports

        print(f"\n{'━'*70}")
        print(f"  METALS RISK DASHBOARD — Analysis Report")
        print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'━'*70}")

        if run_all or "pnl" in reports:
            self.reporter.print_pnl_report()

        if run_all or "risk" in reports:
            self.reporter.print_risk_report()

        if run_all or "vol" in reports:
            self.reporter.print_volatility_report()

        if export:
            self.reporter.export_to_csv(self.data_dir / "analysis_output")

        print(f"\n{'━'*70}\n")

    def run_all(self, export: bool = False):
        self.run(["all"], export=export)


# =============================================================================
# CLI entry point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Metals Risk Dashboard — OOP Analysis Module",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python python/analysis.py                      # all reports
  python python/analysis.py --report pnl         # PnL only
  python python/analysis.py --report risk vol    # risk + vol
  python python/analysis.py --export             # also save CSVs
        """
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--report",   nargs="+",
                        choices=MetalsDashboard.AVAILABLE_REPORTS,
                        default=["all"])
    parser.add_argument("--export",   action="store_true",
                        help="Export results to CSV in data/analysis_output/")
    args = parser.parse_args()

    dashboard = MetalsDashboard(args.data_dir)
    dashboard.run(args.report, export=args.export)


if __name__ == "__main__":
    main()


# =============================================================================
# SCIPY ADDITIONS — appended to MetalsAnalyser via monkey-patch style extension
# These functions are imported and called from MetalsAnalyser directly in usage.
# =============================================================================

def _correlation_matrix_scipy(self) -> "pd.DataFrame":
    """
    Pearson correlation matrix cross-validated with scipy.stats.pearsonr.
    Replaces the original method to demonstrate scipy usage.
    """
    from scipy import stats as scipy_stats
    returns = self.log_returns()
    pivot   = returns.pivot_table(
        index="price_date", columns="symbol", values="log_return"
    ).dropna()
    corr_matrix = pivot.corr(method="pearson").round(4)
    symbols = list(pivot.columns)
    if len(symbols) >= 2:
        r, p = scipy_stats.pearsonr(pivot[symbols[0]], pivot[symbols[1]])
        self._log.info(
            f"  scipy cross-check: corr({symbols[0]},{symbols[1]})="
            f"{r:.4f}  p={p:.4f}  pandas={corr_matrix.loc[symbols[0],symbols[1]]:.4f}"
        )
    return corr_matrix


def normality_tests(self) -> "pd.DataFrame":
    """
    Shapiro-Wilk normality test on log returns per metal (scipy.stats).
    Tests whether returns are normally distributed — key assumption for VaR models.
    p-value < 0.05 rejects normality.
    """
    import pandas as pd
    from scipy import stats as scipy_stats
    returns = self.log_returns()
    results = []
    for symbol, grp in returns.groupby("symbol"):
        rets = grp["log_return"].dropna().values
        if len(rets) < 10:
            continue
        stat, p_value = scipy_stats.shapiro(rets[:500])
        results.append({
            "symbol":         symbol,
            "metal":          grp["metal"].iloc[0],
            "n_obs":          len(rets),
            "shapiro_w":      round(float(stat), 4),
            "p_value":        round(float(p_value), 4),
            "normal_at_5pct": "Yes" if p_value > 0.05 else "No",
        })
    return pd.DataFrame(results).sort_values("p_value")


# Patch methods onto MetalsAnalyser
MetalsAnalyser.correlation_matrix = _correlation_matrix_scipy
MetalsAnalyser.normality_tests     = normality_tests

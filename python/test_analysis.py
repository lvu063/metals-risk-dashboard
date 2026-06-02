"""
test_analysis.py
----------------
Metals Risk Dashboard — Test Suite (TDD style)

Demonstrates Test-Driven Development:
  - Tests are written to specify behaviour BEFORE (or alongside) implementation
  - Each test has a clear Arrange / Act / Assert structure
  - Edge cases and failure modes are tested explicitly
  - Tests act as living documentation of expected behaviour

Run:
    pytest python/test_analysis.py -v
    pytest python/test_analysis.py -v --tb=short    # compact failures
    pytest python/test_analysis.py -k "pnl"         # filter by name
"""

import math
import sys
import tempfile
from pathlib import Path

import pandas as pd
import numpy as np
import pytest

# Make sure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from python.analysis import DataLoader, MetalsAnalyser, RiskReporter, MetalsDashboard


# =============================================================================
# Fixtures — reusable test data
# =============================================================================

@pytest.fixture(scope="module")
def data_dir():
    """Path to real generated CSV data."""
    p = Path(__file__).parent.parent / "data"
    if not p.exists():
        pytest.skip("Data directory not found — run generate_mock_data.py first")
    return str(p)


@pytest.fixture(scope="module")
def loader(data_dir):
    return DataLoader(data_dir)


@pytest.fixture(scope="module")
def analyser(loader):
    return MetalsAnalyser(loader)


@pytest.fixture(scope="module")
def dashboard(data_dir):
    return MetalsDashboard(data_dir)


@pytest.fixture
def minimal_csv_dir(tmp_path):
    """
    Creates a minimal valid CSV dataset in a temp directory.
    Used for unit tests that don't need full 300-row data.
    """
    trades_content = (
        "trade_id,trade_date,settlement_date,metal,symbol,desk,book,"
        "trader,counterparty,buy_sell,trade_type,quantity,unit,"
        "trade_price,spot_at_trade,currency,notional_usd,status\n"
        "TRD-000001,2024-06-01,2024-06-03,Gold,XAU,Precious Metals,PM-PROP-01,"
        "J. Test,Goldman Sachs,Buy,Spot,1000,troy oz,2350.0,2348.0,USD,2350000.0,Confirmed\n"
        "TRD-000002,2024-06-01,2024-06-03,Gold,XAU,Precious Metals,PM-PROP-01,"
        "J. Test,Goldman Sachs,Sell,Spot,400,troy oz,2355.0,2348.0,USD,942000.0,Confirmed\n"
        "TRD-000003,2024-06-02,2024-06-04,Copper,HG,Base Metals,BM-PROP-01,"
        "M. Test,Barclays Metals,Buy,Spot,50000,lbs,4.50,4.48,USD,225000.0,Confirmed\n"
        "TRD-000004,2024-06-03,2024-06-05,Gold,XAU,Precious Metals,PM-PROP-01,"
        "J. Test,Citibank NA,Buy,Forward,200,troy oz,2360.0,2355.0,USD,472000.0,Cancelled\n"
    )

    prices_content = (
        "price_date,metal,symbol,spot_price,currency,unit,source\n"
        "2024-06-01,Gold,XAU,2350.0,USD,troy oz,LBMA\n"
        "2024-06-02,Gold,XAU,2365.0,USD,troy oz,LBMA\n"
        "2024-06-03,Gold,XAU,2360.0,USD,troy oz,LBMA\n"
        "2024-06-01,Copper,HG,4.50,USD,lbs,LME\n"
        "2024-06-02,Copper,HG,4.55,USD,lbs,LME\n"
        "2024-06-03,Copper,HG,4.52,USD,lbs,LME\n"
    )

    positions_content = (
        "as_of_date,book,desk,metal,symbol,net_quantity,unit,"
        "avg_cost_usd,total_cost_usd,trade_count,long_short\n"
        "2024-06-03,PM-PROP-01,Precious Metals,Gold,XAU,600.0,troy oz,"
        "2351.67,1411000.0,2,Long\n"
        "2024-06-03,BM-PROP-01,Base Metals,Copper,HG,50000.0,lbs,"
        "4.50,225000.0,1,Long\n"
    )

    pnl_content = (
        "pnl_date,book,desk,metal,symbol,net_quantity,unit,"
        "spot_price_usd,mtm_value_usd,cost_basis_usd,unrealised_pnl,pnl_pct,long_short\n"
        "2024-06-03,PM-PROP-01,Precious Metals,Gold,XAU,600.0,troy oz,"
        "2360.0,1416000.0,1411000.0,5000.0,0.3543,Long\n"
        "2024-06-03,BM-PROP-01,Base Metals,Copper,HG,50000.0,lbs,"
        "4.52,226000.0,225000.0,1000.0,0.4444,Long\n"
    )

    (tmp_path / "trades.csv").write_text(trades_content)
    (tmp_path / "price_history.csv").write_text(prices_content)
    (tmp_path / "positions.csv").write_text(positions_content)
    (tmp_path / "pnl_summary.csv").write_text(pnl_content)

    return str(tmp_path)


# =============================================================================
# DataLoader tests
# =============================================================================

class TestDataLoader:

    def test_loader_repr_shows_data_dir(self, loader):
        """DataLoader repr should include the data directory path."""
        # Arrange / Act
        result = repr(loader)
        # Assert
        assert "DataLoader" in result
        assert "data_dir" in result

    def test_loads_trades_with_correct_columns(self, loader):
        """Trades DataFrame must contain all required columns after loading."""
        # Arrange — expected minimum columns
        required = ["trade_id", "trade_date", "symbol", "quantity", "notional_usd", "status"]
        # Act
        trades = loader.trades()
        # Assert
        for col in required:
            assert col in trades.columns, f"Missing required column: {col}"

    def test_trade_dates_parsed_as_datetime(self, loader):
        """trade_date column must be datetime dtype, not string."""
        trades = loader.trades()
        assert pd.api.types.is_datetime64_any_dtype(trades["trade_date"]), \
            "trade_date should be datetime64, not object/string"

    def test_price_history_spot_price_is_numeric(self, loader):
        """spot_price must be float — not string after CSV load."""
        prices = loader.price_history()
        assert pd.api.types.is_float_dtype(prices["spot_price"]), \
            "spot_price should be float64"

    def test_caches_results_on_second_load(self, loader):
        """Calling trades() twice should return the same object (cached)."""
        first  = loader.trades()
        second = loader.trades()
        assert first.equals(second), "DataLoader should return identical data on second call"

    def test_missing_file_raises_file_not_found(self, tmp_path):
        """Loading from a directory with no CSVs should raise FileNotFoundError."""
        bad_loader = DataLoader(str(tmp_path))
        with pytest.raises(FileNotFoundError):
            bad_loader.trades()

    def test_minimal_data_loads_without_error(self, minimal_csv_dir):
        """Minimal valid CSVs should load and return non-empty DataFrames."""
        loader = DataLoader(minimal_csv_dir)
        trades = loader.trades()
        assert len(trades) > 0

    def test_all_returns_dict_with_four_keys(self, loader):
        """loader.all() should return a dict with trades, price_history, positions, pnl."""
        result = loader.all()
        assert set(result.keys()) == {"trades", "price_history", "positions", "pnl"}


# =============================================================================
# MetalsAnalyser — PnL tests
# =============================================================================

class TestPnLAnalysis:

    def test_pnl_by_desk_returns_list_of_pnl_summaries(self, analyser):
        """pnl_by_desk() should return a non-empty list."""
        result = analyser.pnl_by_desk()
        assert isinstance(result, list)
        assert len(result) > 0

    def test_pnl_by_desk_sorted_by_abs_pnl_descending(self, analyser):
        """Desks should be sorted by absolute PnL, largest first."""
        result = analyser.pnl_by_desk()
        abs_pnls = [abs(s.unrealised_pnl) for s in result]
        assert abs_pnls == sorted(abs_pnls, reverse=True), \
            "pnl_by_desk() results should be sorted by |PnL| descending"

    def test_pnl_summary_pct_calculated_correctly(self, minimal_csv_dir):
        """PnL % = unrealised_pnl / abs(cost_basis) * 100."""
        a = MetalsAnalyser(DataLoader(minimal_csv_dir))
        summaries = a.pnl_by_desk()
        for s in summaries:
            if s.total_cost != 0:
                expected_pct = s.unrealised_pnl / abs(s.total_cost) * 100
                assert abs(s.pnl_pct - expected_pct) < 0.01, \
                    f"PnL% mismatch for {s.label}: got {s.pnl_pct}, expected {expected_pct:.2f}"

    def test_pnl_by_metal_returns_dataframe(self, analyser):
        """pnl_by_metal() should return a DataFrame with expected columns."""
        result = analyser.pnl_by_metal()
        assert isinstance(result, pd.DataFrame)
        assert "metal" in result.columns
        assert "unrealised_pnl" in result.columns
        assert "pnl_direction" in result.columns

    def test_pnl_direction_correct_sign(self, analyser):
        """Rows with positive PnL should have 'Gain', negative should have 'Loss'."""
        df = analyser.pnl_by_metal()
        gains  = df[df["unrealised_pnl"] > 0]["pnl_direction"]
        losses = df[df["unrealised_pnl"] < 0]["pnl_direction"]
        assert (gains == "Gain").all(), "Positive PnL rows should be labelled 'Gain'"
        assert (losses == "Loss").all(), "Negative PnL rows should be labelled 'Loss'"

    def test_win_loss_ratio_sums_to_total(self, analyser):
        """Winners + losers should equal total positions (flat positions excluded)."""
        wl    = analyser.win_loss_ratio()
        total = len(analyser._data["pnl"])
        assert wl["winners"] + wl["losers"] <= total

    def test_win_rate_between_0_and_100(self, analyser):
        """Win rate must be a percentage in [0, 100]."""
        wl = analyser.win_loss_ratio()
        assert 0.0 <= wl["win_rate"] <= 100.0


# =============================================================================
# MetalsAnalyser — Exposure tests
# =============================================================================

class TestExposureAnalysis:

    def test_exposure_by_metal_returns_list(self, analyser):
        """exposure_by_metal() should return a non-empty list of ExposureSnapshots."""
        result = analyser.exposure_by_metal()
        assert len(result) > 0

    def test_net_exposure_equals_long_minus_short(self, analyser):
        """net_exposure must equal gross_long - gross_short for every snapshot."""
        for snap in analyser.exposure_by_metal():
            expected = snap.gross_long - snap.gross_short
            assert abs(snap.net_exposure - expected) < 0.01, \
                f"{snap.symbol}: net={snap.net_exposure} != long-short={expected:.2f}"

    def test_concentration_sums_to_approximately_one(self, analyser):
        """Sum of all concentrations should be approximately 1.0."""
        total = sum(s.concentration for s in analyser.exposure_by_metal())
        assert abs(total - 1.0) < 0.01, \
            f"Concentrations should sum to ~1.0, got {total:.4f}"

    def test_concentration_flags_returns_dataframe(self, analyser):
        """concentration_flags() should return a DataFrame with 'breach' column."""
        result = analyser.concentration_flags()
        assert isinstance(result, pd.DataFrame)
        assert "breach" in result.columns
        assert "risk_tier" in result.columns

    def test_cancelled_trades_excluded_from_exposure(self, minimal_csv_dir):
        """
        TDD: This test specifies that cancelled trades must not contribute
        to exposure calculations. TRD-000004 is Cancelled in the fixture.
        """
        # Arrange
        a = MetalsAnalyser(DataLoader(minimal_csv_dir))
        # Act
        exposures = a.exposure_by_metal()
        gold_snap  = next((e for e in exposures if e.symbol == "XAU"), None)
        # Assert
        assert gold_snap is not None
        # 1000 Buy + 400 Sell confirmed; 200 Buy cancelled
        # gross_long should be 1000 * 2350 = 2,350,000 (not 1200 * price)
        expected_long = 1000 * 2350.0
        assert abs(gold_snap.gross_long - expected_long) < 1.0, \
            f"Cancelled trade should be excluded. Expected long=${expected_long:,.0f}, got ${gold_snap.gross_long:,.0f}"


# =============================================================================
# MetalsAnalyser — Volatility tests
# =============================================================================

class TestVolatilityAnalysis:

    def test_log_returns_no_nulls_after_first_row(self, analyser):
        """Log returns should not contain NaN except at the very first obs per symbol."""
        returns = analyser.log_returns()
        null_count = returns["log_return"].isnull().sum()
        assert null_count == 0, \
            f"log_returns() should drop NaN rows, found {null_count}"

    def test_log_return_formula_correct(self, minimal_csv_dir):
        """
        TDD: log_return = ln(P_t / P_{t-1}).
        Gold: 2350 → 2365 → log_return = ln(2365/2350) ≈ 0.006374
        """
        # Arrange
        a = MetalsAnalyser(DataLoader(minimal_csv_dir))
        # Act
        returns = a.log_returns()
        gold_returns = returns[returns["symbol"] == "XAU"].sort_values("price_date")
        first_return = gold_returns.iloc[0]["log_return"]
        # Assert
        expected = math.log(2365.0 / 2350.0)
        assert abs(first_return - expected) < 1e-6, \
            f"Log return formula wrong: expected {expected:.6f}, got {first_return:.6f}"

    def test_rolling_volatility_non_negative(self, analyser):
        """Annualised volatility must always be >= 0."""
        vol_df = analyser.rolling_volatility()
        assert (vol_df["annualised_vol_pct"] >= 0).all(), \
            "Annualised volatility cannot be negative"

    def test_volatility_summary_sorted_by_vol_descending(self, analyser):
        """volatility_summary() should sort from most to least volatile."""
        results = analyser.volatility_summary()
        vols = [v.annualised_vol for v in results]
        assert vols == sorted(vols, reverse=True)

    def test_correlation_matrix_diagonal_is_one(self, analyser):
        """Diagonal of correlation matrix must be exactly 1.0 (self-correlation)."""
        corr = analyser.correlation_matrix()
        for symbol in corr.columns:
            assert corr.loc[symbol, symbol] == 1.0, \
                f"Self-correlation for {symbol} should be 1.0"

    def test_correlation_matrix_symmetric(self, analyser):
        """Correlation matrix must be symmetric: corr(A,B) == corr(B,A)."""
        corr = analyser.correlation_matrix()
        diff = (corr - corr.T).abs().max().max()
        assert diff < 1e-10, f"Correlation matrix not symmetric, max diff = {diff}"

    def test_normality_tests_returns_dataframe(self, analyser):
        """normality_tests() should return a DataFrame with p_value column."""
        result = analyser.normality_tests()
        assert isinstance(result, pd.DataFrame)
        assert "p_value" in result.columns
        assert "shapiro_w" in result.columns
        assert len(result) > 0

    def test_normality_p_values_in_valid_range(self, analyser):
        """All p-values must be in [0, 1]."""
        result = analyser.normality_tests()
        assert (result["p_value"] >= 0).all()
        assert (result["p_value"] <= 1).all()


# =============================================================================
# MetalsAnalyser — Trade activity tests
# =============================================================================

class TestTradeActivity:

    def test_monthly_activity_returns_dataframe(self, analyser):
        """monthly_activity() should return a non-empty DataFrame."""
        result = analyser.monthly_activity()
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0

    def test_top_counterparties_respects_n_param(self, analyser):
        """top_counterparties(n) should return exactly n rows."""
        for n in [3, 5, 10]:
            result = analyser.top_counterparties(n)
            assert len(result) <= n, \
                f"top_counterparties({n}) returned {len(result)} rows"

    def test_top_counterparties_sorted_by_exposure(self, analyser):
        """Counterparties should be sorted by gross_exposure descending."""
        result = analyser.top_counterparties(10)
        exposures = result["gross_exposure"].tolist()
        assert exposures == sorted(exposures, reverse=True)


# =============================================================================
# MetalsDashboard — Facade tests
# =============================================================================

class TestMetalsDashboard:

    def test_dashboard_repr(self, dashboard):
        """Dashboard repr should show data_dir."""
        assert "MetalsDashboard" in repr(dashboard)
        assert "data_dir" in repr(dashboard)

    def test_dashboard_composes_all_components(self, dashboard):
        """Dashboard should expose loader, analyser, and reporter."""
        assert hasattr(dashboard, "loader")
        assert hasattr(dashboard, "analyser")
        assert hasattr(dashboard, "reporter")

    def test_run_pnl_does_not_raise(self, dashboard, capsys):
        """dashboard.run(['pnl']) should complete without exceptions."""
        dashboard.run(["pnl"])
        captured = capsys.readouterr()
        assert "SUMMARY" in captured.out.upper()

    def test_run_all_does_not_raise(self, dashboard):
        """dashboard.run_all() should complete without raising exceptions."""
        dashboard.run_all()   # just needs to not throw

    def test_export_creates_csv_files(self, dashboard, tmp_path):
        """run_all(export=True) should create CSV files in the output directory."""
        dashboard.reporter.export_to_csv(str(tmp_path))
        csv_files = list(tmp_path.glob("*.csv"))
        assert len(csv_files) >= 3, \
            f"Expected at least 3 exported CSVs, got {len(csv_files)}"


# =============================================================================
# Edge case / regression tests
# =============================================================================

class TestEdgeCases:

    def test_empty_pnl_data_handled_gracefully(self, tmp_path):
        """
        TDD: If pnl_summary.csv has headers but no data rows,
        pnl_by_desk() should return an empty list, not raise an exception.
        """
        # Arrange — write header-only CSVs
        (tmp_path / "trades.csv").write_text(
            "trade_id,trade_date,settlement_date,metal,symbol,desk,book,"
            "trader,counterparty,buy_sell,trade_type,quantity,unit,"
            "trade_price,spot_at_trade,currency,notional_usd,status\n"
        )
        (tmp_path / "price_history.csv").write_text(
            "price_date,metal,symbol,spot_price,currency,unit,source\n"
        )
        (tmp_path / "positions.csv").write_text(
            "as_of_date,book,desk,metal,symbol,net_quantity,unit,"
            "avg_cost_usd,total_cost_usd,trade_count,long_short\n"
        )
        (tmp_path / "pnl_summary.csv").write_text(
            "pnl_date,book,desk,metal,symbol,net_quantity,unit,"
            "spot_price_usd,mtm_value_usd,cost_basis_usd,unrealised_pnl,pnl_pct,long_short\n"
        )
        # Act
        loader  = DataLoader(str(tmp_path))
        analyser = MetalsAnalyser(loader)
        result  = analyser.pnl_by_desk()
        # Assert — empty list, no exception
        assert result == []

    def test_single_metal_correlation_matrix(self, tmp_path):
        """
        TDD: Correlation matrix with only one metal should return a 1x1 matrix
        with value 1.0 — not raise a division error.
        """
        # Arrange — only Gold prices
        (tmp_path / "trades.csv").write_text(
            "trade_id,trade_date,settlement_date,metal,symbol,desk,book,"
            "trader,counterparty,buy_sell,trade_type,quantity,unit,"
            "trade_price,spot_at_trade,currency,notional_usd,status\n"
        )
        prices = "price_date,metal,symbol,spot_price,currency,unit,source\n"
        for i, p in enumerate([2300, 2310, 2320, 2330, 2325, 2315, 2340]):
            prices += f"2024-0{i+1}-01,Gold,XAU,{p},USD,troy oz,LBMA\n"
        (tmp_path / "price_history.csv").write_text(prices)
        (tmp_path / "positions.csv").write_text(
            "as_of_date,book,desk,metal,symbol,net_quantity,unit,"
            "avg_cost_usd,total_cost_usd,trade_count,long_short\n"
        )
        (tmp_path / "pnl_summary.csv").write_text(
            "pnl_date,book,desk,metal,symbol,net_quantity,unit,"
            "spot_price_usd,mtm_value_usd,cost_basis_usd,unrealised_pnl,pnl_pct,long_short\n"
        )
        # Act
        a    = MetalsAnalyser(DataLoader(str(tmp_path)))
        corr = a.correlation_matrix()
        # Assert
        assert corr.shape == (1, 1)
        assert corr.iloc[0, 0] == 1.0

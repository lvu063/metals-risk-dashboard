"""
api.py
------
Metals Risk Dashboard — REST API (Microservice)

Wraps the MetalsAnalyser as a FastAPI microservice, demonstrating:
  - Microservices architecture (single-responsibility service)
  - Applications integration (REST endpoints other systems can call)
  - Pydantic response models (typed contracts between services)
  - Dependency injection (FastAPI's Depends pattern)
  - Error handling (HTTPException with meaningful codes)

In a production MLOps context, this API would sit behind an API
gateway and be called by the Power BI dataset refresh, Power Automate
flows, or downstream risk systems — replacing file drops.

Usage:
    pip install fastapi uvicorn
    uvicorn python.api:app --reload --port 8000

Endpoints:
    GET  /health                     — liveness check
    GET  /pnl/summary                — PnL by desk
    GET  /pnl/metals                 — PnL by metal
    GET  /exposure                   — Gross/net exposure
    GET  /exposure/concentration     — Concentration flags
    GET  /volatility                 — Vol summary per metal
    GET  /volatility/correlation     — Return correlation matrix
    GET  /volatility/normality       — Shapiro-Wilk normality tests
    GET  /trades/activity            — Monthly trade activity
    GET  /trades/counterparties      — Top N counterparty exposure
    POST /refresh                    — Reload data from disk

Interactive docs: http://localhost:8000/docs
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Lazy import — avoids loading pandas/numpy at import time in test envs
# ---------------------------------------------------------------------------
def _get_analyser_module():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from python.analysis import DataLoader, MetalsAnalyser
    return DataLoader, MetalsAnalyser


# ---------------------------------------------------------------------------
# Pydantic response models — typed contracts for API consumers
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    data_dir: str
    tables_loaded: list[str]


class PnLDeskItem(BaseModel):
    desk:           str
    total_mtm:      float
    total_cost:     float
    unrealised_pnl: float
    pnl_pct:        float
    position_count: int
    long_count:     int
    short_count:    int


class PnLMetalItem(BaseModel):
    metal:          str
    symbol:         str
    total_mtm:      float
    total_cost:     float
    unrealised_pnl: float
    pnl_pct:        float
    pnl_direction:  str
    position_count: int


class ExposureItem(BaseModel):
    metal:         str
    symbol:        str
    gross_long:    float
    gross_short:   float
    net_exposure:  float
    trade_count:   int
    concentration: float


class ConcentrationItem(BaseModel):
    metal:         str
    symbol:        str
    gross_long:    float
    gross_short:   float
    net_exposure:  float
    concentration: float
    risk_tier:     str
    breach:        bool


class VolatilityItem(BaseModel):
    symbol:          str
    metal:           str
    annualised_vol:  float = Field(description="Annualised vol % from 30-day rolling window")
    high_52w:        float
    low_52w:         float
    price_range_pct: float


class NormalityItem(BaseModel):
    symbol:         str
    metal:          str
    n_obs:          int
    shapiro_w:      float
    p_value:        float
    normal_at_5pct: str


class RefreshResponse(BaseModel):
    status:  str
    message: str
    rows:    dict[str, int]


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title       = "Metals Risk Dashboard API",
    description = (
        "REST microservice exposing the MetalsAnalyser as HTTP endpoints. "
        "Demonstrates microservices architecture and applications integration."
    ),
    version     = "1.0.0",
    contact     = {"name": "Risk Technology", "email": "risk-tech@example.com"},
)

# Data directory — override with env var for different environments
DATA_DIR = os.getenv("METALS_DATA_DIR", "data")

# Module-level analyser instance (loaded once on startup)
_analyser_instance: object = None


# ---------------------------------------------------------------------------
# Dependency injection — FastAPI's Depends pattern
# ---------------------------------------------------------------------------

def get_analyser():
    """
    Dependency: provides a MetalsAnalyser instance to route handlers.
    Uses module-level singleton; raises 503 if data not loaded.
    """
    global _analyser_instance
    if _analyser_instance is None:
        try:
            DataLoader, MetalsAnalyser = _get_analyser_module()
            loader = DataLoader(DATA_DIR)
            _analyser_instance = MetalsAnalyser(loader)
        except FileNotFoundError as e:
            raise HTTPException(
                status_code=503,
                detail=f"Data not available: {e}. Run generate_mock_data.py first."
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to initialise analyser: {e}"
            )
    return _analyser_instance


# ---------------------------------------------------------------------------
# Startup event
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def load_data_on_startup():
    """Pre-load data when the service starts — avoids cold start on first request."""
    global _analyser_instance
    try:
        DataLoader, MetalsAnalyser = _get_analyser_module()
        loader = DataLoader(DATA_DIR)
        _analyser_instance = MetalsAnalyser(loader)
        print(f"✓ MetalsAnalyser initialised from {DATA_DIR}")
    except Exception as e:
        print(f"⚠ Could not pre-load data: {e}")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Liveness check",
)
def health(analyser=Depends(get_analyser)):
    """Returns service health and which datasets are currently loaded."""
    tables = list(analyser._data.keys())
    return HealthResponse(
        status        = "ok",
        data_dir      = DATA_DIR,
        tables_loaded = tables,
    )


@app.get(
    "/pnl/summary",
    response_model=list[PnLDeskItem],
    tags=["PnL"],
    summary="PnL aggregated by trading desk",
)
def pnl_by_desk(analyser=Depends(get_analyser)):
    """
    Returns unrealised PnL, MTM value, and position counts for each
    trading desk (Precious Metals, Base Metals).
    Sorted by absolute PnL descending.
    """
    summaries = analyser.pnl_by_desk()
    return [
        PnLDeskItem(
            desk           = s.label,
            total_mtm      = s.total_mtm,
            total_cost     = s.total_cost,
            unrealised_pnl = s.unrealised_pnl,
            pnl_pct        = s.pnl_pct,
            position_count = s.position_count,
            long_count     = s.long_count,
            short_count    = s.short_count,
        )
        for s in summaries
    ]


@app.get(
    "/pnl/metals",
    response_model=list[PnLMetalItem],
    tags=["PnL"],
    summary="PnL contribution broken down by metal",
)
def pnl_by_metal(analyser=Depends(get_analyser)):
    """
    Returns PnL contribution per metal, sorted by absolute PnL.
    Useful for identifying which metals are driving portfolio gains/losses.
    """
    df = analyser.pnl_by_metal()
    return [
        PnLMetalItem(
            metal          = row["metal"],
            symbol         = row["symbol"],
            total_mtm      = row["total_mtm"],
            total_cost     = row["total_cost"],
            unrealised_pnl = row["unrealised_pnl"],
            pnl_pct        = row["pnl_pct"],
            pnl_direction  = row["pnl_direction"],
            position_count = int(row["position_count"]),
        )
        for _, row in df.iterrows()
    ]


@app.get(
    "/exposure",
    response_model=list[ExposureItem],
    tags=["Risk"],
    summary="Gross and net exposure by metal",
)
def exposure(analyser=Depends(get_analyser)):
    """
    Returns gross long, gross short, and net USD exposure per metal.
    Cancelled trades are excluded. Sorted by absolute net exposure.
    """
    snapshots = analyser.exposure_by_metal()
    return [
        ExposureItem(
            metal         = s.metal,
            symbol        = s.symbol,
            gross_long    = s.gross_long,
            gross_short   = s.gross_short,
            net_exposure  = s.net_exposure,
            trade_count   = s.trade_count,
            concentration = s.concentration,
        )
        for s in snapshots
    ]


@app.get(
    "/exposure/concentration",
    response_model=list[ConcentrationItem],
    tags=["Risk"],
    summary="Concentration flags with risk tier",
)
def concentration(
    threshold: float = Query(default=0.40, description="Breach threshold (0–1)"),
    analyser=Depends(get_analyser),
):
    """
    Returns concentration analysis with risk tiers (Normal / Elevated / Medium / HIGH).
    The `breach` flag is True when concentration exceeds the threshold.
    """
    df = analyser.concentration_flags(threshold=threshold)
    return [
        ConcentrationItem(
            metal         = row["metal"],
            symbol        = row["symbol"],
            gross_long    = row["gross_long"],
            gross_short   = row["gross_short"],
            net_exposure  = row["net_exposure"],
            concentration = row["concentration"],
            risk_tier     = str(row["risk_tier"]),
            breach        = bool(row["breach"]),
        )
        for _, row in df.iterrows()
    ]


@app.get(
    "/volatility",
    response_model=list[VolatilityItem],
    tags=["Analytics"],
    summary="Annualised volatility summary per metal",
)
def volatility(analyser=Depends(get_analyser)):
    """
    Returns 30-day rolling annualised volatility, 52-week high/low,
    and price range for each metal. Sorted most-to-least volatile.
    """
    results = analyser.volatility_summary()
    return [
        VolatilityItem(
            symbol          = v.symbol,
            metal           = v.metal,
            annualised_vol  = v.annualised_vol,
            high_52w        = v.high_52w,
            low_52w         = v.low_52w,
            price_range_pct = v.price_range_pct,
        )
        for v in results
    ]


@app.get(
    "/volatility/correlation",
    tags=["Analytics"],
    summary="Pearson correlation matrix of log returns",
)
def correlation(analyser=Depends(get_analyser)):
    """
    Returns the Pearson correlation matrix of daily log returns across metals.
    Cross-validated with scipy.stats.pearsonr.
    Useful for assessing portfolio diversification.
    """
    corr = analyser.correlation_matrix()
    return corr.to_dict()


@app.get(
    "/volatility/normality",
    response_model=list[NormalityItem],
    tags=["Analytics"],
    summary="Shapiro-Wilk normality tests on log returns (scipy)",
)
def normality(analyser=Depends(get_analyser)):
    """
    Tests whether each metal's log returns are normally distributed
    using scipy.stats.shapiro. Key assumption check for VaR models.
    p-value < 0.05 rejects normality at the 5% level.
    """
    df = analyser.normality_tests()
    return [
        NormalityItem(
            symbol         = row["symbol"],
            metal          = row["metal"],
            n_obs          = int(row["n_obs"]),
            shapiro_w      = row["shapiro_w"],
            p_value        = row["p_value"],
            normal_at_5pct = row["normal_at_5pct"],
        )
        for _, row in df.iterrows()
    ]


@app.get(
    "/trades/activity",
    tags=["Trades"],
    summary="Monthly trade activity by desk and direction",
)
def monthly_activity(analyser=Depends(get_analyser)):
    """
    Returns trade count, total notional, and average trade size
    aggregated by month, desk, and buy/sell direction.
    """
    df = analyser.monthly_activity()
    # Convert Period to string for JSON serialisation
    df["month"] = df["month"].astype(str)
    return df.to_dict(orient="records")


@app.get(
    "/trades/counterparties",
    tags=["Trades"],
    summary="Top N counterparties by gross exposure",
)
def counterparties(
    n: int = Query(default=5, ge=1, le=50, description="Number of counterparties to return"),
    analyser=Depends(get_analyser),
):
    """
    Returns the top N counterparties ranked by gross notional exposure.
    Used for credit risk monitoring.
    """
    df = analyser.top_counterparties(n)
    return df.to_dict(orient="records")


@app.post(
    "/refresh",
    response_model=RefreshResponse,
    tags=["System"],
    summary="Reload data from disk",
)
def refresh_data():
    """
    Forces a reload of all CSV data from disk into the analyser.
    Call this after running the ETL pipeline to pick up new data
    without restarting the service.
    """
    global _analyser_instance
    try:
        DataLoader, MetalsAnalyser = _get_analyser_module()
        loader = DataLoader(DATA_DIR)
        _analyser_instance = MetalsAnalyser(loader)
        rows = {k: len(v) for k, v in _analyser_instance._data.items()}
        return RefreshResponse(
            status  = "ok",
            message = f"Data reloaded from {DATA_DIR}",
            rows    = rows,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Refresh failed: {e}")

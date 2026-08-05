"""
=========================================================
Cu Shin Pro Signals Bot V2
config.py

Global configuration for the whole application.

Author : Cu Shin
Version: 2.0.0
=========================================================
"""

from dataclasses import dataclass, field
from typing import List, Dict
import os


# =========================================================
# Application
# =========================================================

@dataclass(frozen=True)
class AppConfig:
    NAME: str = "Cu Shin Pro Signals Bot"
    VERSION: str = "2.0.0"
    TIMEZONE: str = "Asia/Ho_Chi_Minh"
    DEBUG: bool = False
    REFRESH_SECONDS: int = 15


# =========================================================
# Binance
# =========================================================

@dataclass(frozen=True)
class BinanceConfig:
    FUTURES_URL: str = "https://fapi.binance.com"
    SPOT_URL: str = "https://api.binance.com"

    TOP_SYMBOLS: int = 100

    CANDLE_LIMIT: int = 300

    REQUEST_TIMEOUT: int = 10

    MAX_WORKERS: int = 12

    CACHE_SECONDS: int = 15

    INTERVALS: List[str] = field(default_factory=lambda: [
        "5m",
        "15m",
        "30m",
        "1h",
        "4h"
    ])


# =========================================================
# Risk Management
# =========================================================

@dataclass(frozen=True)
class RiskProfile:

    name: str

    risk_percent: float

    leverage: int

    max_dca: int


RISK_LEVELS: Dict[str, RiskProfile] = {

    "LOW": RiskProfile(
        "LOW",
        1.0,
        20,
        2
    ),

    "MEDIUM": RiskProfile(
        "MEDIUM",
        2.0,
        80,
        3
    ),

    "HIGH": RiskProfile(
        "HIGH",
        3.0,
        150,
        4
    ),

    "EXTREME": RiskProfile(
        "EXTREME",
        3.0,
        500,
        4
    )

}


# =========================================================
# Strategy
# =========================================================

@dataclass(frozen=True)
class StrategyConfig:

    SIGNAL_SCORE: int = 85

    EMA_FAST: int = 20

    EMA_MID: int = 50

    EMA_SLOW: int = 200

    RSI_PERIOD: int = 14

    RSI_LONG: int = 35

    RSI_SHORT: int = 65

    ATR_PERIOD: int = 14

    ADX_PERIOD: int = 14

    ADX_MIN: int = 25

    MACD_FAST: int = 12

    MACD_SLOW: int = 26

    MACD_SIGNAL: int = 9

    USE_BTC_FILTER: bool = True

    USE_VOLUME_FILTER: bool = True

    USE_FVG: bool = True

    USE_ORDER_BLOCK: bool = True

    USE_CHOCH: bool = True

    USE_BOS: bool = True


# =========================================================
# Position
# =========================================================

@dataclass(frozen=True)
class PositionConfig:

    TP_LEVELS: int = 3

    DCA_LEVELS: int = 3

    USE_DYNAMIC_SL: bool = True

    USE_DYNAMIC_TP: bool = True

    ATR_MULTIPLIER: float = 0.8


# =========================================================
# Firebase
# =========================================================

@dataclass(frozen=True)
class FirebaseConfig:

    ENABLED: bool = True

    COLLECTION: str = "signals"

    HISTORY_COLLECTION: str = "history"

    MAX_HISTORY: int = 500

    CREDENTIAL_FILE: str = os.getenv(
        "FIREBASE_CREDENTIALS",
        "firebase.json"
    )


# =========================================================
# Dashboard
# =========================================================

@dataclass(frozen=True)
class DashboardConfig:

    SHOW_SCORE: bool = True

    SHOW_CONFIDENCE: bool = True

    SHOW_BTC_TREND: bool = True

    SHOW_MARKET_STATUS: bool = True

    SHOW_HISTORY: bool = True

    SHOW_TOP_OPPORTUNITIES: bool = True

    AUTO_REFRESH: int = 5


# =========================================================
# Global Config Object
# =========================================================

APP = AppConfig()

BINANCE = BinanceConfig()

STRATEGY = StrategyConfig()

POSITION = PositionConfig()

FIREBASE = FirebaseConfig()

DASHBOARD = DashboardConfig()

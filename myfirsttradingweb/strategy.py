"""
=========================================================
Cu Shin Pro Signals Bot V2
strategy.py

Production Strategy Engine
Author: Cu Shin
=========================================================
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


# =========================================================
# Score Item
# =========================================================

@dataclass
class ScoreItem:

    name: str
    points: int
    passed: bool


# =========================================================
# Signal
# =========================================================

@dataclass
class Signal:

    symbol: str

    timeframe: str

    side: str

    score: int

    confidence: str

    quality: str

    risk: float

    leverage: int

    entry: float

    stop_loss: float

    take_profit: List[float]

    dca: List[float]

    reasons: List[str] = field(default_factory=list)


# =========================================================
# Score Engine
# =========================================================

class ScoreEngine:

    def __init__(self):

        self.items: List[ScoreItem] = []

    def add(self, name: str, points: int, passed: bool):

        self.items.append(
            ScoreItem(
                name=name,
                points=points if passed else 0,
                passed=passed
            )
        )

    @property
    def score(self):

        return sum(i.points for i in self.items)

    @property
    def reasons(self):

        return [i.name for i in self.items if i.passed]

    @property
    def confidence(self):

        s = self.score

        if s >= 95:
            return "Very High"

        if s >= 90:
            return "High"

        if s >= 80:
            return "Medium"

        return "Low"

    @property
    def quality(self):

        s = self.score

        if s >= 95:
            return "A+"

        if s >= 90:
            return "A"

        if s >= 85:
            return "B+"

        if s >= 80:
            return "B"

        return "C"


# =========================================================
# Trend Analyzer
# =========================================================

class TrendAnalyzer:

    @staticmethod
    def bullish(row):

        return (

            row["ema20"]

            >

            row["ema50"]

            >

            row["ema100"]

            >

            row["ema200"]

        )

    @staticmethod
    def bearish(row):

        return (

            row["ema20"]

            <

            row["ema50"]

            <

            row["ema100"]

            <

            row["ema200"]

        )

    @staticmethod
    def above_ema20(row):

        return row["close"] > row["ema20"]

    @staticmethod
    def above_ema50(row):

        return row["close"] > row["ema50"]

    @staticmethod
    def above_ema200(row):

        return row["close"] > row["ema200"]


# =========================================================
# Momentum Analyzer
# =========================================================

class MomentumAnalyzer:

    @staticmethod
    def bullish(row):

        return (

            row["macd"]

            >

            row["macd_signal"]

        )

    @staticmethod
    def bearish(row):

        return (

            row["macd"]

            <

            row["macd_signal"]

        )

    @staticmethod
    def healthy_rsi(row):

        return 45 <= row["rsi"] <= 65

    @staticmethod
    def strong_adx(row):

        return row["adx"] >= 25
        # =========================================================
# Volume Analyzer
# =========================================================

class VolumeAnalyzer:

    @staticmethod
    def spike(row):

        return row["volume"] > row["vol_ma20"] * 1.5

    @staticmethod
    def above_average(row):

        return row["volume"] > row["vol_ma20"]

    @staticmethod
    def relative_volume(row):

        if row["vol_ma20"] == 0:
            return 0

        return row["volume"] / row["vol_ma20"]


# =========================================================
# Volatility Analyzer
# =========================================================

class VolatilityAnalyzer:

    @staticmethod
    def atr_percent(row):

        if row["close"] == 0:
            return 0

        return (row["atr"] / row["close"]) * 100

    @staticmethod
    def healthy(row):

        value = VolatilityAnalyzer.atr_percent(row)

        return 0.4 <= value <= 4.5

    @staticmethod
    def leverage(row):

        atr = VolatilityAnalyzer.atr_percent(row)

        if atr >= 5:
            return 20

        if atr >= 4:
            return 30

        if atr >= 3:
            return 50

        if atr >= 2:
            return 75

        if atr >= 1:
            return 100

        return 125


# =========================================================
# BTC Analyzer
# =========================================================

class BTCAnalyzer:

    @staticmethod
    def score(trend):

        table = {
            "strong_bullish": 15,
            "bullish": 10,
            "neutral": 0,
            "bearish": -10,
            "strong_bearish": -15
        }

        return table.get(trend, 0)

    @staticmethod
    def allow_long(trend):

        return trend not in (
            "bearish",
            "strong_bearish"
        )

    @staticmethod
    def allow_short(trend):

        return trend not in (
            "bullish",
            "strong_bullish"
        )


# =========================================================
# Risk Engine
# =========================================================

class RiskEngine:

    @staticmethod
    def risk(score):

        if score >= 95:
            return 3.0

        if score >= 90:
            return 2.5

        if score >= 85:
            return 2.0

        return 1.0


# =========================================================
# DCA Engine
# =========================================================

class DCAEngine:

    @staticmethod
    def long(entry, atr):

        return [

            round(entry - atr * 0.8, 6),

            round(entry - atr * 1.6, 6),

            round(entry - atr * 2.4, 6)

        ]

    @staticmethod
    def short(entry, atr):

        return [

            round(entry + atr * 0.8, 6),

            round(entry + atr * 1.6, 6),

            round(entry + atr * 2.4, 6)

        ]


# =========================================================
# TP / SL Engine
# =========================================================

class TPSLEngine:

    @staticmethod
    def long(entry, atr):

        sl = round(entry - atr * 2, 6)

        tp = [

            round(entry + atr * 1.5, 6),

            round(entry + atr * 3, 6),

            round(entry + atr * 5, 6)

        ]

        return sl, tp

    @staticmethod
    def short(entry, atr):

        sl = round(entry + atr * 2, 6)

        tp = [

            round(entry - atr * 1.5, 6),

            round(entry - atr * 3, 6),

            round(entry - atr * 5, 6)

        ]

        return sl, tp


# =========================================================
# Market Regime
# =========================================================

class MarketRegime:

    @staticmethod
    def detect(row):

        atr = VolatilityAnalyzer.atr_percent(row)

        adx = row["adx"]

        if adx >= 30:

            return "TRENDING"

        if atr >= 4:

            return "VOLATILE"

        if adx <= 18:

            return "SIDEWAY"

        return "NORMAL"
        # =========================================================
# Strategy Engine
# =========================================================

class StrategyEngine:

    def __init__(self):

        self.minimum_score = 85

    # =====================================================

    def build_long_score(
        self,
        row,
        btc_trend="neutral"
    ):

        score = ScoreEngine()

        # ================= Trend =================

        score.add(
            "EMA Bullish",
            20,
            TrendAnalyzer.bullish(row)
        )

        score.add(
            "Price Above EMA20",
            5,
            TrendAnalyzer.above_ema20(row)
        )

        score.add(
            "Price Above EMA50",
            5,
            TrendAnalyzer.above_ema50(row)
        )

        score.add(
            "Price Above EMA200",
            5,
            TrendAnalyzer.above_ema200(row)
        )

        # ================= Momentum =================

        score.add(
            "Healthy RSI",
            10,
            MomentumAnalyzer.healthy_rsi(row)
        )

        score.add(
            "MACD Bullish",
            10,
            MomentumAnalyzer.bullish(row)
        )

        score.add(
            "Strong ADX",
            15,
            MomentumAnalyzer.strong_adx(row)
        )

        # ================= Volume =================

        score.add(
            "Volume Above Average",
            5,
            VolumeAnalyzer.above_average(row)
        )

        score.add(
            "Volume Spike",
            10,
            VolumeAnalyzer.spike(row)
        )

        # ================= ATR =================

        score.add(
            "Healthy ATR",
            10,
            VolatilityAnalyzer.healthy(row)
        )

        # ================= BTC =================

        btc_score = BTCAnalyzer.score(
            btc_trend
        )

        if btc_score > 0:

            score.add(
                "BTC Trend",
                btc_score,
                True
            )

        return score

    # =====================================================

    def build_short_score(
        self,
        row,
        btc_trend="neutral"
    ):

        score = ScoreEngine()

        score.add(
            "EMA Bearish",
            20,
            TrendAnalyzer.bearish(row)
        )

        score.add(
            "MACD Bearish",
            10,
            MomentumAnalyzer.bearish(row)
        )

        score.add(
            "Healthy RSI",
            10,
            MomentumAnalyzer.healthy_rsi(row)
        )

        score.add(
            "Strong ADX",
            15,
            MomentumAnalyzer.strong_adx(row)
        )

        score.add(
            "Volume Above Average",
            5,
            VolumeAnalyzer.above_average(row)
        )

        score.add(
            "Volume Spike",
            10,
            VolumeAnalyzer.spike(row)
        )

        score.add(
            "Healthy ATR",
            10,
            VolatilityAnalyzer.healthy(row)
        )

        if btc_trend in (
            "bearish",
            "strong_bearish"
        ):

            score.add(
                "BTC Bearish",
                10,
                True
            )

        return score

    # =====================================================

    def generate_long(

        self,

        symbol,

        timeframe,

        row,

        btc_trend="neutral"

    ):

        if not BTCAnalyzer.allow_long(
            btc_trend
        ):
            return None

        score = self.build_long_score(
            row,
            btc_trend
        )

        if score.score < self.minimum_score:
            return None

        entry = row["close"]

        sl, tp = TPSLEngine.long(
            entry,
            row["atr"]
        )

        dca = DCAEngine.long(
            entry,
            row["atr"]
        )

        return Signal(

            symbol=symbol,

            timeframe=timeframe,

            side="LONG",

            score=score.score,

            confidence=score.confidence,

            quality=score.quality,

            risk=RiskEngine.risk(
                score.score
            ),

            leverage=VolatilityAnalyzer.leverage(
                row
            ),

            entry=entry,

            stop_loss=sl,

            take_profit=tp,

            dca=dca,

            reasons=score.reasons

        )

    # =====================================================

    def generate_short(

        self,

        symbol,

        timeframe,

        row,

        btc_trend="neutral"

    ):

        if not BTCAnalyzer.allow_short(
            btc_trend
        ):
            return None

        score = self.build_short_score(
            row,
            btc_trend
        )

        if score.score < self.minimum_score:
            return None

        entry = row["close"]

        sl, tp = TPSLEngine.short(
            entry,
            row["atr"]
        )

        dca = DCAEngine.short(
            entry,
            row["atr"]
        )

        return Signal(

            symbol=symbol,

            timeframe=timeframe,

            side="SHORT",

            score=score.score,

            confidence=score.confidence,

            quality=score.quality,

            risk=RiskEngine.risk(
                score.score
            ),

            leverage=VolatilityAnalyzer.leverage(
                row
            ),

            entry=entry,

            stop_loss=sl,

            take_profit=tp,

            dca=dca,

            reasons=score.reasons

        )
        # =========================================================
# Signal Builder
# =========================================================

from datetime import datetime
from zoneinfo import ZoneInfo


class SignalBuilder:

    @staticmethod
    def vn_time():

        return datetime.now(
            ZoneInfo("Asia/Ho_Chi_Minh")
        ).strftime("%d/%m/%Y %H:%M:%S")

    @staticmethod
    def market_status(row):

        regime = MarketRegime.detect(row)

        if regime == "TRENDING":
            return "Trending"

        if regime == "VOLATILE":
            return "Volatile"

        if regime == "SIDEWAY":
            return "Sideway"

        return "Normal"

    @staticmethod
    def build(signal, row):

        return {

            "symbol": signal.symbol,

            "side": signal.side,

            "timeframe": signal.timeframe,

            "score": signal.score,

            "confidence": signal.confidence,

            "quality": signal.quality,

            "entry": signal.entry,

            "dca": signal.dca,

            "stop_loss": signal.stop_loss,

            "take_profit": signal.take_profit,

            "risk": signal.risk,

            "leverage": signal.leverage,

            "market": SignalBuilder.market_status(
                row
            ),

            "time": SignalBuilder.vn_time(),

            "reasons": signal.reasons

        }


# =========================================================
# Best Timeframe Selector
# =========================================================

class TimeframeSelector:

    @staticmethod
    def choose(signals):

        """
        signals = list[Signal]
        """

        if len(signals) == 0:
            return None

        signals = sorted(

            signals,

            key=lambda x: x.score,

            reverse=True

        )

        return signals[0]


# =========================================================
# Coin Ranking
# =========================================================

class CoinRanking:

    def __init__(self):

        self.coins = []

    def add(

        self,

        symbol,

        timeframe,

        score,

        confidence,

        quality

    ):

        self.coins.append({

            "symbol": symbol,

            "timeframe": timeframe,

            "score": score,

            "confidence": confidence,

            "quality": quality

        })

    def top(self, limit=10):

        return sorted(

            self.coins,

            key=lambda x: x["score"],

            reverse=True

        )[:limit]


# =========================================================
# Scanner Result
# =========================================================

class ScannerResult:

    def __init__(self):

        self.signals = []

        self.ranking = CoinRanking()

    def add_signal(

        self,

        signal

    ):

        self.signals.append(signal)

        self.ranking.add(

            signal.symbol,

            signal.timeframe,

            signal.score,

            signal.confidence,

            signal.quality

        )

    def best(self):

        return TimeframeSelector.choose(
            self.signals
        )

    def leaderboard(self):

        return self.ranking.top(10)
        # =========================================================
# Position Engine
# =========================================================

from dataclasses import dataclass


@dataclass
class Position:

    entry: float

    average_entry: float

    dca_levels: list

    stop_loss: float

    take_profit: list

    leverage: int

    risk_percent: float

    position_size: float

    rr: float


class PositionEngine:

    @staticmethod
    def calculate_position_size(

        balance: float,

        risk_percent: float,

        entry: float,

        stop_loss: float,

        leverage: int

    ):

        risk_money = balance * (risk_percent / 100)

        distance = abs(entry - stop_loss)

        if distance <= 0:
            return 0

        qty = (risk_money / distance) * leverage

        return round(qty, 4)

    # =====================================================

    @staticmethod
    def average_price(entries):

        return round(

            sum(entries) / len(entries),

            6

        )

    # =====================================================

    @staticmethod
    def reward(entry, tp):

        return abs(tp - entry)

    # =====================================================

    @staticmethod
    def risk(entry, sl):

        return abs(entry - sl)

    # =====================================================

    @staticmethod
    def rr(entry, sl, tp):

        r = PositionEngine.risk(entry, sl)

        if r == 0:
            return 0

        return round(

            PositionEngine.reward(entry, tp) / r,

            2

        )

    # =====================================================

    @staticmethod
    def build(

        balance,

        signal

    ):

        entries = [

            signal.entry,

            *signal.dca

        ]

        avg = PositionEngine.average_price(

            entries

        )

        sl = signal.stop_loss

        tp = signal.take_profit

        size = PositionEngine.calculate_position_size(

            balance,

            signal.risk,

            avg,

            sl,

            signal.leverage

        )

        rr = PositionEngine.rr(

            avg,

            sl,

            tp[0]

        )

        return Position(

            entry=signal.entry,

            average_entry=avg,

            dca_levels=signal.dca,

            stop_loss=sl,

            take_profit=tp,

            leverage=signal.leverage,

            risk_percent=signal.risk,

            position_size=size,

            rr=rr

        )

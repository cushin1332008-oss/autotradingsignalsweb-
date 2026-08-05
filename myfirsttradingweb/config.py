from dataclasses import dataclass
import os

@dataclass
class Config:

    APP_NAME = "Cu Shin Pro Signals Bot"

    TIMEZONE = "Asia/Ho_Chi_Minh"

    BINANCE_SPOT = "https://api.binance.com"

    BINANCE_FUTURES = "https://fapi.binance.com"

    SCAN_INTERVAL = 15

    TOP_SYMBOLS = 100

    CANDLE_LIMIT = 300

    MAX_THREADS = 12

    FIREBASE_CREDENTIAL = os.getenv("FIREBASE_CREDENTIALS")

    TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

    TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT_ID")

    RISK_LEVELS = {

        "LOW":1,

        "MEDIUM":2,

        "HIGH":3

    }

    LEVERAGE={

        "LOW":20,

        "MEDIUM":80,

        "HIGH":500

    }

config=Config()

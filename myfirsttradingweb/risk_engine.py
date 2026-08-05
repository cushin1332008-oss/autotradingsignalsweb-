from dataclasses import dataclass


@dataclass
class RiskProfile:
    risk_percent: float
    leverage: int
    max_positions: int
    confidence: str


class RiskEngine:

    @staticmethod
    def get_profile(score: int, atr_percent: float) -> RiskProfile:

        # Risk theo điểm tín hiệu
        if score >= 95:
            risk = 3.0
            confidence = "Very High"
        elif score >= 90:
            risk = 2.5
            confidence = "High"
        elif score >= 85:
            risk = 2.0
            confidence = "Medium"
        else:
            risk = 1.0
            confidence = "Low"

        # Leverage theo ATR
        if atr_percent >= 5:
            leverage = 20
        elif atr_percent >= 4:
            leverage = 30
        elif atr_percent >= 3:
            leverage = 50
        elif atr_percent >= 2:
            leverage = 75
        elif atr_percent >= 1:
            leverage = 100
        else:
            leverage = 125

        # Giới hạn đúng yêu cầu 20–500x
        leverage = max(20, min(500, leverage))

        return RiskProfile(
            risk_percent=risk,
            leverage=leverage,
            max_positions=3,
            confidence=confidence,
        )

    @staticmethod
    def position_size(balance, risk_percent):

        return balance * risk_percent / 100

    @staticmethod
    def calc_rr(entry, stop_loss, take_profit):

        risk = abs(entry - stop_loss)

        reward = abs(take_profit - entry)

        if risk == 0:
            return 0

        return round(reward / risk, 2)

    @staticmethod
    def move_sl_to_average(avg_entry, side, atr):

        if side == "LONG":
            return round(avg_entry - atr * 2, 6)

        return round(avg_entry + atr * 2, 6)

    @staticmethod
    def update_tp(avg_entry, side, atr):

        if side == "LONG":

            return [

                round(avg_entry + atr * 1.5, 6),

                round(avg_entry + atr * 3, 6),

                round(avg_entry + atr * 5, 6),

            ]

        return [

            round(avg_entry - atr * 1.5, 6),

            round(avg_entry - atr * 3, 6),

            round(avg_entry - atr * 5, 6),

        ]

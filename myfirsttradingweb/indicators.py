def calc_position_sizing(entry_1, stop_loss, confluence_pct, profile_key, account_balance=1000.0, leverage=None):
    """
    Tính toán Volume, Margin và Risk cố định từ 1% - 3% tài khoản.
    Đòn bẩy linh hoạt từ 20x đến 500x.
    """
    # 1. Xác định % Risk (1% - 3%) dựa trên độ tin cậy tín hiệu
    if confluence_pct >= 85:
        risk_pct = 3.0  # Tín hiệu đẹp, R:R cao -> Risk 3%
    elif confluence_pct >= 70:
        risk_pct = 2.0  # Tín hiệu trung bình khá -> Risk 2%
    else:
        risk_pct = 1.0  # Tín hiệu đạt chuẩn tối thiểu -> Risk 1%

    # 2. Xác định đòn bẩy (Mặc định 20x - 500x theo Chiến lược)
    if leverage is None:
        default_leverage_map = {
            "SCALP": 50,     # Lướt nhanh M15: Bẩy 50x - 100x
            "SWING": 30,     # Khung H1: Bẩy 30x - 50x
            "POSITION": 20,  # Khung H4: Bẩy 20x
        }
        leverage = default_leverage_map.get(profile_key, 20)

    # Khống chế trần/sàn đòn bẩy từ 20x đến 500x
    leverage = max(20, min(int(leverage), 500))

    # 3. Tính % khoảng cách đến SL từ Entry 1
    sl_dist_pct = abs(entry_1 - stop_loss) / entry_1

    if sl_dist_pct == 0:
        return {}

    # 4. Tính Tổng Giá Trị Vị Thế (Notional Value) & Margin cần ký quỹ
    # Risk_Amount = Notional_Value * sl_dist_pct  =>  Notional_Value = Risk_Amount / sl_dist_pct
    risk_usdt = account_balance * (risk_pct / 100.0)
    notional_usdt = risk_usdt / sl_dist_pct
    margin_usdt = notional_usdt / leverage
    margin_pct = (margin_usdt / account_balance) * 100.0

    return {
        "risk_pct": risk_pct,
        "risk_usdt": round(risk_usdt, 2),
        "leverage": leverage,
        "margin_usdt": round(margin_usdt, 2),
        "margin_pct": round(margin_pct, 2),
        "position_size_usdt": round(notional_usdt, 2)
    }

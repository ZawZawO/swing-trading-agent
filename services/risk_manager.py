"""
Risk Manager Service
====================
Calculates trade levels and position sizing using ATR-based methodology.

Defaults:
  Account capital : £300
  Risk per trade  : 3% = £9
  Stop loss       : Entry − ATR × 1.5
  Target          : Entry + (Entry − Stop) × 2  (2:1 R:R minimum)
"""


def calc_trade_levels(
    price: float,
    atr: float,
    account_size: float = 300.0,
    risk_percent: float = 3.0,
) -> dict:
    """
    Calculate entry, stop loss, target, risk/reward, and position size.

    Returns dict with:
      entry, stop_loss, target, risk_per_share, reward_per_share,
      rr_ratio, risk_amount, shares, position_value
    """
    if atr <= 0 or price <= 0:
        # Fallback: 5% stop, 10% target
        stop_loss = round(price * 0.95, 2)
        target = round(price * 1.10, 2)
    else:
        stop_loss = round(price - atr * 1.5, 2)
        # Ensure stop is at least 1% below entry
        stop_loss = min(stop_loss, round(price * 0.99, 2))
        stop_loss = max(stop_loss, 0.01)
        target = round(price + (price - stop_loss) * 2, 2)

    risk_per_share = round(price - stop_loss, 4)
    reward_per_share = round(target - price, 4)

    rr_ratio = round(reward_per_share / risk_per_share, 2) if risk_per_share > 0 else 0.0

    risk_amount = round(account_size * (risk_percent / 100), 2)  # £9 by default

    if risk_per_share > 0:
        shares = int(risk_amount / risk_per_share)
    else:
        shares = 0

    position_value = round(shares * price, 2)

    return {
        "entry": round(price, 2),
        "stop_loss": stop_loss,
        "target": target,
        "risk_per_share": risk_per_share,
        "reward_per_share": reward_per_share,
        "rr_ratio": rr_ratio,
        "risk_amount": risk_amount,
        "shares": shares,
        "position_value": position_value,
    }


def calc_position_from_levels(
    entry: float,
    stop: float,
    account_size: float = 300.0,
    risk_percent: float = 3.0,
) -> dict:
    """Calculate position size given custom entry/stop levels."""
    risk_amount = round(account_size * (risk_percent / 100), 2)
    risk_per_share = round(entry - stop, 4)
    if risk_per_share <= 0:
        return {"shares": 0, "risk_amount": risk_amount, "position_value": 0.0}
    shares = int(risk_amount / risk_per_share)
    return {
        "shares": shares,
        "risk_amount": risk_amount,
        "risk_per_share": risk_per_share,
        "position_value": round(shares * entry, 2),
    }

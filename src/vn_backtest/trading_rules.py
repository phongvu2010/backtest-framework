import pandas as pd
import numpy as np
from typing import Dict

class TradingRulesManager:
    """
    Helper class to convert Vietnamese exchange rules into tick sizes, lot sizes,
    price limits, and settlement periods.
    """
    def __init__(
        self,
        dynamic_rules: bool = True,
        default_lot_size: int = 100,
        default_allow_odd_lot: bool = False,
        exchanges: Dict[str, str] = None,
        raw_listing_dates: Dict[str, pd.Timestamp] = None
    ):
        self.dynamic_rules = dynamic_rules
        self.default_lot_size = default_lot_size
        self.default_allow_odd_lot = default_allow_odd_lot
        self.exchanges = exchanges or {}
        self.raw_listing_dates = raw_listing_dates or {}

    def get_tick_size(
        self, price: float, exchange: str, current_time: pd.Timestamp = None
    ) -> float:
        price = float(price)
        if exchange == "hose":
            if (
                self.dynamic_rules
                and current_time is not None
                and current_time < pd.Timestamp("2016-09-12")
            ):
                # HOSE rules before 12/09/2016
                if price < 50000.0:
                    return 100.0
                elif price < 100000.0:
                    return 500.0
                else:
                    return 1000.0
            else:
                # HOSE rules from 12/09/2016 onwards
                if price < 10000.0:
                    return 10.0
                elif price < 50000.0:
                    return 50.0
                else:
                    return 100.0
        else:
            # HNX and UPCOM use 100 VND tick size for all stocks
            return 100.0

    def round_to_tick(
        self,
        price: float,
        exchange: str,
        direction: str,
        current_time: pd.Timestamp = None,
    ) -> float:
        price = float(price)
        tick = self.get_tick_size(price, exchange, current_time)

        if direction == "down":  # Ceiling
            return (price // tick) * tick
        elif direction == "up":  # Floor
            return np.ceil(price / tick) * tick
        else:
            return round(price / tick) * tick

    def check_price_limits(
        self,
        price: float,
        prev_close: float,
        exchange: str,
        price_limit: float,
        current_time: pd.Timestamp = None,
    ) -> tuple[float, float, bool, bool]:
        if prev_close is None or price_limit == 0.0:
            return float("inf"), 0.0, False, False

        raw_ceiling = prev_close * (1 + price_limit)
        raw_floor = prev_close * (1 - price_limit)

        ceiling = self.round_to_tick(raw_ceiling, exchange, "down", current_time)
        floor = self.round_to_tick(raw_floor, exchange, "up", current_time)

        is_ceiling = price >= ceiling
        is_floor = price <= floor

        return ceiling, floor, is_ceiling, is_floor

    def get_lot_size(self, ticker: str, current_time: pd.Timestamp) -> int:
        if not self.dynamic_rules:
            return self.default_lot_size

        exch = self.exchanges.get(ticker, "hose")
        if exch == "hose":
            if current_time < pd.Timestamp("2021-01-04"):
                return 10
            else:
                return 100
        else:
            return 100

    def is_odd_lot_allowed(self, ticker: str, current_time: pd.Timestamp) -> bool:
        if not self.dynamic_rules:
            return self.default_allow_odd_lot
        exch = self.exchanges.get(ticker, "hose")
        if exch == "hose":
            return current_time >= pd.Timestamp("2022-09-12")
        return True

    def get_price_limit(self, ticker: str, current_time: pd.Timestamp) -> float:
        exch = self.exchanges.get(ticker, "hose")

        # Check if today is the listing day
        is_listing_day = False
        if ticker in self.raw_listing_dates:
            if current_time.normalize() == self.raw_listing_dates[ticker].normalize():
                is_listing_day = True

        if is_listing_day:
            if exch == "hose":
                return 0.20
              # HNX
            elif exch == "hnx":
                return 0.30
              # UPCOM
            elif exch == "upcom":
                return 0.40
            return 0.0

        # Normal trading day - historical limits
        if exch == "hose":
            if current_time < pd.Timestamp("2000-08-24"):
                return 0.02
            elif current_time < pd.Timestamp("2001-06-13"):
                return 0.05
            elif current_time < pd.Timestamp("2002-08-01"):
                return 0.02
            elif current_time < pd.Timestamp("2003-01-02"):
                return 0.03
            elif current_time < pd.Timestamp("2008-03-27"):
                return 0.05
            elif current_time < pd.Timestamp("2008-04-07"):
                return 0.01
            elif current_time < pd.Timestamp("2008-06-19"):
                return 0.02
            elif current_time < pd.Timestamp("2008-08-18"):
                return 0.03
            elif current_time < pd.Timestamp("2013-01-15"):
                return 0.05
            else:
                return 0.07
        elif exch == "hnx":
            if current_time < pd.Timestamp("2008-03-27"):
                return 0.10
            elif current_time < pd.Timestamp("2008-04-07"):
                return 0.02
            elif current_time < pd.Timestamp("2008-06-19"):
                return 0.03
            elif current_time < pd.Timestamp("2008-08-18"):
                return 0.05
            elif current_time < pd.Timestamp("2013-01-15"):
                return 0.07
            else:
                return 0.10
        elif exch == "upcom":
            if current_time < pd.Timestamp("2015-07-01"):
                return 0.10
            else:
                return 0.15
        return 0.0

    def apply_dynamic_rules(self, current_time: pd.Timestamp, execution_at: str) -> int:
        # Quy tắc chu kỳ thanh toán lịch sử Việt Nam:
        if current_time < pd.Timestamp("2016-01-01"):
            return 4  # Settle cuối ngày T+3 -> Giao dịch từ T+4
        elif current_time < pd.Timestamp("2022-08-29"):
            return 3  # Settle cuối ngày T+2 -> Giao dịch từ T+3
        else:  # Từ 29/08/2022 (T+1.5)
            if execution_at == "close":
                return 2  # Settle 13:00 T+2 -> Giao dịch được Close T+2
            else:
                return 3  # Giao dịch được Open T+3

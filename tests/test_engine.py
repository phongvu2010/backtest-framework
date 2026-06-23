import pytest
import pandas as pd
import numpy as np
from vn_backtest.engine import BacktestEngine
from vn_backtest.strategy import Strategy


# 1. Strategy that triggers Look-Ahead Bias (looks into the future via negative shift)
class FutureLookerStrategy(Strategy):
    def init(self):
        # looks forward 1 bar (looks at tomorrow's Close)
        self.future_close = self.I(lambda df: df["Close"].shift(-1), name="FutureClose")

    def next(self):
        pass


def test_lookahead_bias_static_detection():
    # Needs at least 100 periods to trigger lookahead check past default warmup threshold
    dates = pd.date_range(start="2023-01-01", periods=100, freq="D")
    stock_df = pd.DataFrame(
        {
            "Open": [50000.0] * 100,
            "High": [51000.0] * 100,
            "Low": [49000.0] * 100,
            "Close": [50000.0 + i * 100 for i in range(100)],  # changing prices
            "Volume": [100000] * 100,
        },
        index=dates,
    )

    # Initialize engine, registering FutureLookerStrategy.
    # It should trigger a UserWarning about look-ahead bias during initialization.
    engine = BacktestEngine(
        data={"FPT": stock_df},
        strategy_class=FutureLookerStrategy,
        initial_cash=100_000_000.0,
        check_lookahead=True,
    )

    with pytest.warns(UserWarning, match="CẢNH BÁO LOOK-AHEAD BIAS"):
        engine.run()


# 2. Strategy that places ATO / ATC orders and tests execution prices
class AuctionOrderStrategy(Strategy):
    def init(self):
        pass

    def next(self):
        if self.current_idx == 0:
            self.buy("FPT", size=10, order_type="ATO")
        elif self.current_idx == 1:
            self.sell("FPT", size=10, order_type="ATC")


def test_ato_atc_execution_prices():
    dates = pd.date_range(start="2023-01-01", periods=5, freq="D")
    # Day 1: O=50000, C=52000
    # Day 2: O=55000, C=57000
    # Day 3: O=52000, C=53000
    stock_df = pd.DataFrame(
        {
            "Open": [50000.0, 55000.0, 52000.0, 52000.0, 52000.0],
            "High": [51000.0, 56000.0, 53000.0, 53000.0, 53000.0],
            "Low": [49000.0, 54000.0, 51000.0, 51000.0, 51000.0],
            "Close": [52000.0, 57000.0, 53000.0, 53000.0, 53000.0],
            "Volume": [100000] * 5,
        },
        index=dates,
    )

    engine = BacktestEngine(
        data={"FPT": stock_df},
        strategy_class=AuctionOrderStrategy,
        initial_cash=100_000_000.0,
        buy_fee=0.0,
        sell_fee=0.0,
        sell_tax=0.0,
        lot_size=1,
        allow_odd_lot=True,
    )

    results = engine.run()
    trades = results["trades"]

    # Order ATO placed on day 1 (idx 0) executes on day 2 (idx 1) Open = 55000.0
    # Order ATC placed on day 2 (idx 1) executes on day 3 (idx 2) Close = 53000.0
    buy_trade = trades[trades["Action"] == "BUY"].iloc[0]
    assert buy_trade["Price"] == 55000.0

    sell_trade = trades[trades["Action"] == "SELL"].iloc[0]
    assert sell_trade["Price"] == 53000.0

import pytest
import pandas as pd
from vn_backtest.engine import BacktestEngine
from vn_backtest.strategy import Strategy


class BuyMaxStrategy(Strategy):
    def init(self):
        pass

    def next(self):
        # Place a buy order allocating 100% of available cash on day 1 (index 0)
        # Using margin (margin_ratio=0.5 allows buying up to 2x equity)
        if self.current_idx == 0:
            # Sized in engine to use max leverage
            self.buy("FPT")


def test_margin_interest_accumulation():
    dates = pd.date_range(start="2023-01-01", periods=10, freq="D")
    stock_df = pd.DataFrame(
        {
            "Open": [100000.0] * 10,
            "High": [100000.0] * 10,
            "Low": [100000.0] * 10,
            "Close": [100000.0] * 10,
            "Volume": [100000] * 10,
        },
        index=dates,
    )

    # Cash = 10,000,000. Sized buy order at margin_ratio = 0.5 allows buying 20,000,000 worth of shares (200 shares)
    # This leaves Cash = -10,000,000 (ignoring fees).
    engine = BacktestEngine(
        data={"FPT": stock_df},
        strategy_class=BuyMaxStrategy,
        initial_cash=10_000_000.0,
        margin_ratio=0.5,
        margin_interest_rate=0.10,  # 10% p.a.
        buy_fee=0.0,
        sell_fee=0.0,
        sell_tax=0.0,
        lot_size=1,
        allow_odd_lot=True,
    )

    results = engine.run()
    
    # Check that margin interest has been charged
    trades = results["trades"]
    interest_records = trades[trades["Action"] == "MARGIN_INTEREST"]
    assert len(interest_records) > 0
    # Interest per day = 10,000,000 * 0.10 / 365 = ~2739 VND
    assert interest_records.iloc[0]["Value"] > 0


def test_margin_call_and_force_sell():
    dates = pd.date_range(start="2023-01-01", periods=5, freq="D")
    # Price drops dramatically to trigger margin call
    # Day 1: 100000
    # Day 2: 100000 (execution day for the buy order placed on day 1)
    # Day 3: 60000 (price drop)
    stock_df = pd.DataFrame(
        {
            "Open": [100000.0, 100000.0, 60000.0, 60000.0, 60000.0],
            "High": [100000.0, 100000.0, 60000.0, 60000.0, 60000.0],
            "Low": [100000.0, 100000.0, 60000.0, 60000.0, 60000.0],
            "Close": [100000.0, 100000.0, 60000.0, 60000.0, 60000.0],
            "Volume": [100000] * 5,
        },
        index=dates,
    )

    # Cash = 10,000,000. Sized buy order at margin_ratio = 0.5 buys 20,000,000 (200 shares)
    # Cash becomes -10,000,000
    # On day 3, close price drops to 60000. Positions value = 200 * 60000 = 12,000,000.
    # Equity = 12,000,000 - 10,000,000 = 2,000,000.
    # Equity ratio = 2,000,000 / 12,000,000 = 16.67% < margin_maintenance_ratio (35%)
    # This should trigger a Margin Call & Force Sell
    engine = BacktestEngine(
        data={"FPT": stock_df},
        strategy_class=BuyMaxStrategy,
        initial_cash=10_000_000.0,
        margin_ratio=0.5,
        margin_maintenance_ratio=0.35,
        buy_fee=0.0,
        sell_fee=0.0,
        sell_tax=0.0,
        lot_size=1,
        allow_odd_lot=True,
    )

    results = engine.run()
    order_logs = results["order_logs"]
    
    # Check for MARGIN_CALL log
    margin_calls = order_logs[order_logs["Action"] == "MARGIN_CALL"]
    assert len(margin_calls) > 0
    
    # Check that sell orders were executed
    trades = results["trades"]
    sells = trades[trades["Action"] == "SELL"]
    assert len(sells) > 0

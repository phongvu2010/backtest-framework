import pytest
import pandas as pd
from vn_backtest.engine import BacktestEngine
from vn_backtest.strategy import Strategy


class HoldStrategy(Strategy):
    def init(self):
        pass

    def next(self):
        # Buy on day 1 (index 0)
        if self.current_idx == 0:
            self.buy("FPT", size=100)  # Buy 100 shares


def test_cash_dividend():
    # Setup stock data: 20 days
    dates = pd.date_range(start="2023-01-01", periods=20, freq="D")
    stock_df = pd.DataFrame(
        {
            "Open": [50000.0] * 20,
            "High": [51000.0] * 20,
            "Low": [49000.0] * 20,
            "Close": [50000.0] * 20,
            "Volume": [100000] * 20,
        },
        index=dates,
    )

    # Cash dividend: 2000 VND per share, ex-date is day 5 (index 4), payout-date is day 12 (index 11)
    corp_df = pd.DataFrame(
        {
            "exright_date": [dates[4]],
            "value_per_share": [2000.0],
            "exercise_ratio": [0.0],
            "event_name_vi": ["Cổ tức bằng tiền mặt"],
            "payout_date": [dates[11]],
        }
    )

    engine = BacktestEngine(
        data={"FPT": stock_df},
        strategy_class=HoldStrategy,
        corporate_actions={"FPT": corp_df},
        initial_cash=10_000_000.0,
        price_scale=1.0,
        lot_size=10,
        exchange="hose",
        adjust_corporate_actions=True,
        dividend_tax_rate=0.05,  # 5% tax
    )

    results = engine.run()
    trades = results["trades"]

    # FPT bought 100 shares. Dividend: 100 * 2000 = 200,000 VND
    # Tax: 5% * 200k = 10,000 VND
    # Net Dividend paid: 190,000 VND on day 12 (index 11)
    div_trades = trades[trades["Action"] == "DIVIDEND_CASH"]
    assert len(div_trades) == 1
    assert div_trades.iloc[0]["Value"] == 200000.0
    assert div_trades.iloc[0]["Tax"] == 10000.0
    assert div_trades.iloc[0]["TotalValue"] == 190000.0


def test_stock_dividend():
    dates = pd.date_range(start="2023-01-01", periods=100, freq="D")
    stock_df = pd.DataFrame(
        {
            "Open": [50000.0] * 100,
            "High": [51000.0] * 100,
            "Low": [49000.0] * 100,
            "Close": [50000.0] * 100,
            "Volume": [100000] * 100,
        },
        index=dates,
    )

    # Stock dividend: 10% (ratio 0.1), ex-date is day 5, payout-date (listing date) is day 50 (index 49)
    corp_df = pd.DataFrame(
        {
            "exright_date": [dates[4]],
            "value_per_share": [0.0],
            "exercise_ratio": [0.1],
            "event_name_vi": ["Cổ tức bằng cổ phiếu"],
            "payout_date": [dates[49]],
        }
    )

    engine = BacktestEngine(
        data={"FPT": stock_df},
        strategy_class=HoldStrategy,
        corporate_actions={"FPT": corp_df},
        initial_cash=10_000_000.0,
        price_scale=1.0,
        lot_size=10,
        exchange="hose",
        adjust_corporate_actions=True,
        rights_listing_delay=45,
    )

    results = engine.run()
    trades = results["trades"]

    # 100 shares * 0.1 = 10 dividend shares
    stock_div_trades = trades[trades["Action"] == "DIVIDEND_STOCK"]
    assert len(stock_div_trades) == 1
    assert stock_div_trades.iloc[0]["Quantity"] == 10

    # Auto-liquidation sell trade on the last day should have quantity 110 (100 bought + 10 dividend)
    sell_trades = trades[trades["Action"] == "SELL"]
    assert len(sell_trades) == 1
    assert sell_trades.iloc[0]["Quantity"] == 110

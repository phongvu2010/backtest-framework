import pytest
import pandas as pd
from vn_backtest.trading_rules import TradingRulesManager


def test_tick_size_hose_historical():
    # Before 2016-09-12 rules:
    # < 50k: tick 100
    # < 100k: tick 500
    # >= 100k: tick 1000
    rules = TradingRulesManager(dynamic_rules=True, price_scale=1.0)
    t_before = pd.Timestamp("2016-09-11")

    assert rules.get_tick_size(49000.0, "hose", t_before) == 100.0
    assert rules.get_tick_size(80000.0, "hose", t_before) == 500.0
    assert rules.get_tick_size(120000.0, "hose", t_before) == 1000.0


def test_tick_size_hose_modern():
    # Modern rules (>= 2016-09-12):
    # < 10k: tick 10
    # < 50k: tick 50
    # >= 50k: tick 100
    rules = TradingRulesManager(dynamic_rules=True, price_scale=1.0)
    t_after = pd.Timestamp("2016-09-12")

    assert rules.get_tick_size(9900.0, "hose", t_after) == 10.0
    assert rules.get_tick_size(25000.0, "hose", t_after) == 50.0
    assert rules.get_tick_size(85000.0, "hose", t_after) == 100.0


def test_tick_size_hnx_upcom():
    rules = TradingRulesManager(dynamic_rules=True, price_scale=1.0)
    assert rules.get_tick_size(50000.0, "hnx") == 100.0
    assert rules.get_tick_size(5000.0, "upcom") == 100.0


def test_price_scale_tick_size():
    # With price_scale=1000.0 (e.g. FPT price input is 85.5 instead of 85500.0)
    rules = TradingRulesManager(dynamic_rules=True, price_scale=1000.0)
    t_after = pd.Timestamp("2020-01-01")

    # price = 85.5 => actual price in VND is 85,500.0 (>= 50,000) => tick in VND is 100.0 => returned tick is 0.1
    assert rules.get_tick_size(85.5, "hose", t_after) == 0.1


def test_price_limits():
    rules = TradingRulesManager(dynamic_rules=True, price_scale=1.0)
    t_date = pd.Timestamp("2020-01-01")

    # HOSE limit is 7%
    limit = rules.get_price_limit("FPT", t_date)
    assert limit == 0.07

    # prev_close = 100000.0, limit = 7% => ceiling = 107000.0, floor = 93000.0
    ceiling, floor, is_ceiling, is_floor = rules.check_price_limits(
        price=107000.0, prev_close=100000.0, exchange="hose", price_limit=limit, current_time=t_date
    )
    assert ceiling == 107000.0
    assert floor == 93000.0
    assert is_ceiling is True
    assert is_floor is False


def test_lot_size_historical():
    rules = TradingRulesManager(dynamic_rules=True, exchanges={"FPT": "hose"})
    
    # HOSE before 2021-01-04 is 10 shares
    assert rules.get_lot_size("FPT", pd.Timestamp("2020-12-31")) == 10
    # HOSE after 2021-01-04 is 100 shares
    assert rules.get_lot_size("FPT", pd.Timestamp("2021-01-04")) == 100


def test_odd_lot_allowed():
    rules = TradingRulesManager(dynamic_rules=True, exchanges={"FPT": "hose"})
    
    # HOSE before 2022-09-12: odd lot not allowed
    assert rules.is_odd_lot_allowed("FPT", pd.Timestamp("2022-09-11")) is False
    # HOSE after 2022-09-12: odd lot allowed
    assert rules.is_odd_lot_allowed("FPT", pd.Timestamp("2022-09-12")) is True


def test_settlement_days_historical():
    rules = TradingRulesManager(dynamic_rules=True)
    
    # Before 2016-01-01 is T+3 (returns 4 since trade can occur at T+4 open)
    assert rules.apply_dynamic_rules(pd.Timestamp("2015-12-31"), "open") == 4
    # T+2 before 2022-08-29 (returns 3)
    assert rules.apply_dynamic_rules(pd.Timestamp("2020-01-01"), "open") == 3
    # T+1.5 from 2022-08-29 onwards (returns 2 for execution at close, 3 for open)
    assert rules.apply_dynamic_rules(pd.Timestamp("2022-08-30"), "close") == 2
    assert rules.apply_dynamic_rules(pd.Timestamp("2022-08-30"), "open") == 3

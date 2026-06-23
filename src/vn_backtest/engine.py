import logging
import pandas as pd
import numpy as np
from typing import Type, Union, List, Dict, Any
from collections import deque
from .strategy import Strategy
from .trading_rules import TradingRulesManager
from .margin import MarginManager
from .corporate_actions import CorporateActionProcessor
from .orders import Order, OrderStatus, OrderType

logger = logging.getLogger(__name__)


class BacktestEngine:
    """
    Backtesting Engine tailored for the Vietnamese Stock Market.
    Supports T+1.5/T+2 settlement cycle, lot size restrictions, transaction costs (taxes & fees),
    and exchange-specific daily price limits (ceiling/floor).
    """

    def __init__(
        self,
        data: Union[pd.DataFrame, Dict[str, pd.DataFrame]],
        strategy_class: Type[Strategy],
        corporate_actions: Dict[str, pd.DataFrame] = None,
        initial_cash: float = 100_000_000.0,  # 100M VND default
        buy_fee: float = 0.0015,  # 0.15% brokerage fee
        sell_fee: float = 0.0015,  # 0.15% brokerage fee
        sell_tax: float = 0.001,  # 0.1% selling tax in VN
        settlement_days: int = 2,  # T+2 settlement for shares
        lot_size: int = 100,  # Lot size of 100 shares in VN
        exchange: Union[str, Dict[str, str]] = "hose",  # 'hose', 'hnx', 'upcom'
        execution_at: str = "open",  # Execute at 'open' or 'close' of next bar
        restrict_ceiling_buy: bool = True,  # Cannot buy if price is at Ceiling
        restrict_floor_sell: bool = True,  # Cannot sell if price is at Floor
        slippage: float = 0.0,  # Slippage percentage (e.g. 0.001 = 0.1%)
        dynamic_rules: bool = True,  # Enable dynamic historical rules
        advance_interest_rate: float = 0.12,  # 12% p.a. Cash Advance interest
        auto_close_at_end: bool = True,  # Sell all positions at final bar
        allow_odd_lot: bool = False,  # Allow odd lot trading (1-99 shares)
        max_volume_ratio: float = None,  # Max trade size as a fraction of daily volume
        volume_limit_ratio: float = 0.10,  # Default market participation limit (10% of daily volume)
        limit_order_fill_policy: str = "conservative",  # Limit order fill policy: 'standard' or 'conservative'
        limit_fill_fraction: float = 0.20,  # Fraction to fill when limit price touches Low/High (20%)
        min_daily_volume: int = 10000,  # Minimum daily volume required for trading (10k shares)
        adjust_corporate_actions: bool = True,  # Set True to simulate corporate actions (splits/dividends)
        force_adjusted: bool = None,  # Force adjusted status (True: already adjusted, False: raw)
        margin_ratio: float = 1.0,  # 1.0 = no margin, 0.5 = 50% margin (2x leverage)
        margin_interest_rate: float = 0.13,  # 13% p.a. Margin Loan interest
        margin_maintenance_ratio: float = 0.35,  # 35% account equity ratio for margin call liquidation
        ticker: str = None,  # Optional: Ticker name if data is a single DataFrame
        strategy_params: Dict[str, Any] = None,  # Dict of parameters for strategy init
        market_impact_coef: float = 0.0,  # Market impact coefficient for dynamic slippage
        rights_listing_delay: int = 90,  # Calendar days delay for rights/stock dividend listing
        dividend_tax_rate: float = 0.05,  # 5% dividend tax rate in VN
        price_scale: float = 1.0,
        listing_dates: Dict[str, Union[str, pd.Timestamp]] = None,
        check_lookahead: bool = True,  # Option to bypass look-ahead bias checks
    ):
        # Handle multi-ticker data dict
        if isinstance(data, pd.DataFrame):
            t_name = ticker
            if not t_name:
                t_name = getattr(data, "name", None)
            if not t_name:
                t_name = getattr(self, "ticker", "FPT")
            self.data = {t_name: data.copy()}
            self.main_ticker = t_name
            self.ticker = t_name
        elif isinstance(data, dict):
            self.data = {k: v.copy() for k, v in data.items()}
            self.main_ticker = list(self.data.keys())[0] if data else "FPT"
            self.ticker = ",".join(self.data.keys())
        else:
            raise ValueError("Data must be a pandas DataFrame or a dict of DataFrames")

        # [TIMEZONE ALIGNMENT] Ensure all data indices are timezone-naive
        for ticker_k, df_val in list(self.data.items()):
            if hasattr(df_val.index, "tz") and df_val.index.tz is not None:
                df_val.index = df_val.index.tz_localize(None)
                self.data[ticker_k] = df_val

        # [TIMEZONE ALIGNMENT] Ensure corporate actions are timezone-naive
        self.corporate_actions = {}
        if corporate_actions:
            for ticker_k, df_val in corporate_actions.items():
                df_copy = df_val.copy()
                if hasattr(df_copy.index, "tz") and df_copy.index.tz is not None:
                    df_copy.index = df_copy.index.tz_localize(None)
                for col in df_copy.columns:
                    if pd.api.types.is_datetime64_any_dtype(df_copy[col]):
                        if df_copy[col].dt.tz is not None:
                            df_copy[col] = df_copy[col].dt.tz_localize(None)
                self.corporate_actions[ticker_k] = df_copy

        # Pre-group corporate actions by exright_date for O(1) daily lookups
        self.corporate_actions_by_date = {}
        for ticker, df in self.corporate_actions.items():
            if df.empty or "exright_date" not in df.columns:
                continue
            for _, row in df.iterrows():
                dt = row["exright_date"]
                if pd.notna(dt):
                    norm_dt = pd.to_datetime(dt).normalize()
                    if norm_dt not in self.corporate_actions_by_date:
                        self.corporate_actions_by_date[norm_dt] = []
                    self.corporate_actions_by_date[norm_dt].append((ticker, row))

        self.strategy_class = strategy_class
        self.initial_cash = initial_cash
        self.buy_fee = buy_fee
        self.sell_fee = sell_fee
        self.sell_tax = sell_tax
        self.settlement_days = settlement_days
        self.lot_size = lot_size
        self.execution_at = execution_at.lower()
        self.restrict_ceiling_buy = restrict_ceiling_buy
        self.restrict_floor_sell = restrict_floor_sell
        self.slippage = slippage
        self.market_impact_coef = market_impact_coef
        self.dynamic_rules = dynamic_rules
        self.advance_interest_rate = advance_interest_rate
        self.auto_close_at_end = auto_close_at_end
        self.allow_odd_lot = allow_odd_lot
        self.max_volume_ratio = max_volume_ratio
        self.volume_limit_ratio = volume_limit_ratio
        self.limit_order_fill_policy = limit_order_fill_policy.lower()
        self.limit_fill_fraction = limit_fill_fraction
        self.min_daily_volume = min_daily_volume
        self.adjust_corporate_actions = adjust_corporate_actions
        self.force_adjusted = force_adjusted
        self.margin_ratio = margin_ratio
        self.margin_interest_rate = margin_interest_rate
        self.margin_maintenance_ratio = margin_maintenance_ratio
        self.strategy_params = strategy_params or {}
        self.rights_listing_delay = rights_listing_delay
        self.dividend_tax_rate = dividend_tax_rate
        self.price_scale = price_scale
        self.dividend_shares = {}
        self.check_lookahead = check_lookahead

        # Risk management tracking
        self.position_entry_price = {}
        self.position_highest_price = {}

        # Save default settings to fall back to if dynamic_rules is disabled
        self.default_settlement_days = settlement_days
        self.default_lot_size = lot_size
        self.default_allow_odd_lot = allow_odd_lot

        # Handle exchange per ticker
        if isinstance(exchange, str):
            self.exchanges = {ticker: exchange.lower() for ticker in self.data}
        elif isinstance(exchange, dict):
            self.exchanges = {ticker: ex.lower() for ticker, ex in exchange.items()}
        else:
            self.exchanges = {ticker: "hose" for ticker in self.data}

        # Align all dates to create unified timeline (already normalized to tz-naive)
        all_dates = set()
        for df in self.data.values():
            all_dates.update(df.index)
        self.dates = sorted(list(all_dates))

        # Fetch corporate actions for all tickers if enabled
        # Track pending cash dividends: list of dicts {'amount': float, 'payout_date': datetime, 'ticker': str}
        self.pending_dividends: List[Dict[str, Any]] = []

        # Initialize portfolio state
        self.cash = initial_cash

        # Positions: ticker -> total quantity
        self.positions: Dict[str, int] = {}
        # Sellable shares: ticker -> quantity settled
        self.sellable_shares: Dict[str, int] = {}

        # Share Settlement Queue: list of dicts {'ticker': str, 'quantity': int, 'settle_idx': int}
        self.settlement_queue: List[Dict[str, Any]] = []

        # Cash Settlement Queue: list of dicts {'amount': float, 'settle_idx': int, 'borrowed': float}
        self.cash_settlement_queue: List[Dict[str, Any]] = []

        # Order queues
        self.pending_orders: List[Order] = []
        self.order_counter = 0

        # History logs
        self.trades_history: List[Dict[str, Any]] = []
        self.order_logs: List[Dict[str, Any]] = []
        self.portfolio_history: List[Dict[str, Any]] = []
        self.is_bankrupt = False

        # Initialize managers
        self.margin_manager = MarginManager(self)
        self.corporate_processor = CorporateActionProcessor(self)

        # Detect if data is already adjusted
        self.dividends_already_factored = False
        if self.adjust_corporate_actions:
            if self.force_adjusted is not None:
                self.dividends_already_factored = self.force_adjusted
            else:
                self.dividends_already_factored = self.corporate_processor.detect_if_adjusted()

            if self.dividends_already_factored:
                logger.warning(
                    "==============================================================\n"
                    "CẢNH BÁO: Phát hiện dữ liệu giá đầu vào đã được ĐIỀU CHỈNH (Adjusted). "
                    "Tự động vô hiệu hóa việc cộng dồn cổ tức/chia tách để tránh lỗi Double-Adjustment.\n"
                    "=============================================================="
                )

        # Calculate adjusted price columns
        self.corporate_processor.calculate_adjusted_prices()

        # Identify first listing dates before reindexing (and normalize timezone)
        self.raw_listing_dates = {}
        input_listing_dates = listing_dates or {}
        for ticker in self.data:
            if ticker in input_listing_dates:
                dt_val = pd.to_datetime(input_listing_dates[ticker])
                if dt_val.tz is not None:
                    dt_val = dt_val.tz_localize(None)
                self.raw_listing_dates[ticker] = dt_val

        # Initialize TradingRulesManager
        self.rules = TradingRulesManager(
            dynamic_rules=self.dynamic_rules,
            default_lot_size=self.default_lot_size,
            default_allow_odd_lot=self.default_allow_odd_lot,
            exchanges=self.exchanges,
            raw_listing_dates=self.raw_listing_dates,
            price_scale=self.price_scale,
        )

        # Simple heuristic check for price scale mismatch
        for ticker, df in self.data.items():
            if not df.empty and "Close" in df.columns:
                med_close = df["Close"].median()
                if med_close < 1000.0 and self.price_scale == 1.0:
                    import warnings

                    warnings.warn(
                        f"❌ CẢNH BÁO: Giá trung vị của {ticker} là {med_close:.2f} (< 1000) nhưng 'price_scale' đang đặt là 1.0.\n"
                        f"Nếu dữ liệu của bạn có giá ở đơn vị nghìn đồng (ví dụ 50.5 thay vì 50500), vui lòng đặt 'price_scale=1000' để tránh tính sai luật trần sàn/tick size!",
                        UserWarning,
                    )
                    logger.warning(
                        f"Mismatched price scale warning for {ticker}: median={med_close:.2f}, price_scale={self.price_scale}"
                    )

        # Reindex and fill data to prevent multi-ticker timeline alignment issues
        self._reindex_and_fill_data()

    @property
    def available_cash(self) -> float:
        """Get cash available to buy shares today (settled cash)."""
        pending_cash = sum(
            item["amount"] - item.get("borrowed", 0.0)
            for item in self.cash_settlement_queue
        )
        return max(0.0, self.cash - pending_cash)

    def place_buy_order(
        self,
        ticker: str,
        size: Union[float, int, None],
        time: pd.Timestamp,
        limit_price: float = None,
        stop_price: float = None,
        expiration_bars: int = None,
        oco_sibling_id: str = None,
        order_type: str = None,
        note: str = None,  # Custom transaction notes or tracking info
    ) -> Order:
        """Queue a buy order for the next bar."""
        self.order_counter += 1
        order_id = f"order_{self.order_counter}"

        if order_type is not None:
            resolved_type = order_type.upper()
        else:
            resolved_type = OrderType.MARKET
            if limit_price is not None:
                resolved_type = OrderType.LIMIT
            if stop_price is not None:
                resolved_type = OrderType.STOP
            if oco_sibling_id is not None:
                resolved_type = OrderType.OCO

        order = Order(
            order_id=order_id,
            ticker=ticker,
            action="buy",
            order_type=resolved_type,
            size=size,
            limit_price=limit_price,
            stop_price=stop_price,
            time_placed=time,
            oco_sibling_id=oco_sibling_id,
            expiration_bars=expiration_bars,
            note=note,
        )
        self.pending_orders.append(order)
        return order

    def place_sell_order(
        self,
        ticker: str,
        size: Union[float, int, None],
        time: pd.Timestamp,
        limit_price: float = None,
        stop_price: float = None,
        expiration_bars: int = None,
        oco_sibling_id: str = None,
        order_type: str = None,
        note: str = None,  # Custom transaction notes or tracking info
    ) -> Order:
        """Queue a sell order for the next bar."""
        self.order_counter += 1
        order_id = f"order_{self.order_counter}"

        if order_type is not None:
            resolved_type = order_type.upper()
        else:
            resolved_type = OrderType.MARKET
            if limit_price is not None:
                resolved_type = OrderType.LIMIT
            if stop_price is not None:
                resolved_type = OrderType.STOP
            if oco_sibling_id is not None:
                resolved_type = OrderType.OCO

        order = Order(
            order_id=order_id,
            ticker=ticker,
            action="sell",
            order_type=resolved_type,
            size=size,
            limit_price=limit_price,
            stop_price=stop_price,
            time_placed=time,
            oco_sibling_id=oco_sibling_id,
            expiration_bars=expiration_bars,
            note=note,
        )
        self.pending_orders.append(order)
        return order

    def place_target_percent_order(
        self, ticker: str, target_percent: float, time: pd.Timestamp
    ) -> Order:
        """Queue a target percent order for the next bar."""
        self.order_counter += 1
        order_id = f"order_{self.order_counter}"

        order = Order(
            order_id=order_id,
            ticker=ticker,
            action="target_percent",
            order_type=OrderType.MARKET,
            time_placed=time,
        )
        order.target_percent = target_percent
        self.pending_orders.append(order)
        return order

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order by its ID. Cascades to OCO siblings."""
        found = False
        target_order = None
        for order in self.pending_orders:
            if order.order_id == order_id:
                target_order = order
                found = True
                break

        if (
            not found
            and hasattr(self, "_current_executing_orders")
            and self._current_executing_orders
        ):
            for order in self._current_executing_orders:
                if order.order_id == order_id:
                    target_order = order
                    found = True
                    break

        if found and target_order is not None:
            if target_order.status in [
                OrderStatus.FILLED,
                OrderStatus.CANCELLED,
                OrderStatus.EXPIRED,
            ]:
                return False

            target_order.status = OrderStatus.CANCELLED
            if target_order in self.pending_orders:
                self.pending_orders.remove(target_order)

            self.order_logs.append(
                {
                    "Date": (
                        self.dates[self.current_idx]
                        if hasattr(self, "current_idx")
                        else None
                    ),
                    "Ticker": target_order.ticker,
                    "Action": "ORDER_CANCELLED",
                    "Reason": "Cancelled by strategy or user",
                    "Price": 0.0,
                    "Quantity": target_order.quantity,
                }
            )

            # Cascade cancel OCO sibling if exists
            if target_order.oco_sibling_id:
                self.cancel_order(target_order.oco_sibling_id)

            return True
        return False

    def _get_execution_price(self, ticker: str, idx: int) -> float:
        """Calculate base execution price according to the execution model using cached arrays."""
        exec_mode = self.execution_at.lower()
        arrays = self._price_arrays[ticker]
        open_p = float(arrays["Open"][idx])
        close_p = float(arrays["Close"][idx])
        high_p = float(arrays["High"][idx])
        low_p = float(arrays["Low"][idx])

        if exec_mode == "open":
            return open_p
        elif exec_mode == "close":
            return close_p
        elif exec_mode in ["average", "vwap"]:
            if "Average" in arrays:
                avg_val = arrays["Average"][idx]
                if pd.notna(avg_val) and avg_val > 0:
                    return float(avg_val)
            # fallback to OHLC average
            return (open_p + high_p + low_p + close_p) / 4.0
        elif exec_mode == "hl2":
            return (high_p + low_p) / 2.0
        elif exec_mode == "typical":
            return (high_p + low_p + close_p) / 3.0
        else:
            # default fallback
            return open_p if exec_mode == "open" else close_p

    def _get_tick_size(
        self, price: float, exchange: str, current_time: pd.Timestamp = None
    ) -> float:
        """Get the tick size for a given price according to exchange rules."""
        return self.rules.get_tick_size(price, exchange, current_time)

    def _round_to_tick(
        self,
        price: float,
        exchange: str,
        direction: str,
        current_time: pd.Timestamp = None,
    ) -> float:
        """Round a price to the nearest tick size according to Vietnam exchange rules."""
        return self.rules.round_to_tick(price, exchange, direction, current_time)

    def _check_price_limits(
        self,
        price: float,
        prev_close: float,
        exchange: str,
        price_limit: float,
        current_time: pd.Timestamp = None,
    ) -> tuple[float, float, bool, bool]:
        """Calculate ceiling and floor prices and check if execution price hits them."""
        return self.rules.check_price_limits(
            price, prev_close, exchange, price_limit, current_time
        )

    def _get_lot_size(self, ticker: str, current_time: pd.Timestamp) -> int:
        """Get the lot size dynamically based on time and exchange rules."""
        return self.rules.get_lot_size(ticker, current_time)

    def _is_odd_lot_allowed(self, ticker: str, current_time: pd.Timestamp) -> bool:
        """Determine if odd-lot trading (1-99 shares) is allowed for a stock today."""
        return self.rules.is_odd_lot_allowed(ticker, current_time)

    def _get_price_limit(self, ticker: str, current_time: pd.Timestamp) -> float:
        """Get the daily price limit percentage for a stock based on date and listing status."""
        return self.rules.get_price_limit(ticker, current_time)

    def _process_settlements(self, current_idx: int):
        """Move shares from locked to sellable once they reach their settlement index."""
        active_settlements = []
        for item in self.settlement_queue:
            if current_idx >= item["settle_idx"]:
                ticker = item["ticker"]
                qty = item["quantity"]
                self.sellable_shares[ticker] = self.sellable_shares.get(ticker, 0) + qty
            else:
                active_settlements.append(item)
        self.settlement_queue = active_settlements

    def _process_cash_settlements(self, current_idx: int):
        """Move cash from pending to available once it reaches settlement index."""
        active_cash_settlements = []
        for item in self.cash_settlement_queue:
            if current_idx < item["settle_idx"]:
                active_cash_settlements.append(item)
        self.cash_settlement_queue = active_cash_settlements

    def _apply_dynamic_rules(self, current_time: pd.Timestamp):
        """Apply VN historical trading rules based on the date."""
        self.settlement_days = self.rules.apply_dynamic_rules(
            current_time, self.execution_at
        )

    def run(self) -> Dict[str, Any]:
        """Run the backtest simulation."""
        # Initialize strategy
        strategy = self.strategy_class(self.data, self, **self.strategy_params)
        strategy.init()

        n_bars = len(self.dates)

        # Pre-compute previous-bar reference prices and close prices to avoid
        # O(N²) DataFrame slicing (`ticker_df[:current_time]`) inside the loop.
        self._prev_ref_cache: Dict[str, np.ndarray] = {}
        self._prev_close_cache: Dict[str, np.ndarray] = {}
        self._price_arrays: Dict[str, Dict[str, np.ndarray]] = {}

        for ticker, ticker_df in self.data.items():
            # Cache OHLCV arrays for fast lookup
            self._price_arrays[ticker] = {
                "Open": ticker_df["Open"].values,
                "High": ticker_df["High"].values,
                "Low": ticker_df["Low"].values,
                "Close": ticker_df["Close"].values,
                "Volume": ticker_df["Volume"].values,
                "Traded": ticker_df["Traded"].values if "Traded" in ticker_df.columns else np.ones(len(ticker_df)),
            }
            if "Average" in ticker_df.columns:
                self._price_arrays[ticker]["Average"] = ticker_df["Average"].values

            exch = self.exchanges.get(ticker, "hose")
            if exch == "upcom":
                if "Average" in ticker_df.columns:
                    ref = ticker_df["Average"].where(
                        ticker_df["Average"].notna() & (ticker_df["Average"] > 0),
                        (
                            ticker_df["Open"]
                            + ticker_df["High"]
                            + ticker_df["Low"]
                            + ticker_df["Close"]
                        )
                        / 4.0,
                    )
                else:
                    ref = (
                        ticker_df["Open"]
                        + ticker_df["High"]
                        + ticker_df["Low"]
                        + ticker_df["Close"]
                    ) / 4.0
            else:
                ref = ticker_df["Close"]
            self._prev_ref_cache[ticker] = ref.shift(1).values
            self._prev_close_cache[ticker] = ticker_df["Close"].shift(1).values

        # Main simulation loop
        for idx in range(n_bars):
            strategy.current_idx = idx
            current_time = self.dates[idx]

            # 0. Apply dynamic rules if active
            if self.dynamic_rules:
                self._apply_dynamic_rules(current_time)

            # 1. Process share settlements at start of day
            self._process_settlements(idx)

            # 2. Process cash settlements at start of day
            self._process_cash_settlements(idx)

            # 2.5 Process corporate actions today if enabled
            if self.adjust_corporate_actions:
                self.corporate_processor.process_corporate_actions(current_time, idx)

            # 2.6 Auto-liquidation for delisted / last active day stocks
            current_date = current_time.normalize()
            if hasattr(self, "tickers_by_last_active_date") and current_date in self.tickers_by_last_active_date:
                for ticker in self.tickers_by_last_active_date[current_date]:
                    qty = self.positions.get(ticker, 0)
                    if qty > 0:
                            # Force sell at close price of the last active day
                            close_price = self._price_arrays[ticker]["Close"][idx]
                            if pd.isna(close_price):
                                close_val = self._prev_close_cache[ticker][idx]
                                close_price = 0.0 if pd.isna(close_val) else float(close_val)

                            trade_value = qty * close_price
                            fee = trade_value * self.sell_fee
                            tax = trade_value * self.sell_tax

                            # Apply 5% personal income tax (TNCN) on selling stock dividends under Decree 126
                            div_tax = 0.0
                            div_qty = self.dividend_shares.get(ticker, 0)
                            sold_from_div = min(qty, div_qty)
                            if sold_from_div > 0:
                                self.dividend_shares[ticker] = div_qty - sold_from_div
                                div_tax = (
                                    sold_from_div
                                    * min(close_price, 10000.0)
                                    * self.dividend_tax_rate
                                )
                                tax += div_tax

                            net_proceeds = trade_value - fee - tax

                            # Add cash and remove positions immediately
                            self.cash += net_proceeds
                            settle_idx = idx + self.settlement_days
                            self.cash_settlement_queue.append(
                                {
                                    "amount": net_proceeds,
                                    "settle_idx": settle_idx,
                                    "borrowed": 0.0,
                                }
                            )

                            self.positions[ticker] = 0
                            self.sellable_shares[ticker] = 0

                            # Clean up positions dictionaries
                            if ticker in self.positions:
                                del self.positions[ticker]
                            if ticker in self.sellable_shares:
                                del self.sellable_shares[ticker]
                            if ticker in self.position_entry_price:
                                del self.position_entry_price[ticker]
                            if ticker in self.position_highest_price:
                                del self.position_highest_price[ticker]
                            if ticker in self.dividend_shares:
                                del self.dividend_shares[ticker]

                            self.trades_history.append(
                                {
                                    "Date": current_time,
                                    "Ticker": ticker,
                                    "Action": "SELL",
                                    "Quantity": qty,
                                    "Price": close_price,
                                    "Value": trade_value,
                                    "Fee": fee,
                                    "Tax": tax,
                                    "TotalValue": net_proceeds,
                                    "TimePlaced": current_time,
                                    "Note": "Auto-liquidated on last active trading day (Delisted)",
                                }
                            )
                            self.order_logs.append(
                                {
                                    "Date": current_time,
                                    "Ticker": ticker,
                                    "Action": "SELL_FILLED",
                                    "Reason": "Auto-liquidated on last active trading day (Delisted)",
                                    "Price": close_price,
                                    "Quantity": qty,
                                }
                            )
                            logger.info(
                                f"[DELIST] Tự động tất toán vị thế {ticker}: "
                                f"Bán {qty} CP tại giá {close_price:,.0f}đ do hủy niêm yết."
                            )

            # Không cần đồng bộ hóa ở đây nữa vì available_cash là property động
            pass

            # 2.7 Auto Stop Loss & Trailing Stop Risk checks
            self._check_risk_management(strategy, current_time, idx)

            # 3. Execute pending orders placed on previous day
            self._execute_orders(current_time, idx)

            # 4. Calculate portfolio equity at current Close
            # PERF: O(1) lookup using precomputed shifted close prices cache for valuation fallback
            positions_value = 0.0
            for ticker, qty in self.positions.items():
                close_price = self._price_arrays[ticker]["Close"][idx]
                if pd.isna(close_price):
                    close_val = self._prev_close_cache[ticker][idx]
                    close_price = 0.0 if pd.isna(close_val) else float(close_val)
                positions_value += qty * close_price

            equity = self.cash + positions_value

            if equity < 0:
                self.is_bankrupt = True
                logger.critical(
                    f"🚨 [BANKRUPTCY] Tài khoản bị âm tài sản ròng tại ngày {current_time.strftime('%d/%m/%Y')}! "
                    f"Equity: {equity:,.0f} VND (Tiền mặt: {self.cash:,.0f} VND, Giá trị danh mục: {positions_value:,.0f} VND)"
                )

            # 4.1 Daily Margin Interest Check
            equity = self.margin_manager.check_margin_interest(current_time, idx, equity)

            # 4.2 Margin Maintenance Ratio Check (Force Sell liquidation)
            self.margin_manager.check_margin_maintenance(current_time, idx, positions_value, equity)

            # Save history
            history_record = {
                "Date": current_time,
                "Cash": self.cash,
                "AvailableCash": self.available_cash,
                "Equity": equity,
            }
            # Record individual ticker valuations for portfolio analysis
            for t in self.data:
                q = self.positions.get(t, 0)
                if q > 0:
                    c_price = self._price_arrays[t]["Close"][idx]
                    if pd.isna(c_price):
                        c_val = self._prev_close_cache[t][idx]
                        c_price = 0.0 if pd.isna(c_val) else float(c_val)
                    history_record[f"Val_{t}"] = q * c_price
                else:
                    history_record[f"Val_{t}"] = 0.0
            self.portfolio_history.append(history_record)

            # 5. Call strategy's next() to make new trading decisions
            if idx < n_bars - 1:
                strategy.next()
                self._size_pending_orders(current_time, idx)

        # Auto-close positions at final bar if active
        if self.auto_close_at_end and any(qty > 0 for qty in self.positions.values()):
            last_date = self.dates[-1]
            active_tickers = [t for t, q in self.positions.items() if q > 0]
            for ticker in active_tickers:
                qty = self.positions[ticker]
                close_price = self._price_arrays[ticker]["Close"][-1]
                if pd.isna(close_price):
                    close_val = self._prev_close_cache[ticker][-1]
                    close_price = 0.0 if pd.isna(close_val) else float(close_val)

                # Apply transaction fee and tax
                trade_value = qty * close_price
                fee = trade_value * self.sell_fee
                tax = trade_value * self.sell_tax

                # Apply 5% personal income tax (TNCN) on selling stock dividends under Decree 126
                div_tax = 0.0
                div_qty = self.dividend_shares.get(ticker, 0)
                sold_from_div = min(qty, div_qty)
                if sold_from_div > 0:
                    self.dividend_shares[ticker] = div_qty - sold_from_div
                    div_tax = (
                        sold_from_div
                        * min(close_price, 10000.0)
                        * self.dividend_tax_rate
                    )
                    tax += div_tax

                net_proceeds = trade_value - fee - tax

                # Settle cash immediately since it's the end of backtest
                self.cash += net_proceeds

                self.positions[ticker] = 0
                self.sellable_shares[ticker] = 0
                if ticker in self.dividend_shares:
                    del self.dividend_shares[ticker]

                trade_record = {
                    "Date": last_date,
                    "Ticker": ticker,
                    "Action": "SELL",
                    "Quantity": qty,
                    "Price": close_price,
                    "Value": trade_value,
                    "Fee": fee,
                    "Tax": tax,
                    "TotalValue": net_proceeds,
                    "TimePlaced": last_date,
                    "Note": "Auto-closed at end of backtest",
                }
                self.trades_history.append(trade_record)
                self.order_logs.append(
                    {
                        "Date": last_date,
                        "Ticker": ticker,
                        "Action": "SELL_FILLED",
                        "Reason": "Auto-closed at end of backtest",
                        "Price": close_price,
                        "Quantity": qty,
                    }
                )

            # Update last history record
            self.portfolio_history[-1]["Cash"] = self.cash
            self.portfolio_history[-1]["AvailableCash"] = self.available_cash
            self.portfolio_history[-1]["Equity"] = self.cash
            for t in self.data:
                self.portfolio_history[-1][f"Val_{t}"] = 0.0

        # Create output DataFrames
        equity_df = pd.DataFrame(self.portfolio_history).set_index("Date")
        trades_df = pd.DataFrame(self.trades_history)
        order_logs_df = pd.DataFrame(self.order_logs)

        return {
            "equity_curve": equity_df,
            "trades": trades_df,
            "order_logs": order_logs_df,
            "initial_cash": self.initial_cash,
            "final_cash": self.cash,
            "final_equity": (
                equity_df["Equity"].iloc[-1]
                if not equity_df.empty
                else self.initial_cash
            ),
            "is_bankrupt": self.is_bankrupt,
        }

    def _execute_orders(
        self,
        current_time: pd.Timestamp,
        current_idx: int,
    ):
        """Execute orders queued on the previous bar."""
        if not self.pending_orders:
            return

        orders_to_process = self.pending_orders.copy()
        self.pending_orders.clear()

        # Sort evaluated orders: SELL first, BUY second to free up cash first
        sorted_orders = sorted(
            orders_to_process, key=lambda x: 0 if x.action == "sell" else 1
        )
        self._current_executing_orders = sorted_orders

        # Build prev_closes only for the tickers that have pending orders
        prev_closes = {}
        for order in sorted_orders:
            ticker = order.ticker
            if ticker not in prev_closes:
                cached_val = self._prev_ref_cache[ticker][current_idx]
                if cached_val is not None and not pd.isna(cached_val):
                    prev_closes[ticker] = float(cached_val)
                else:
                    prev_closes[ticker] = None

        for order in sorted_orders:
            # Skip executing orders placed on the current bar (they will execute on the next bar)
            if order.time_placed == current_time:
                self.pending_orders.append(order)
                continue

            # Skip if cancelled, filled or expired
            if order.status in [
                OrderStatus.CANCELLED,
                OrderStatus.FILLED,
                OrderStatus.EXPIRED,
            ]:
                continue

            # Increment bars since placed
            order.bars_since_placed += 1

            # Check expiration
            if (
                order.expiration_bars is not None
                and order.bars_since_placed > order.expiration_bars
            ):
                order.status = OrderStatus.EXPIRED
                self.order_logs.append(
                    {
                        "Date": current_time,
                        "Ticker": order.ticker,
                        "Action": "ORDER_EXPIRED",
                        "Reason": f"Order expired after {order.expiration_bars} bars",
                        "Price": 0.0,
                        "Quantity": order.quantity,
                    }
                )
                if order.oco_sibling_id:
                    self.cancel_order(order.oco_sibling_id)
                continue

            ticker = order.ticker
            action = order.action
            qty = order.remaining_quantity
            time_placed = order.time_placed
            is_partial_fill_touch = False

            # Check if ticker traded on current_time (idx)
            if ticker not in self._price_arrays:
                # Ticker data not found, cancel order
                order.status = OrderStatus.CANCELLED
                self.order_logs.append(
                    {
                        "Date": current_time,
                        "Ticker": ticker,
                        "Action": f"{order.order_type}_CANCELLED",
                        "Reason": "Ticker data not available in engine",
                        "Price": 0.0,
                        "Quantity": order.quantity,
                    }
                )
                continue

            ticker_arrays = self._price_arrays[ticker]
            # Since index is normalized and unified, we check if current_idx is valid
            if current_idx >= len(ticker_arrays["Open"]):
                # Out of bounds
                continue

            # Check for zero volume or NaN volume (suspended trading or illiquid) or not traded today
            vol = ticker_arrays["Volume"][current_idx]
            traded = ticker_arrays["Traded"][current_idx]

            # If not traded today (pre-debut or post-delisting)
            if pd.isna(vol) or traded == 0:
                if order.order_type in ["ATO", "ATC"]:
                    order.status = OrderStatus.CANCELLED
                    self.order_logs.append(
                        {
                            "Date": current_time,
                            "Ticker": ticker,
                            "Action": f"{order.order_type}_CANCELLED",
                            "Reason": "Ticker did not trade on execution day",
                            "Price": 0.0,
                            "Quantity": order.quantity,
                        }
                    )
                else:
                    # Keep order pending if ticker didn't trade today
                    self.pending_orders.append(order)
                continue

            # Check for zero volume or NaN volume or if it violates minimum daily volume (illiquid/suspended trading)
            is_illiquid = False
            reason_msg = ""
            if vol <= 0:
                is_illiquid = True
                reason_msg = "Zero trading volume or suspended trading on execution day"
            elif self.min_daily_volume is not None and vol < self.min_daily_volume:
                is_illiquid = True
                reason_msg = f"Daily trading volume ({vol:,.0f}) below minimum threshold ({self.min_daily_volume:,.0f})"

            if is_illiquid:
                if order.order_type in ["ATO", "ATC"]:
                    order.status = OrderStatus.CANCELLED
                    self.order_logs.append(
                        {
                            "Date": current_time,
                            "Ticker": ticker,
                            "Action": f"{order.order_type}_CANCELLED",
                            "Reason": reason_msg,
                            "Price": 0.0,
                            "Quantity": order.quantity,
                        }
                    )
                else:
                    # Keep order pending if ticker didn't trade or is illiquid today
                    self.pending_orders.append(order)
                    self.order_logs.append(
                        {
                            "Date": current_time,
                            "Ticker": ticker,
                            "Action": f"{action.upper()}_DEFERRED",
                            "Reason": reason_msg,
                            "Price": 0.0,
                            "Quantity": 0,
                        }
                    )
                continue

            prev_close = prev_closes.get(ticker)

            open_p = float(ticker_arrays["Open"][current_idx])
            high_p = float(ticker_arrays["High"][current_idx])
            low_p = float(ticker_arrays["Low"][current_idx])
            close_p = float(ticker_arrays["Close"][current_idx])

            # Check if today is the listing day
            is_listing_day = False
            if hasattr(self, "raw_listing_dates") and ticker in self.raw_listing_dates:
                if (
                    current_time.normalize()
                    == self.raw_listing_dates[ticker].normalize()
                ):
                    is_listing_day = True

            if is_listing_day:
                prev_close = open_p  # Use Open price as reference on listing day

            exch = self.exchanges.get(ticker, "hose")
            lot_size = self._get_lot_size(ticker, current_time)
            price_limit = self._get_price_limit(ticker, current_time)

            # Determine dynamic lot size based on odd lot permission
            effective_lot_size = (
                1 if self._is_odd_lot_allowed(ticker, current_time) else lot_size
            )

            # Determine base price and execution type
            if order.order_type == "ATO":
                base_price = open_p
            elif order.order_type == "ATC":
                base_price = close_p
            # Check Stop Order condition
            elif order.stop_price is not None:
                stop_triggered = False
                if action == "buy":
                    if high_p >= order.stop_price:
                        stop_triggered = True
                        base_price = max(open_p, order.stop_price)
                elif action == "sell":
                    if low_p <= order.stop_price:
                        stop_triggered = True
                        base_price = min(open_p, order.stop_price)

                if not stop_triggered:
                    self.pending_orders.append(order)
                    continue

                # If stop triggered and limit_price is present, check limit condition
                if order.limit_price is not None:
                    limit_price = order.limit_price
                    if action == "buy":
                        if low_p < limit_price:
                            base_price = min(base_price, limit_price)
                        elif low_p == limit_price:
                            if self.limit_order_fill_policy == "conservative":
                                is_partial_fill_touch = True
                                base_price = limit_price
                            else:
                                base_price = min(base_price, limit_price)
                        else:
                            self.pending_orders.append(order)
                            continue
                    elif action == "sell":
                        if high_p > limit_price:
                            base_price = max(base_price, limit_price)
                        elif high_p == limit_price:
                            if self.limit_order_fill_policy == "conservative":
                                is_partial_fill_touch = True
                                base_price = limit_price
                            else:
                                base_price = max(base_price, limit_price)
                        else:
                            self.pending_orders.append(order)
                            continue
            # Execution Price (handling Limit Orders)
            elif order.limit_price is not None:
                limit_price = order.limit_price
                if action == "buy":
                    if low_p < limit_price:
                        base_price = min(open_p, limit_price)
                    elif low_p == limit_price:
                        if self.limit_order_fill_policy == "conservative":
                            is_partial_fill_touch = True
                            base_price = limit_price
                        else:
                            base_price = min(open_p, limit_price)
                    else:
                        # Price did not reach buy limit, defer to next trading day
                        self.pending_orders.append(order)
                        continue
                elif action == "sell":
                    if high_p > limit_price:
                        base_price = max(open_p, limit_price)
                    elif high_p == limit_price:
                        if self.limit_order_fill_policy == "conservative":
                            is_partial_fill_touch = True
                            base_price = limit_price
                        else:
                            base_price = max(open_p, limit_price)
                    else:
                        # Price did not reach sell limit, defer to next trading day
                        self.pending_orders.append(order)
                        continue
            else:
                base_price = self._get_execution_price(ticker, current_idx)

            # Apply partial fill logic if it only touched the limit price
            if is_partial_fill_touch:
                original_qty = qty
                qty = int(qty * self.limit_fill_fraction)
                if effective_lot_size and effective_lot_size > 0:
                    qty = (qty // effective_lot_size) * effective_lot_size
                # If quantity rounds to 0, try to fill at least one minimum lot if order size permits
                if qty == 0 and original_qty >= effective_lot_size:
                    qty = effective_lot_size
                qty = min(qty, original_qty)

                touch_note = f"Limit price touched. Conservative policy filled {self.limit_fill_fraction*100:.0f}% of order."
                if order.note:
                    order.note = f"{order.note} ({touch_note})"
                else:
                    order.note = touch_note

            # Apply Price Limits (Ceiling/Floor)
            ceiling, floor, is_ceiling, is_floor = self._check_price_limits(
                base_price, prev_close, exch, price_limit, current_time
            )

            # Check Ceiling/Floor Locks
            if action == "buy" and is_ceiling and self.restrict_ceiling_buy:
                self.order_logs.append(
                    {
                        "Date": current_time,
                        "Ticker": ticker,
                        "Action": "BUY_REJECTED",
                        "Reason": f"Price at Ceiling limit ({ceiling})",
                        "Price": base_price,
                        "Quantity": 0,
                    }
                )
                order.status = OrderStatus.CANCELLED
                if order.oco_sibling_id:
                    self.cancel_order(order.oco_sibling_id)
                continue

            if action == "sell" and is_floor and self.restrict_floor_sell:
                # [FORCE SELL SAFETY] check if this order is a Margin liquidation
                is_force_sell = order.note and "Force Sell" in order.note
                reason_msg = f"Price at Floor limit ({floor})"
                if is_force_sell:
                    reason_msg += " - WARNING: Force Sell Liquidation failed due to liquidity shortage (floor lock)!"
                    logger.warning(
                        f"[MARGIN CALL] Giải chấp thất bại đối với {ticker}: "
                        f"Cổ phiếu bị floor lock (mất thanh khoản bán) tại ngày {current_time.strftime('%d/%m/%Y')}."
                    )

                self.order_logs.append(
                    {
                        "Date": current_time,
                        "Ticker": ticker,
                        "Action": "SELL_REJECTED",
                        "Reason": reason_msg,
                        "Price": base_price,
                        "Quantity": 0,
                    }
                )
                order.status = OrderStatus.CANCELLED
                if order.oco_sibling_id:
                    self.cancel_order(order.oco_sibling_id)
                continue

            # Apply Slippage (only for market/stop orders, excluding ATO/ATC)
            exec_price = base_price
            limit_price = order.limit_price
            if order.order_type in ["ATO", "ATC"]:
                # Round to nearest tick for auction price just in case
                exec_price = self._round_to_tick(
                    exec_price, exch, "nearest", current_time
                )
            elif limit_price is None:
                # Calculate percentage slippage
                pct_slippage = self.slippage
                if (
                    self.market_impact_coef > 0.0
                    and vol > 0
                ):
                    volume_share = qty / vol
                    pct_slippage += self.market_impact_coef * (volume_share**2)

                # Cap percentage slippage at 5.0% to keep it realistic
                pct_slippage = min(pct_slippage, 0.05)

                if action == "buy":
                    exec_price = exec_price * (1.0 + pct_slippage)
                else:
                    exec_price = exec_price * (1.0 - pct_slippage)

                order.applied_slippage = pct_slippage

                # Add absolute minimum slippage (half tick size for spread)
                tick_size = self._get_tick_size(base_price, exch, current_time)
                min_slippage = 0.5 * tick_size

                if action == "buy":
                    exec_price += min_slippage
                    # Round UP to nearest tick size to buy at or above ask price
                    exec_price = self._round_to_tick(
                        exec_price, exch, "up", current_time
                    )
                else:
                    exec_price -= min_slippage
                    # Round DOWN to nearest tick size to sell at or below bid price
                    exec_price = self._round_to_tick(
                        exec_price, exch, "down", current_time
                    )
            else:
                # For limit orders, just round to nearest tick to be sure
                exec_price = self._round_to_tick(
                    exec_price, exch, "nearest", current_time
                )

            # Limit price execution (cannot buy above ceiling or sell below floor)
            if exec_price > ceiling:
                exec_price = ceiling
            elif exec_price < floor:
                exec_price = floor

            # --- PROCESS BUY ORDER ---
            if action == "buy":
                original_qty = qty
                # Apply volume limit constraint (use max_volume_ratio if specified, otherwise fall back to volume_limit_ratio)
                active_volume_ratio = self.max_volume_ratio if self.max_volume_ratio is not None else self.volume_limit_ratio
                if active_volume_ratio is not None:
                    max_qty = int(vol * active_volume_ratio)
                    if effective_lot_size and effective_lot_size > 0:
                        max_qty = (
                            int(max_qty // effective_lot_size) * effective_lot_size
                        )
                    if qty > max_qty:
                        qty = max_qty

                if qty <= 0:
                    if order.order_type in ["ATO", "ATC"]:
                        order.status = OrderStatus.CANCELLED
                        self.order_logs.append(
                            {
                                "Date": current_time,
                                "Ticker": ticker,
                                "Action": f"{order.order_type}_CANCELLED",
                                "Reason": f"Target quantity scaled to 0 due to volume limits (cancelled {original_qty} shares)",
                                "Price": exec_price,
                                "Quantity": original_qty,
                            }
                        )
                    else:
                        # Defer the whole buy order to the next day
                        self.pending_orders.append(order)
                        self.order_logs.append(
                            {
                                "Date": current_time,
                                "Ticker": ticker,
                                "Action": "BUY_DEFERRED",
                                "Reason": f"Target quantity scaled to 0 due to volume limits (deferred {original_qty} shares)",
                                "Price": exec_price,
                                "Quantity": original_qty,
                            }
                        )
                    continue

                # Calculate Net Equity and max spend for margin trading
                current_positions_value = sum(
                    q * prev_closes.get(t, 0.0)
                    for t, q in self.positions.items()
                    if prev_closes.get(t) is not None
                )
                net_equity = self.cash + current_positions_value
                max_leverage = 1.0 / self.margin_ratio
                max_spend = max(
                    0.0, net_equity * max_leverage - current_positions_value
                )

                # Calculate cost
                trade_value = qty * exec_price
                fee = trade_value * self.buy_fee
                total_cost = trade_value + fee

                amount_needed = total_cost - self.available_cash
                advance_fee = 0.0

                # If we exceed max spend, we must scale down the qty
                if total_cost > max_spend:
                    low_qty = 0
                    high_qty = qty
                    best_qty = 0

                    while low_qty <= high_qty:
                        mid_qty = (low_qty + high_qty) // 2
                        if effective_lot_size and effective_lot_size > 0:
                            mid_qty = (
                                int(mid_qty // effective_lot_size) * effective_lot_size
                            )

                        if mid_qty == 0:
                            break

                        test_trade_value = mid_qty * exec_price
                        test_fee = test_trade_value * self.buy_fee
                        test_total_cost = test_trade_value + test_fee
                        test_amount_needed = test_total_cost - self.available_cash

                        test_advance_fee = 0.0
                        if test_amount_needed > 0:
                            temp_queue = sorted(
                                self.cash_settlement_queue,
                                key=lambda x: x["settle_idx"],
                            )
                            borrowed_so_far = 0.0
                            for item in temp_queue:
                                if borrowed_so_far >= test_amount_needed:
                                    break
                                settle_date = self.dates[
                                    min(item["settle_idx"], len(self.dates) - 1)
                                ]
                                days_diff = (settle_date - current_time).days
                                if days_diff <= 0:
                                    days_diff = 1
                                chunk_unborrowed = item["amount"] - item.get(
                                    "borrowed", 0.0
                                )
                                if chunk_unborrowed <= 0:
                                    continue
                                factor = (
                                    1.0
                                    + (self.advance_interest_rate / 365.0) * days_diff
                                )
                                to_borrow = min(
                                    test_amount_needed - borrowed_so_far,
                                    chunk_unborrowed / factor,
                                )
                                fee_for_chunk = (
                                    to_borrow
                                    * (self.advance_interest_rate / 365.0)
                                    * days_diff
                                )
                                borrowed_so_far += to_borrow
                                test_advance_fee += fee_for_chunk

                        if test_total_cost + test_advance_fee <= max_spend:
                            best_qty = mid_qty
                            if effective_lot_size and effective_lot_size > 0:
                                low_qty = mid_qty + effective_lot_size
                            else:
                                low_qty = mid_qty + 1
                        else:
                            if effective_lot_size and effective_lot_size > 0:
                                high_qty = mid_qty - effective_lot_size
                            else:
                                high_qty = mid_qty - 1

                    qty = best_qty

                    if qty <= 0:
                        order.status = OrderStatus.CANCELLED
                        self.order_logs.append(
                            {
                                "Date": current_time,
                                "Ticker": ticker,
                                "Action": "BUY_CANCELLED",
                                "Reason": "Insufficient funds including pending cash",
                                "Price": exec_price,
                                "Quantity": 0,
                            }
                        )
                        if order.oco_sibling_id:
                            self.cancel_order(order.oco_sibling_id)
                        continue

                    trade_value = qty * exec_price
                    fee = trade_value * self.buy_fee
                    total_cost = trade_value + fee
                    amount_needed = total_cost - self.available_cash

                # Borrow from cash_settlement_queue if needed
                if amount_needed > 0:
                    temp_queue = sorted(
                        self.cash_settlement_queue, key=lambda x: x["settle_idx"]
                    )
                    borrowed_so_far = 0.0

                    for item in temp_queue:
                        if borrowed_so_far >= amount_needed:
                            break

                        settle_date = self.dates[
                            min(item["settle_idx"], len(self.dates) - 1)
                        ]
                        days_diff = (settle_date - current_time).days
                        if days_diff <= 0:
                            days_diff = 1

                        chunk_unborrowed = item["amount"] - item.get("borrowed", 0.0)
                        if chunk_unborrowed <= 0:
                            continue

                        factor = 1.0 + (self.advance_interest_rate / 365.0) * days_diff
                        to_borrow = min(
                            amount_needed - borrowed_so_far, chunk_unborrowed / factor
                        )
                        fee_for_chunk = (
                            to_borrow * (self.advance_interest_rate / 365.0) * days_diff
                        )

                        item["borrowed"] = (
                            item.get("borrowed", 0.0) + to_borrow + fee_for_chunk
                        )
                        borrowed_so_far += to_borrow
                        advance_fee += fee_for_chunk

                # Deduct costs from balances
                self.cash -= total_cost + advance_fee

                self.positions[ticker] = self.positions.get(ticker, 0) + qty

                # Add to settlement queue
                settle_idx = current_idx + self.settlement_days
                self.settlement_queue.append(
                    {"ticker": ticker, "quantity": qty, "settle_idx": settle_idx}
                )

                trade_record = {
                    "Date": current_time,
                    "Ticker": ticker,
                    "Action": "BUY",
                    "Quantity": qty,
                    "Price": exec_price,
                    "Value": trade_value,
                    "Fee": fee,
                    "Tax": 0.0,
                    "TotalValue": total_cost,
                    "AdvanceFee": advance_fee,
                    "TimePlaced": time_placed,
                    "Note": order.note if order.note else None,
                }
                self.trades_history.append(trade_record)

                # Update Order status
                order.filled_quantity += qty
                deferred_qty = original_qty - qty
                order.remaining_quantity = deferred_qty

                if deferred_qty > 0:
                    if order.order_type in ["ATO", "ATC"]:
                        order.status = OrderStatus.PARTIALLY_FILLED
                        self.order_logs.append(
                            {
                                "Date": current_time,
                                "Ticker": ticker,
                                "Action": f"BUY_PARTIALLY_FILLED_CANCEL_REMAINING",
                                "Reason": f"Bought {qty} shares, cancelled remaining {deferred_qty} due to volume limits/cash"
                                + (
                                    f" (Ứng trước, phí: {advance_fee:,.0f}đ)"
                                    if advance_fee > 0
                                    else ""
                                ),
                                "Price": exec_price,
                                "Quantity": qty,
                            }
                        )
                    else:
                        order.status = OrderStatus.PARTIALLY_FILLED
                        self.pending_orders.append(order)
                        self.order_logs.append(
                            {
                                "Date": current_time,
                                "Ticker": ticker,
                                "Action": "BUY_PARTIALLY_FILLED",
                                "Reason": f"Bought {qty} shares, deferred {deferred_qty} due to volume limits/cash"
                                + (
                                    f" (Ứng trước, phí: {advance_fee:,.0f}đ)"
                                    if advance_fee > 0
                                    else ""
                                ),
                                "Price": exec_price,
                                "Quantity": qty,
                            }
                        )
                else:
                    order.status = OrderStatus.FILLED
                    self.order_logs.append(
                        {
                            "Date": current_time,
                            "Ticker": ticker,
                            "Action": "BUY_FILLED",
                            "Reason": "Success"
                            + (
                                f" (Ứng trước, phí: {advance_fee:,.0f}đ)"
                                if advance_fee > 0
                                else ""
                            ),
                            "Price": exec_price,
                            "Quantity": qty,
                        }
                    )

                if order.oco_sibling_id:
                    self.cancel_order(order.oco_sibling_id)

                # Update tracking of entry prices
                old_qty = self.positions.get(ticker, 0) - qty
                if old_qty > 0:
                    old_price = self.position_entry_price.get(ticker, exec_price)
                    self.position_entry_price[ticker] = (
                        old_price * old_qty + exec_price * qty
                    ) / (old_qty + qty)
                else:
                    self.position_entry_price[ticker] = exec_price

                if self.execution_at == "open":
                    self.position_highest_price[ticker] = max(
                        self.position_highest_price.get(ticker, 0.0),
                        exec_price,
                        high_p,
                    )
                else:
                    self.position_highest_price[ticker] = max(
                        self.position_highest_price.get(ticker, 0.0), exec_price
                    )

            # --- PROCESS SELL ORDER ---
            elif action == "sell":
                # Get max sellable quantity
                max_sellable = self.sellable_shares.get(ticker, 0)
                original_qty = qty
                qty = min(qty, max_sellable)

                # Check if we need to defer the unsellable part
                deferred_qty = original_qty - qty

                if qty <= 0:
                    if order.order_type in ["ATO", "ATC"]:
                        order.status = OrderStatus.CANCELLED
                        self.order_logs.append(
                            {
                                "Date": current_time,
                                "Ticker": ticker,
                                "Action": f"{order.order_type}_CANCELLED",
                                "Reason": f"All shares locked in settlement (cancelled {original_qty} shares)",
                                "Price": exec_price,
                                "Quantity": original_qty,
                            }
                        )
                    else:
                        # Defer the whole order to the next day
                        self.pending_orders.append(order)
                        self.order_logs.append(
                            {
                                "Date": current_time,
                                "Ticker": ticker,
                                "Action": "SELL_DEFERRED",
                                "Reason": f"All shares locked in settlement (deferred {original_qty} shares)",
                                "Price": exec_price,
                                "Quantity": original_qty,
                            }
                        )
                    continue

                # Apply volume limit constraint (use max_volume_ratio if specified, otherwise fall back to volume_limit_ratio)
                active_volume_ratio = self.max_volume_ratio if self.max_volume_ratio is not None else self.volume_limit_ratio
                if active_volume_ratio is not None:
                    max_qty = int(vol * active_volume_ratio)
                    if effective_lot_size and effective_lot_size > 0:
                        max_qty = (
                            int(max_qty // effective_lot_size) * effective_lot_size
                        )
                    if qty > max_qty:
                        qty = max_qty
                        # Update deferred quantity to include amount cut by volume limits
                        deferred_qty = original_qty - qty

                if qty <= 0:
                    order.status = OrderStatus.CANCELLED
                    self.order_logs.append(
                        {
                            "Date": current_time,
                            "Ticker": ticker,
                            "Action": "SELL_CANCELLED",
                            "Reason": "Target quantity scaled to 0 due to volume limits",
                            "Price": exec_price,
                            "Quantity": 0,
                        }
                    )
                    if order.oco_sibling_id:
                        self.cancel_order(order.oco_sibling_id)
                    continue

                # Execute Sell Trade
                trade_value = qty * exec_price
                fee = trade_value * self.sell_fee
                tax = trade_value * self.sell_tax

                # Apply 5% personal income tax (TNCN) on selling stock dividends under Decree 126
                div_tax = 0.0
                div_qty = self.dividend_shares.get(ticker, 0)
                sold_from_div = min(qty, div_qty)
                if sold_from_div > 0:
                    self.dividend_shares[ticker] = div_qty - sold_from_div
                    div_tax = (
                        sold_from_div
                        * min(exec_price, 10000.0)
                        * self.dividend_tax_rate
                    )
                    tax += div_tax

                net_proceeds = trade_value - fee - tax

                self.cash += net_proceeds

                # Add to cash settlement queue
                settle_idx = current_idx + self.settlement_days
                self.cash_settlement_queue.append(
                    {"amount": net_proceeds, "settle_idx": settle_idx, "borrowed": 0.0}
                )

                self.positions[ticker] = self.positions[ticker] - qty
                self.sellable_shares[ticker] = self.sellable_shares[ticker] - qty

                if self.positions[ticker] == 0:
                    del self.positions[ticker]
                    if ticker in self.position_entry_price:
                        del self.position_entry_price[ticker]
                    if ticker in self.position_highest_price:
                        del self.position_highest_price[ticker]
                    if ticker in self.dividend_shares:
                        del self.dividend_shares[ticker]

                if ticker in self.sellable_shares and self.sellable_shares[ticker] == 0:
                    del self.sellable_shares[ticker]

                trade_record = {
                    "Date": current_time,
                    "Ticker": ticker,
                    "Action": "SELL",
                    "Quantity": qty,
                    "Price": exec_price,
                    "Value": trade_value,
                    "Fee": fee,
                    "Tax": tax,
                    "TotalValue": net_proceeds,
                    "TimePlaced": time_placed,
                    "Note": order.note if order.note else None,
                }
                self.trades_history.append(trade_record)

                # Update Order status
                order.filled_quantity += qty
                order.remaining_quantity = deferred_qty

                if deferred_qty > 0:
                    if order.order_type in ["ATO", "ATC"]:
                        order.status = OrderStatus.PARTIALLY_FILLED
                        self.order_logs.append(
                            {
                                "Date": current_time,
                                "Ticker": ticker,
                                "Action": f"SELL_PARTIALLY_FILLED_CANCEL_REMAINING",
                                "Reason": f"Sold {qty} shares, cancelled remaining {deferred_qty} due to settlement lock/volume limits",
                                "Price": exec_price,
                                "Quantity": qty,
                            }
                        )
                    else:
                        order.status = OrderStatus.PARTIALLY_FILLED
                        self.pending_orders.append(order)
                        self.order_logs.append(
                            {
                                "Date": current_time,
                                "Ticker": ticker,
                                "Action": "SELL_PARTIALLY_FILLED",
                                "Reason": f"Sold {qty} shares, deferred {deferred_qty} due to settlement lock/volume limits",
                                "Price": exec_price,
                                "Quantity": qty,
                            }
                        )
                else:
                    order.status = OrderStatus.FILLED
                    self.order_logs.append(
                        {
                            "Date": current_time,
                            "Ticker": ticker,
                            "Action": "SELL_FILLED",
                            "Reason": "Success",
                            "Price": exec_price,
                            "Quantity": qty,
                        }
                    )

                if order.oco_sibling_id:
                    self.cancel_order(order.oco_sibling_id)

        if hasattr(self, "_current_executing_orders"):
            del self._current_executing_orders

    def _reindex_and_fill_data(self):
        """Reindex each ticker's DataFrame to the unified timeline and fill missing values."""
        self.last_active_dates = {}
        for ticker, df in list(self.data.items()):
            df["Traded"] = 1.0

            # Keep track of the actual last active trading date in the raw data
            last_active_date = df.index[-1]
            self.last_active_dates[ticker] = last_active_date

            # Reindex to the global timeline
            df_reindexed = df.reindex(self.dates)

            # Fill Volume and Traded with 0 for missing days
            df_reindexed["Volume"] = df_reindexed["Volume"].fillna(0.0)
            df_reindexed["Traded"] = df_reindexed["Traded"].fillna(0.0)

            # Identify which price columns actually exist in the original DataFrame
            price_cols = [
                "Open",
                "High",
                "Low",
                "Close",
                "Adj_Open",
                "Adj_High",
                "Adj_Low",
                "Adj_Close",
                "Average",
                "Adj_Average",
            ]
            actual_price_cols = [
                col for col in price_cols if col in df_reindexed.columns
            ]

            # Forward fill price columns, but do NOT backward fill (to prevent lookahead/listing bias before debut)
            df_reindexed[actual_price_cols] = df_reindexed[actual_price_cols].ffill()

            # Set price columns to NaN after the last active date to prevent look-ahead bias and hold pricing
            df_reindexed.loc[
                df_reindexed.index > last_active_date, actual_price_cols
            ] = np.nan

            self.data[ticker] = df_reindexed

        # Pre-group tickers by their normalized last active date for O(1) daily lookup
        self.tickers_by_last_active_date = {}
        for ticker, last_active_date in self.last_active_dates.items():
            norm_date = last_active_date.normalize()
            if norm_date not in self.tickers_by_last_active_date:
                self.tickers_by_last_active_date[norm_date] = []
            self.tickers_by_last_active_date[norm_date].append(ticker)

    def _size_pending_orders(self, current_time: pd.Timestamp, current_idx: int):
        """
        Convert float/None sizes and target percent orders into exact share quantities
        using the close prices of the current day (at the time the order is placed).
        """
        sized_orders = []
        for order in self.pending_orders:
            action = order.action
            ticker = order.ticker

            # Check if this order has already been sized (e.g. deferred from a previous day due to settlement lock)
            if order.is_sized:
                # Keep it as is but cap the sell quantity if our total position has changed
                if action == "sell":
                    total_pos = self.positions.get(ticker, 0)
                    order.quantity = min(order.quantity, total_pos)
                    order.remaining_quantity = min(order.remaining_quantity, total_pos)
                    if order.quantity <= 0:
                        order.status = OrderStatus.CANCELLED
                        continue
                sized_orders.append(order)
                continue

            # Get latest close price of the ticker
            close_price = self._price_arrays[ticker]["Close"][current_idx]
            if pd.isna(close_price):
                close_val = self._prev_close_cache[ticker][current_idx]
                close_price = None if pd.isna(close_val) else float(close_val)

            if close_price is None or pd.isna(close_price) or close_price <= 0:
                # Cannot size order without price, reject it
                order.status = OrderStatus.CANCELLED
                self.order_logs.append(
                    {
                        "Date": current_time,
                        "Ticker": ticker,
                        "Action": f"{action.upper()}_REJECTED",
                        "Reason": "No historical price available for order sizing",
                        "Price": 0.0,
                        "Quantity": 0,
                    }
                )
                continue

            lot_size = self._get_lot_size(ticker, current_time)
            effective_lot_size = (
                1 if self._is_odd_lot_allowed(ticker, current_time) else lot_size
            )

            # Calculate total portfolio equity for target percent or margin calculations
            positions_value = 0.0
            for t, pos_qty in self.positions.items():
                c_price = self._price_arrays[t]["Close"][current_idx]
                if pd.isna(c_price):
                    c_val = self._prev_close_cache[t][current_idx]
                    c_price = 0.0 if pd.isna(c_val) else float(c_val)
                positions_value += pos_qty * c_price
            equity = self.cash + positions_value

            qty = 0
            if action == "target_percent":
                target_percent = order.target_percent
                current_qty = self.positions.get(ticker, 0)

                if target_percent == 0.0:
                    # Sell all positions (using total position size instead of sellable_shares to support T+2 deferral)
                    qty = self.positions.get(ticker, 0)
                    action = "sell"
                else:
                    target_value = equity * target_percent
                    current_value = current_qty * close_price

                    if target_value > current_value:
                        # Need to buy
                        cash_to_use = target_value - current_value
                        # Sizing buy order quantity
                        target_shares = cash_to_use / (close_price * (1 + self.buy_fee))
                        if effective_lot_size and effective_lot_size > 0:
                            qty = (
                                int(target_shares // effective_lot_size)
                                * effective_lot_size
                            )
                        else:
                            qty = int(target_shares)
                        action = "buy"
                    elif target_value < current_value:
                        # Need to sell
                        value_to_sell = current_value - target_value
                        target_shares = value_to_sell / close_price
                        if effective_lot_size and effective_lot_size > 0:
                            qty = (
                                int(target_shares // effective_lot_size)
                                * effective_lot_size
                            )
                        else:
                            qty = int(target_shares)
                        # Cannot sell more than total owned positions
                        total_pos = self.positions.get(ticker, 0)
                        qty = min(qty, total_pos)
                        action = "sell"
                    else:
                        continue  # No change needed
            else:
                # Standard buy or sell
                size = order.size
                if action == "buy":
                    if size is None:
                        # Use all available cash (or max spend if margin)
                        if self.margin_ratio < 1.0:
                            max_leverage = 1.0 / self.margin_ratio
                            max_spend = max(
                                0.0, equity * max_leverage - positions_value
                            )
                            cash_to_use = max_spend
                        else:
                            cash_to_use = self.available_cash
                    elif isinstance(size, float) and 0.0 < size <= 1.0:
                        cash_to_use = equity * size
                        # Limit to cash/max spend
                        if self.margin_ratio < 1.0:
                            max_leverage = 1.0 / self.margin_ratio
                            max_spend = max(
                                0.0, equity * max_leverage - positions_value
                            )
                            cash_to_use = min(cash_to_use, max_spend)
                        else:
                            cash_to_use = min(cash_to_use, self.available_cash)
                    elif isinstance(size, (int, np.integer)) and size >= 1:
                        qty = int(size)
                        cash_to_use = 0.0
                    else:
                        continue

                    if qty == 0:
                        target_shares = cash_to_use / (close_price * (1 + self.buy_fee))
                        if effective_lot_size and effective_lot_size > 0:
                            qty = (
                                int(target_shares // effective_lot_size)
                                * effective_lot_size
                            )
                        else:
                            qty = int(target_shares)

                elif action == "sell":
                    # Size against total positions instead of sellable_shares to prevent T+2 locked orders from being discarded.
                    total_pos = self.positions.get(ticker, 0)
                    if size is None:
                        qty = total_pos
                    elif isinstance(size, float) and 0.0 < size <= 1.0:
                        target_shares = total_pos * size
                        if effective_lot_size and effective_lot_size > 0:
                            qty = (
                                int(target_shares // effective_lot_size)
                                * effective_lot_size
                            )
                            if (
                                qty == 0
                                and target_shares > 0
                                and target_shares == total_pos
                            ):
                                qty = total_pos
                        else:
                            qty = int(target_shares)
                    elif isinstance(size, (int, np.integer)) and size >= 1:
                        qty = min(int(size), total_pos)
                    else:
                        continue

            if qty > 0:
                order.action = action
                order.quantity = qty
                order.remaining_quantity = qty
                order.is_sized = True
                sized_orders.append(order)
            else:
                order.status = OrderStatus.CANCELLED
        self.pending_orders = sized_orders

    def _check_risk_management(
        self, strategy, current_time: pd.Timestamp, current_idx: int
    ):
        """Check and execute Stop Loss / Trailing Stop triggers for active positions."""
        if not self.positions:
            return

        has_sl = getattr(strategy, "stop_loss", None) is not None
        has_ts = getattr(strategy, "trailing_stop", None) is not None

        if not (has_sl or has_ts):
            return

        tickers_to_check = list(self.positions.keys())
        for ticker in tickers_to_check:
            qty = self.positions.get(ticker, 0)
            if qty <= 0:
                continue

            # Get values at current_idx directly from numpy arrays
            ticker_arrays = self._price_arrays[ticker]
            if current_idx >= len(ticker_arrays["Open"]):
                continue

            traded = ticker_arrays["Traded"][current_idx]
            # Skip checking if not traded today
            if traded == 0:
                continue

            low_price = ticker_arrays["Low"][current_idx]
            high_price = ticker_arrays["High"][current_idx]
            open_price = ticker_arrays["Open"][current_idx]

            # Get position highest price before today to calculate trailing stop level
            prev_highest = self.position_highest_price.get(ticker, open_price)

            # Check Stop Loss
            triggered = False
            trigger_reason = ""
            trigger_price = 0.0

            if has_sl:
                entry_price = self.position_entry_price.get(ticker, open_price)
                stop_loss_price = entry_price * (1.0 - strategy.stop_loss)
                if low_price <= stop_loss_price:
                    triggered = True
                    trigger_reason = (
                        f"Stop Loss Triggered (-{strategy.stop_loss*100:.1f}%)"
                    )
                    trigger_price = min(
                        open_price, stop_loss_price
                    )  # Sell at stop price or Open if gap down

            # Check Trailing Stop
            if not triggered and has_ts:
                # Use highest price before today to calculate trailing stop level
                # to avoid today's high resetting the trailing stop before checking today's low.
                trailing_stop_price = prev_highest * (1.0 - strategy.trailing_stop)
                if low_price <= trailing_stop_price:
                    triggered = True
                    trigger_reason = (
                        f"Trailing Stop Triggered (-{strategy.trailing_stop*100:.1f}%)"
                    )
                    trigger_price = min(
                        open_price, trailing_stop_price
                    )  # Sell at trailing stop price or Open if gap down

            if triggered:
                # Execute Sell immediately (at trigger_price)
                sellable = self.sellable_shares.get(ticker, 0)

                # Check if we need to defer the unsellable part
                deferred_qty = qty - sellable

                if sellable <= 0:
                    # Cannot sell due to settlement lock, queue a pending sell order for next day
                    self.place_sell_order(ticker, size=qty, time=current_time)
                    self.order_logs.append(
                        {
                            "Date": current_time,
                            "Ticker": ticker,
                            "Action": "RISK_TRIGGER_DEFERRED",
                            "Reason": f"{trigger_reason} but shares are locked in settlement. Queued sell order.",
                            "Price": trigger_price,
                            "Quantity": qty,
                        }
                    )
                else:
                    qty_to_sell = min(qty, sellable)

                    if deferred_qty > 0:
                        # Queue the remaining unsellable portion for next day
                        self.place_sell_order(
                            ticker, size=deferred_qty, time=current_time
                        )
                        self.order_logs.append(
                            {
                                "Date": current_time,
                                "Ticker": ticker,
                                "Action": "RISK_TRIGGER_PARTIALLY_DEFERRED",
                                "Reason": f"{trigger_reason} but partial lock. Sold {qty_to_sell}, queued remaining {deferred_qty}.",
                                "Price": trigger_price,
                                "Quantity": deferred_qty,
                            }
                        )

                    trade_value = qty_to_sell * trigger_price
                    fee = trade_value * self.sell_fee
                    tax = trade_value * self.sell_tax

                    # Apply 5% personal income tax (TNCN) on selling stock dividends under Decree 126
                    div_tax = 0.0
                    div_qty = self.dividend_shares.get(ticker, 0)
                    sold_from_div = min(qty_to_sell, div_qty)
                    if sold_from_div > 0:
                        self.dividend_shares[ticker] = div_qty - sold_from_div
                        div_tax = (
                            sold_from_div
                            * min(trigger_price, 10000.0)
                            * self.dividend_tax_rate
                        )
                        tax += div_tax

                    net_proceeds = trade_value - fee - tax

                    self.cash += net_proceeds
                    # Add to cash settlement queue
                    settle_idx = current_idx + self.settlement_days
                    self.cash_settlement_queue.append(
                        {
                            "amount": net_proceeds,
                            "settle_idx": settle_idx,
                            "borrowed": 0.0,
                        }
                    )

                    self.positions[ticker] = self.positions[ticker] - qty_to_sell
                    self.sellable_shares[ticker] = (
                        self.sellable_shares[ticker] - qty_to_sell
                    )

                    if self.positions[ticker] == 0:
                        del self.positions[ticker]
                        if ticker in self.position_entry_price:
                            del self.position_entry_price[ticker]
                        if ticker in self.position_highest_price:
                            del self.position_highest_price[ticker]
                        if ticker in self.dividend_shares:
                            del self.dividend_shares[ticker]

                    if (
                        ticker in self.sellable_shares
                        and self.sellable_shares[ticker] == 0
                    ):
                        del self.sellable_shares[ticker]

                    trade_record = {
                        "Date": current_time,
                        "Ticker": ticker,
                        "Action": "SELL",
                        "Quantity": qty_to_sell,
                        "Price": trigger_price,
                        "Value": trade_value,
                        "Fee": fee,
                        "Tax": tax,
                        "TotalValue": net_proceeds,
                        "TimePlaced": current_time,
                        "Note": trigger_reason,
                    }
                    self.trades_history.append(trade_record)
                    self.order_logs.append(
                        {
                            "Date": current_time,
                            "Ticker": ticker,
                            "Action": "SELL_FILLED",
                            "Reason": trigger_reason,
                            "Price": trigger_price,
                            "Quantity": qty_to_sell,
                        }
                    )

            # Update position highest price at the end of the day if the position still exists
            if ticker in self.positions:
                self.position_highest_price[ticker] = max(prev_highest, high_price)

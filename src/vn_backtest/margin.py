import logging
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class MarginManager:
    """
    Manages margin calculations, interest payments, maintenance margin checks,
    and handles automatic force liquidation for the BacktestEngine.
    """

    def __init__(self, engine):
        self.engine = engine

    def check_margin_interest(self, current_time: pd.Timestamp, idx: int, equity: float) -> float:
        """
        Calculate and charge daily margin interest if settled cash is negative.
        Returns the updated equity.
        """
        pending_cash = sum(
            item["amount"] - item.get("borrowed", 0.0)
            for item in self.engine.cash_settlement_queue
        )
        settled_cash = self.engine.cash - pending_cash

        if settled_cash < 0:
            # Calculate actual calendar days elapsed since the previous trading day
            days_diff = 1
            if idx > 0:
                days_diff = (self.engine.dates[idx] - self.engine.dates[idx - 1]).days
                if days_diff <= 0:
                    days_diff = 1
            interest = (
                abs(settled_cash) * (self.engine.margin_interest_rate / 365.0) * days_diff
            )
            self.engine.cash -= interest
            equity -= interest

            self.engine.trades_history.append(
                {
                    "Date": current_time,
                    "Ticker": "MARGIN",
                    "Action": "MARGIN_INTEREST",
                    "Quantity": 0,
                    "Price": 0.0,
                    "Value": interest,
                    "Fee": interest,
                    "Tax": 0.0,
                    "TotalValue": interest,
                    "TimePlaced": current_time,
                    "Note": f"Lãi vay Margin ({days_diff} ngày): {interest:,.0f} VND (Dư nợ thực tế: {abs(settled_cash):,.0f} VND, Chờ về: {pending_cash:,.0f} VND)",
                }
            )
        return equity

    def check_margin_maintenance(
        self, current_time: pd.Timestamp, idx: int, positions_value: float, equity: float
    ):
        """
        Check if the margin maintenance ratio is violated and place force sell orders if necessary.
        """
        if positions_value > 0 and self.engine.margin_ratio < 1.0:
            current_margin_ratio = equity / positions_value
            if current_margin_ratio < self.engine.margin_maintenance_ratio:
                # Calculate required liquidation value
                target_ratio = self.engine.margin_maintenance_ratio + 0.02
                value_to_sell = (target_ratio * positions_value - equity) / (
                    target_ratio - self.engine.sell_fee - self.engine.sell_tax
                )
                value_to_sell = min(value_to_sell, positions_value)

                self.engine.order_logs.append(
                    {
                        "Date": current_time,
                        "Ticker": "PORTFOLIO",
                        "Action": "MARGIN_CALL",
                        "Reason": f"Tỷ lệ ký quỹ ({current_margin_ratio*100:.2f}%) < {self.engine.margin_maintenance_ratio*100:.2f}%. Yêu cầu giải chấp khoảng {value_to_sell:,.0f} VND.",
                        "Price": 0.0,
                        "Quantity": 0,
                    }
                )

                for ticker, qty in list(self.engine.positions.items()):
                    # Proportional sell
                    close_price = self.engine._price_arrays[ticker]["Close"][idx]
                    if pd.isna(close_price):
                        close_val = self.engine._prev_close_cache[ticker][idx]
                        close_price = 0.0 if pd.isna(close_val) else float(close_val)

                    if close_price > 0:
                        qty_to_sell = qty * (value_to_sell / positions_value)
                        lot_size = self.engine._get_lot_size(ticker, current_time)
                        effective_lot_size = (
                            1
                            if self.engine._is_odd_lot_allowed(ticker, current_time)
                            else lot_size
                        )
                        if effective_lot_size and effective_lot_size > 0:
                            qty_to_sell = (
                                int(np.ceil(qty_to_sell / effective_lot_size))
                                * effective_lot_size
                            )
                        else:
                            qty_to_sell = int(np.ceil(qty_to_sell))

                        qty_to_sell = min(qty_to_sell, qty)
                        if qty_to_sell > 0:
                            self.engine.place_sell_order(
                                ticker,
                                size=qty_to_sell,
                                time=current_time,
                                note="Force Sell Liquidation due to Margin Call",
                            )

import pandas as pd


class OrderStatus:
    PENDING = "PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class OrderType:
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    OCO = "OCO"
    ATO = "ATO"
    ATC = "ATC"


class Order:
    """
    Represents a trading order in the backtest engine with a tracked lifecycle.
    """

    def __init__(
        self,
        order_id: str,
        ticker: str,
        action: str,  # 'buy' or 'sell'
        order_type: str,  # 'market', 'limit', 'stop', 'oco'
        size: float = None,
        limit_price: float = None,
        stop_price: float = None,
        time_placed: pd.Timestamp = None,
        oco_sibling_id: str = None,
        expiration_bars: int = None,
        note: str = None,  # Custom transaction notes or tracking info
    ):
        self.order_id = order_id
        self.ticker = ticker
        self.action = action.lower()
        self.order_type = order_type.upper()
        self.size = size
        self.limit_price = limit_price
        self.stop_price = stop_price
        self.time_placed = time_placed
        self.oco_sibling_id = oco_sibling_id
        self.expiration_bars = expiration_bars
        self.note = note

        self.status = OrderStatus.PENDING
        self.quantity = 0  # To be set when sized
        self.filled_quantity = 0
        self.remaining_quantity = 0
        self.bars_since_placed = 0
        self.applied_slippage = 0.0
        self.is_sized = False
        self.target_percent = None

    def __repr__(self):
        return (
            f"Order(id={self.order_id}, ticker={self.ticker}, action={self.action}, "
            f"type={self.order_type}, status={self.status}, qty={self.quantity}, "
            f"filled={self.filled_quantity})"
        )

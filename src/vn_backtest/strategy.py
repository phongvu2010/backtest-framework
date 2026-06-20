import logging
import pandas as pd
from typing import Callable, Any

logger = logging.getLogger(__name__)


class Strategy:
    """
    Base class for writing backtesting strategies.
    Inherit from this class and override init() and next() methods.
    """

    def __init__(self, data: Any, engine: Any, **kwargs):
        self.data = data
        self.engine = engine
        self._indicators = []
        self.current_idx = 0

        # Risk management parameters
        self.stop_loss = None
        self.trailing_stop = None

        # Set additional parameters as attributes (for optimization or customization)
        for key, value in kwargs.items():
            setattr(self, key, value)

    @property
    def current_time(self) -> pd.Timestamp:
        """Get current timestamp of the backtest simulation."""
        if hasattr(self.engine, "dates"):
            return self.engine.dates[self.current_idx]
        return self.data.index[self.current_idx]

    # ────────────────────────────────────────────────────────
    # OHLCV Accessors
    # ────────────────────────────────────────────────────────

    def _get_field(self, field: str, ticker: str = None) -> float:
        """
        Unified OHLCV data accessor. Used by all @property shortcuts and get_xxx() methods.

        Resolves data in priority order:
          1. If ticker given (or resolvable): df.loc[current_time, field] for the ticker.
          2. Fallback (single-DataFrame mode): df[field].iloc[current_idx].

        Returns float('nan') when the current_time is not in the ticker's index
        (e.g. the stock was not traded on that day).
        """
        if ticker is None:
            ticker = getattr(
                self.engine,
                "main_ticker",
                list(self.data.keys())[0] if isinstance(self.data, dict) else None,
            )
        if ticker is not None:
            df = self.data[ticker] if isinstance(self.data, dict) else self.data
            current_time = self.current_time
            if current_time in df.index:
                return float(df.loc[current_time, field])
            return float("nan")
        # Fallback: single-DataFrame mode without a named ticker
        return float(self.data[field].iloc[self.current_idx])

    @property
    def open(self) -> float:
        """Get the Open price of the current bar for the main ticker."""
        return self._get_field("Open")

    @property
    def high(self) -> float:
        """Get the High price of the current bar for the main ticker."""
        return self._get_field("High")

    @property
    def low(self) -> float:
        """Get the Low price of the current bar for the main ticker."""
        return self._get_field("Low")

    @property
    def close(self) -> float:
        """Get the Close price of the current bar for the main ticker."""
        return self._get_field("Close")

    @property
    def volume(self) -> float:
        """Get the Volume of the current bar for the main ticker."""
        return self._get_field("Volume")

    def get_open(self, ticker: str) -> float:
        """Get Open price of a specific ticker today."""
        return self._get_field("Open", ticker)

    def get_high(self, ticker: str) -> float:
        """Get High price of a specific ticker today."""
        return self._get_field("High", ticker)

    def get_low(self, ticker: str) -> float:
        """Get Low price of a specific ticker today."""
        return self._get_field("Low", ticker)

    def get_close(self, ticker: str) -> float:
        """Get Close price of a specific ticker today."""
        return self._get_field("Close", ticker)

    def get_volume(self, ticker: str) -> float:
        """Get Volume of a specific ticker today."""
        return self._get_field("Volume", ticker)

    @property
    def cash(self) -> float:
        """Get total portfolio cash (settled + pending)."""
        return self.engine.cash

    @property
    def available_cash(self) -> float:
        """Get cash available to buy shares today."""
        return self.engine.available_cash

    @property
    def positions(self) -> dict:
        """Get total shares owned per ticker."""
        return self.engine.positions

    @property
    def sellable_shares(self) -> dict:
        """Get settled shares available to sell per ticker."""
        return self.engine.sellable_shares

    @property
    def safe_data(self) -> pd.DataFrame:
        """
        [ANTI-LOOKAHEAD BIAS]
        Trả về DataFrame dữ liệu đã bị cắt (sliced) nghiêm ngặt từ ngày đầu tiên
        cho đến thời điểm hiện tại (current_idx).
        Sử dụng property này bên trong hàm next() nếu bạn cần tính toán các
        chỉ báo động (dynamic indicators) mà muốn đảm bảo 100% không vô tình
        tham chiếu đến dữ liệu tương lai.
        """
        ticker = getattr(
            self.engine,
            "main_ticker",
            list(self.data.keys())[0] if isinstance(self.data, dict) else None,
        )
        df = self.data[ticker] if isinstance(self.data, dict) else self.data
        return df.iloc[: self.current_idx + 1]

    def init(self):
        """
        Initialize strategy indicators.
        Override in subclass to precompute indicators on the historical data.
        """
        pass

    def next(self):
        """
        Define strategy logic for each trading day.
        Override in subclass. This is called on every trading day (bar).
        """
        pass

    def buy(self, ticker: str, size: float = None, limit_price: float = None) -> None:
        """
        Place a Buy Order.

        Args:
            ticker (str): The ticker symbol to buy (e.g. 'FPT').
            size (float or int, optional):
                - If float between 0.0 and 1.0 (e.g., 0.5): Allocates that percentage of available cash.
                - If integer > 1 (e.g., 200): Buys that exact number of shares.
                - If None: Allocates 100% of available cash.
            limit_price (float, optional): Limit price for the order. If None, it is a Market Order.
        """
        self.engine.place_buy_order(
            ticker, size, time=self.current_time, limit_price=limit_price
        )

    def sell(self, ticker: str, size: float = None, limit_price: float = None) -> None:
        """
        Place a Sell Order.

        Args:
            ticker (str): The ticker symbol to sell.
            size (float or int, optional):
                - If float between 0.0 and 1.0 (e.g., 0.5): Sells that percentage of the position.
                - If integer > 1: Sells that exact number of shares.
                - If None: Sells the entire position.
            limit_price (float, optional): Limit price for the order. If None, it is a Market Order.
        """
        self.engine.place_sell_order(
            ticker, size, time=self.current_time, limit_price=limit_price
        )

    def order_target_percent(self, ticker: str, target_percent: float) -> None:
        """
        Place a target percent order.

        Args:
            ticker (str): The ticker symbol.
            target_percent (float): Target percent of total equity (e.g. 0.2 = 20%, 0.0 = close position).
        """
        self.engine.place_target_percent_order(
            ticker, target_percent, time=self.current_time
        )

    def I(self, func: Callable[..., pd.Series], *args, ticker: str = None, **kwargs) -> pd.Series:
        """
        Khai báo và tính toán một chỉ báo (Indicator) trên toàn bộ tập dữ liệu.
        Phương thức này tính toán theo cơ chế Vectorization (tính 1 lần ở init)
        để tối đa hóa tốc độ Backtest.

        ⚠️ CẢNH BÁO LOOKAHEAD BIAS:
        Vì hàm này tính toán trên toàn bộ chuỗi thời gian (cả quá khứ và tương lai),
        hãy đảm bảo logic của hàm `func` KHÔNG sử dụng dữ liệu tương lai.
        - AN TOÀN: rolling().mean(), ewm(), shift(1)
        - NGUY HIỂM: shift(-1), nội suy giá trị tương lai (forward interpolation).

        Args:
            func: Hàm tính toán chỉ báo (ví dụ: ta.trend.sma_indicator)
            *args: Các tham số vị trí truyền vào func
            ticker: Mã cổ phiếu cụ thể để tính chỉ báo (tùy chọn)
            **kwargs: Các tham số từ khóa truyền vào func

        Returns:
            pd.Series: Chuỗi giá trị của chỉ báo.
        """
        # Xác định ticker và tham số truyền vào hàm
        if ticker is None and args and isinstance(args[0], str) and isinstance(self.data, dict) and args[0] in self.data:
            ticker = args[0]
            func_args = args[1:]
        elif ticker is None:
            if isinstance(self.data, dict):
                ticker = getattr(self.engine, "main_ticker", list(self.data.keys())[0])
            else:
                ticker = None
            func_args = args
        else:
            func_args = args

        df = self.data[ticker] if ticker and isinstance(self.data, dict) else self.data

        # Redirect indicators from Close to Adj_Close if adjusted price columns are available
        if "Adj_Close" in df.columns and "column" not in kwargs:
            try:
                import inspect
                sig = inspect.signature(func)
                if "column" in sig.parameters:
                    param_names = list(sig.parameters.keys())
                    col_idx = param_names.index("column") - 1  # skip first arg (df)
                    if len(func_args) <= col_idx:
                        kwargs["column"] = "Adj_Close"
                        logger.debug("Tự động chuyển nguồn dữ liệu chỉ báo sang cột 'Adj_Close'.")
            except Exception:
                if len(func_args) < 2:
                    kwargs["column"] = "Adj_Close"
        elif "Adj_Close" in df.columns and "column" in kwargs:
            if kwargs["column"] == "Close":
                kwargs["column"] = "Adj_Close"
                logger.debug("Tự động chuyển nguồn dữ liệu chỉ báo sang cột 'Adj_Close'.")

        indicator_series = func(df, *func_args, **kwargs)

        if not isinstance(indicator_series, pd.Series):
            raise TypeError(
                f"Hàm indicator '{func.__name__ if hasattr(func, '__name__') else str(func)}' phải trả về pd.Series, "
                f"nhưng đã trả về {type(indicator_series).__name__}."
            )

        self._indicators.append(indicator_series)
        return indicator_series

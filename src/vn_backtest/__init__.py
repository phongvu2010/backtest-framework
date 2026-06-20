import logging

from .strategy import Strategy
from .engine import BacktestEngine
from .analysis import PerformanceAnalyzer
from .reporter import ReportGenerator
from .optimizer import ParameterOptimizer

__all__ = [
    "Strategy",
    "BacktestEngine",
    "PerformanceAnalyzer",
    "ReportGenerator",
    "ParameterOptimizer",
]

# Thiết lập Logger mặc định cho toàn bộ thư viện là NullHandler
# Điều này đảm bảo thư viện sẽ không tự động in bất kỳ thứ gì ra màn hình
# trừ khi người dùng chủ động cấu hình logging ở phía ứng dụng của họ.
logging.getLogger("vn_backtest").addHandler(logging.NullHandler())

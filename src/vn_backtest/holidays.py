import datetime
import pandas as pd
from typing import Union, List, Set
import holidays


class VietnamMarketCalendar:
    """
    Manages Vietnamese stock market trading holidays (HOSE, HNX, UPCoM)
    using the Python 'holidays' library.
    Handles weekends, public holidays, and compensation days.
    """

    def __init__(self, start_year: int = 2015, end_year: int = 2030):
        self.start_year = start_year
        self.end_year = end_year
        # Generate the holidays set using the holidays library
        self.vn_holidays = holidays.VN(years=list(range(start_year, end_year + 1)))

    def is_holiday(self, date: Union[str, pd.Timestamp, datetime.date]) -> bool:
        """Check if a specific date is a stock market holiday or weekend."""
        ts = pd.to_datetime(date).normalize()
        if ts.dayofweek >= 5:  # Saturday or Sunday
            return True
        # Convert to datetime.date for holidays library lookup
        py_date = ts.to_pydatetime().date()
        return py_date in self.vn_holidays

    def is_trading_day(self, date: Union[str, pd.Timestamp]) -> bool:
        """Check if a date is a valid trading day."""
        return not self.is_holiday(date)

    def get_trading_days(self, start_date: Union[str, pd.Timestamp], end_date: Union[str, pd.Timestamp]) -> List[pd.Timestamp]:
        """Generate a list of trading days between start_date and end_date (inclusive)."""
        start = pd.to_datetime(start_date).normalize()
        end = pd.to_datetime(end_date).normalize()
        all_days = pd.date_range(start=start, end=end, freq="D")
        return [day for day in all_days if self.is_trading_day(day)]

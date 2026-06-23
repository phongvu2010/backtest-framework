import logging
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class CorporateActionProcessor:
    """
    Handles corporate actions such as cash dividends, stock dividends/splits,
    rights issues, and adjusts historical stock prices accordingly.
    """

    def __init__(self, engine):
        self.engine = engine

    def detect_if_adjusted(self) -> bool:
        """
        Detect if the input data is already adjusted for splits and dividends.
        Checks historical splits/dividends and counts expected price drops.
        """
        if not self.engine.adjust_corporate_actions:
            return True

        unadjusted_count = 0
        adjusted_count = 0

        for ticker, df in self.engine.data.items():
            events = self.engine.corporate_actions.get(ticker)
            if events is None or events.empty:
                continue

            # Find stock dividends / splits with a significant ratio (> 0.05)
            splits = events[events["exercise_ratio"] > 0.05]
            df_dates_normalized = df.index.normalize()

            for _, event in splits.iterrows():
                if pd.isna(event["exright_date"]):
                    continue
                ex_date = pd.to_datetime(event["exright_date"]).normalize()
                if ex_date in df_dates_normalized:
                    idx_ex = df_dates_normalized.get_loc(ex_date)
                    if idx_ex > 0:
                        close_prev = df["Close"].iloc[idx_ex - 1]
                        close_ex = df["Close"].iloc[idx_ex]
                        ratio = close_ex / close_prev
                        expected_ratio = 1.0 / (1.0 + event["exercise_ratio"])

                        # Price ratio matches expected price drop (unadjusted)
                        if abs(ratio - expected_ratio) < 0.12:
                            unadjusted_count += 1
                        # Price ratio is close to 1.0 (adjusted, meaning no drop)
                        elif abs(ratio - 1.0) < 0.05:
                            adjusted_count += 1

        if unadjusted_count > 0 or adjusted_count > 0:
            logger.info(
                f"Phân tích dữ liệu: phát hiện {unadjusted_count} sự kiện CHƯA điều chỉnh "
                f"và {adjusted_count} sự kiện ĐÃ điều chỉnh."
            )
            return adjusted_count >= unadjusted_count

        # Default to True if no events found
        return True

    def calculate_adjusted_prices(self):
        """
        Calculate adjusted price columns for all tickers.
        If input price data is already adjusted, copy raw columns.
        Otherwise, use backward CRSP adjustment algorithm.
        """
        for ticker, df in self.engine.data.items():
            if self.engine.dividends_already_factored:
                # Copy raw columns
                df["Adj_Open"] = df["Open"]
                df["Adj_High"] = df["High"]
                df["Adj_Low"] = df["Low"]
                df["Adj_Close"] = df["Close"]
                if "Average" in df.columns:
                    df["Adj_Average"] = df["Average"]
            else:
                # Initialize adjusted columns with raw values
                df["Adj_Open"] = df["Open"].astype(float)
                df["Adj_High"] = df["High"].astype(float)
                df["Adj_Low"] = df["Low"].astype(float)
                df["Adj_Close"] = df["Close"].astype(float)
                if "Average" in df.columns:
                    df["Adj_Average"] = df["Average"].astype(float)

                events = self.engine.corporate_actions.get(ticker)
                if events is None or events.empty:
                    continue

                events_sorted = events.sort_values("exright_date", ascending=False)
                multipliers = pd.Series(1.0, index=df.index)

                for _, event in events_sorted.iterrows():
                    if pd.isna(event["exright_date"]):
                        continue
                    ex_date = pd.to_datetime(event["exright_date"]).normalize()
                    past_dates = df.index[df.index < ex_date]
                    if past_dates.empty:
                        continue

                    factor = 1.0
                    val_per_share = event.get("value_per_share")
                    exercise_ratio = event.get("exercise_ratio")
                    event_name = event.get("event_name_vi", "")
                    event_title = (
                        event.get("event_title_vi", "")
                        if "event_title_vi" in event.index
                        else ""
                    )

                    is_cash_div = False
                    if pd.notna(val_per_share) and val_per_share > 0:
                        is_cash_div = True
                    elif (
                        "tiền mặt" in str(event_name).lower()
                        or "tiền mặt" in str(event_title).lower()
                    ):
                        is_cash_div = True
                        if pd.isna(val_per_share) or val_per_share == 0:
                            if pd.notna(exercise_ratio) and exercise_ratio > 0:
                                val_per_share = exercise_ratio * 10000.0
                            else:
                                val_per_share = 1000.0

                    is_rights_issue = False
                    if (
                        "quyền mua" in str(event_title).lower()
                        or "quyền mua" in str(event_name).lower()
                    ):
                        is_rights_issue = True

                    if is_cash_div:
                        idx_prev_date = past_dates[-1]
                        close_prev = df.loc[idx_prev_date, "Close"]
                        net_div = val_per_share
                        if close_prev > net_div:
                            factor = (close_prev - net_div) / close_prev
                    elif is_rights_issue:
                        ratio = exercise_ratio if pd.notna(exercise_ratio) else 0.0
                        if ratio > 0:
                            idx_prev_date = past_dates[-1]
                            close_prev = df.loc[idx_prev_date, "Close"]
                            subscription_price = 10000.0
                            if close_prev > subscription_price:
                                factor = (
                                    1.0 + ratio * (subscription_price / close_prev)
                                ) / (1.0 + ratio)
                            else:
                                factor = 1.0
                    else:
                        ratio = exercise_ratio if pd.notna(exercise_ratio) else 0.0
                        if ratio > 0:
                            factor = 1.0 / (1.0 + ratio)

                    multipliers.loc[past_dates] *= factor

                df["Adj_Open"] = df["Adj_Open"] * multipliers
                df["Adj_High"] = df["Adj_High"] * multipliers
                df["Adj_Low"] = df["Adj_Low"] * multipliers
                df["Adj_Close"] = df["Adj_Close"] * multipliers
                if "Average" in df.columns:
                    df["Adj_Average"] = df["Adj_Average"] * multipliers

    def process_corporate_actions(self, current_time: pd.Timestamp, current_idx: int):
        """Process stock splits, stock dividends, and cash dividends."""
        norm_time = current_time.normalize()

        # 1. Check pending cash dividends payout
        active_pending = []
        for item in self.engine.pending_dividends:
            payout_dt = item["payout_date"]
            if payout_dt.tz is not None:
                payout_dt = payout_dt.tz_localize(None)
            payout_dt_norm = payout_dt.normalize()
            if norm_time >= payout_dt_norm:
                amount = item["amount"]
                tax = amount * self.engine.dividend_tax_rate
                net_amount = amount - tax

                self.engine.cash += net_amount

                # Log trade record
                self.engine.trades_history.append(
                    {
                        "Date": current_time,
                        "Ticker": item["ticker"],
                        "Action": "DIVIDEND_CASH",
                        "Quantity": 0,
                        "Price": 0.0,
                        "Value": amount,
                        "Fee": 0.0,
                        "Tax": tax,
                        "TotalValue": net_amount,
                        "TimePlaced": current_time,
                        "Note": f"Nhận cổ tức tiền mặt cho {item['ticker']} (Tổng: {amount:,.0f} VND, Thuế {self.engine.dividend_tax_rate*100:.1f}%: {tax:,.0f} VND, Thực nhận: {net_amount:,.0f} VND)",
                    }
                )
                self.engine.order_logs.append(
                    {
                        "Date": current_time,
                        "Ticker": item["ticker"],
                        "Action": "DIVIDEND_PAID",
                        "Reason": f"Nhận cổ tức tiền mặt ({amount:,.0f}đ, sau thuế {self.engine.dividend_tax_rate*100:.1f}%: {net_amount:,.0f}đ)",
                        "Price": 0.0,
                        "Quantity": 0,
                    }
                )
            else:
                active_pending.append(item)
        self.engine.pending_dividends = active_pending

        # 2. Check for new ex-right events today
        events_all = self.engine.corporate_actions_by_date.get(norm_time, [])
        if not events_all:
            return

        for ticker in self.engine.data:
            events_today = [ev for t, ev in events_all if t == ticker]
            if not events_today:
                continue

            for event in events_today:
                qty = self.engine.positions.get(ticker, 0)
                if qty <= 0:
                    continue

                val_per_share = event.get("value_per_share")
                exercise_ratio = event.get("exercise_ratio")
                event_name = event.get("event_name_vi", "")
                event_title = (
                    event.get("event_title_vi", "")
                    if "event_title_vi" in event.index
                    else ""
                )

                # Check for Cash Dividend
                is_cash_div = False
                if pd.notna(val_per_share) and val_per_share > 0:
                    is_cash_div = True
                elif (
                    "tiền mặt" in str(event_name).lower()
                    or "tiền mặt" in str(event_title).lower()
                ):
                    is_cash_div = True
                    if pd.isna(val_per_share) or val_per_share == 0:
                        # Fallback: estimate 10% par value if exercise_ratio is present
                        if pd.notna(exercise_ratio) and exercise_ratio > 0:
                            val_per_share = exercise_ratio * 10000.0
                        else:
                            val_per_share = 1000.0  # Standard fallback

                if is_cash_div:
                    payout_val = val_per_share if pd.notna(val_per_share) else 1000.0
                    dividend_cash = qty * payout_val
                    payout_date = event.get("payout_date")
                    if pd.isna(payout_date) or payout_date is None:
                        payout_date = current_time + pd.Timedelta(days=15)
                    else:
                        payout_date = pd.to_datetime(payout_date)
                        if payout_date.tz is not None:
                            payout_date = payout_date.tz_localize(None)

                    self.engine.pending_dividends.append(
                        {
                            "amount": dividend_cash,
                            "payout_date": payout_date,
                            "ticker": ticker,
                        }
                    )

                    self.engine.order_logs.append(
                        {
                            "Date": current_time,
                            "Ticker": ticker,
                            "Action": "DIVIDEND_ACCRUED",
                            "Reason": f"Chốt quyền nhận cổ tức tiền mặt ({payout_val:,.0f}đ/CP, thanh toán ngày {payout_date.strftime('%d/%m/%Y')})",
                            "Price": payout_val,
                            "Quantity": qty,
                        }
                    )

                    # Adjust risk management prices for cash dividend ex-rights price drop
                    if not self.engine.dividends_already_factored:
                        close_prev = (
                            self.engine.data[ticker].iloc[current_idx - 1]["Close"]
                            if current_idx > 0
                            else payout_val
                        )
                        if close_prev > payout_val:
                            factor = (close_prev - payout_val) / close_prev
                            if ticker in self.engine.position_entry_price:
                                self.engine.position_entry_price[ticker] *= factor
                            if ticker in self.engine.position_highest_price:
                                self.engine.position_highest_price[ticker] *= factor

                # Check for Rights Offering (Quyền mua phát hành thêm)
                elif not self.engine.dividends_already_factored and (
                    "quyền mua" in str(event_title).lower()
                    or "quyền mua" in str(event_name).lower()
                ):
                    ratio = exercise_ratio if pd.notna(exercise_ratio) else 0.0
                    if ratio > 0:
                        # Adjust risk management prices for dilution from rights issue ex-rights price drop
                        close_prev = (
                            self.engine.data[ticker].iloc[current_idx - 1]["Close"]
                            if current_idx > 0
                            else 10000.0
                        )
                        if close_prev > 10000.0:
                            factor = (close_prev + ratio * 10000.0) / (
                                close_prev * (1.0 + ratio)
                            )
                            if ticker in self.engine.position_entry_price:
                                self.engine.position_entry_price[ticker] *= factor
                            if ticker in self.engine.position_highest_price:
                                self.engine.position_highest_price[ticker] *= factor

                        new_shares = int(qty * ratio)
                        if new_shares > 0:
                            # Check if market price is above subscription price (usually 10,000 VND)
                            subscription_price = 10000.0
                            ticker_df = self.engine.data[ticker]
                            current_price = (
                                ticker_df.loc[current_time, "Close"]
                                if current_time in ticker_df.index
                                else subscription_price
                            )

                            if current_price > subscription_price:
                                cash_needed = new_shares * subscription_price

                                # Check cash restriction
                                can_exercise = True
                                if self.engine.margin_ratio >= 1.0 and cash_needed > self.engine.cash:
                                    # Limit new shares to cash capacity if margin not allowed
                                    max_buyable = int(self.engine.cash // subscription_price)
                                    if max_buyable > 0:
                                        new_shares = min(new_shares, max_buyable)
                                        cash_needed = new_shares * subscription_price
                                    else:
                                        can_exercise = False

                                if can_exercise:
                                    # Determine unlock date (usually listing date or self.rights_listing_delay days)
                                    unlock_date = event.get("listing_date")
                                    if pd.isna(unlock_date) or unlock_date is None:
                                        unlock_date = event.get("payout_date")
                                    if pd.isna(unlock_date) or unlock_date is None:
                                        unlock_date = current_time + pd.Timedelta(
                                            days=self.engine.rights_listing_delay
                                        )
                                    else:
                                        unlock_date = pd.to_datetime(unlock_date)
                                        if unlock_date.tz is not None:
                                            unlock_date = unlock_date.tz_localize(None)

                                    unlock_idx = current_idx + int(
                                        self.engine.rights_listing_delay * 5 / 7
                                    )
                                    for future_idx in range(
                                        current_idx, len(self.engine.dates)
                                    ):
                                        target_dt = self.engine.dates[future_idx]
                                        if target_dt.tz is not None:
                                            target_dt = target_dt.tz_localize(None)
                                        if target_dt >= unlock_date:
                                            unlock_idx = future_idx
                                            break

                                    self.engine.positions[ticker] = (
                                        self.engine.positions.get(ticker, 0) + new_shares
                                    )

                                    self.engine.settlement_queue.append(
                                        {
                                            "ticker": ticker,
                                            "quantity": new_shares,
                                            "settle_idx": unlock_idx,
                                        }
                                    )

                                    self.engine.trades_history.append(
                                        {
                                            "Date": current_time,
                                            "Ticker": ticker,
                                            "Action": "RIGHTS_EXERCISED",
                                            "Quantity": new_shares,
                                            "Price": subscription_price,
                                            "Value": cash_needed,
                                            "Fee": 0.0,
                                            "Tax": 0.0,
                                            "TotalValue": cash_needed,
                                            "TimePlaced": current_time,
                                            "Note": f"Thực hiện quyền mua tỉ lệ {ratio*100:.1f}% giá {subscription_price:,.0f}đ (-{cash_needed:,.0f} VND, +{new_shares} CP, mở khóa ngày {self.engine.dates[min(unlock_idx, len(self.engine.dates)-1)].strftime('%d/%m/%Y')})",
                                        }
                                    )
                                    self.engine.order_logs.append(
                                        {
                                            "Date": current_time,
                                            "Ticker": ticker,
                                            "Action": "RIGHTS_EXERCISED",
                                            "Reason": f"Thực hiện quyền mua (+{new_shares} CP @ {subscription_price:,.0f}đ)",
                                            "Price": subscription_price,
                                            "Quantity": new_shares,
                                        }
                                    )
                                else:
                                    self.engine.order_logs.append(
                                        {
                                            "Date": current_time,
                                            "Ticker": ticker,
                                            "Action": "RIGHTS_LAPSED",
                                            "Reason": "Insufficient cash to exercise rights",
                                            "Price": subscription_price,
                                            "Quantity": 0,
                                        }
                                    )
                            else:
                                self.engine.order_logs.append(
                                    {
                                        "Date": current_time,
                                        "Ticker": ticker,
                                        "Action": "RIGHTS_LAPSED",
                                        "Reason": f"Market price ({current_price:,.0f}đ) <= rights price ({subscription_price:,.0f}đ)",
                                        "Price": subscription_price,
                                        "Quantity": 0,
                                    }
                                )
                # Check for Stock Dividend / Share Issue (free)
                elif not self.engine.dividends_already_factored:
                    ratio = exercise_ratio if pd.notna(exercise_ratio) else 0.0
                    if ratio > 0:
                        # Adjust risk management prices for stock dividend ex-rights price drop
                        factor = 1.0 / (1.0 + ratio)
                        if ticker in self.engine.position_entry_price:
                            self.engine.position_entry_price[ticker] *= factor
                        if ticker in self.engine.position_highest_price:
                            self.engine.position_highest_price[ticker] *= factor

                        new_shares = int(qty * ratio)
                        if new_shares > 0:
                            self.engine.positions[ticker] = (
                                self.engine.positions.get(ticker, 0) + new_shares
                            )
                            self.engine.dividend_shares[ticker] = (
                                self.engine.dividend_shares.get(ticker, 0) + new_shares
                            )

                            # Determine unlock date
                            unlock_date = event.get("listing_date")
                            if pd.isna(unlock_date) or unlock_date is None:
                                unlock_date = event.get("payout_date")
                            if pd.isna(unlock_date) or unlock_date is None:
                                unlock_date = current_time + pd.Timedelta(
                                    days=self.engine.rights_listing_delay
                                )
                            else:
                                unlock_date = pd.to_datetime(unlock_date)
                                if unlock_date.tz is not None:
                                    unlock_date = unlock_date.tz_localize(None)

                            # Map unlock_date to trading day index
                            unlock_idx = current_idx + int(
                                self.engine.rights_listing_delay * 5 / 7
                            )
                            for future_idx in range(current_idx, len(self.engine.dates)):
                                target_dt = self.engine.dates[future_idx]
                                if target_dt.tz is not None:
                                    target_dt = target_dt.tz_localize(None)
                                if target_dt >= unlock_date:
                                    unlock_idx = future_idx
                                    break

                            self.engine.settlement_queue.append(
                                {
                                    "ticker": ticker,
                                    "quantity": new_shares,
                                    "settle_idx": unlock_idx,
                                }
                            )

                            self.engine.trades_history.append(
                                {
                                    "Date": current_time,
                                    "Ticker": ticker,
                                    "Action": "DIVIDEND_STOCK",
                                    "Quantity": new_shares,
                                    "Price": 0.0,
                                    "Value": 0.0,
                                    "Fee": 0.0,
                                    "Tax": 0.0,
                                    "TotalValue": 0.0,
                                    "TimePlaced": current_time,
                                    "Note": f"Nhận cổ tức cổ phiếu tỉ lệ {ratio*100:.1f}% (+{new_shares} CP, mở khóa ngày {self.engine.dates[min(unlock_idx, len(self.engine.dates)-1)].strftime('%d/%m/%Y')})",
                                }
                            )
                            self.engine.order_logs.append(
                                {
                                    "Date": current_time,
                                    "Ticker": ticker,
                                    "Action": "DIVIDEND_STOCK_FILLED",
                                    "Reason": f"Nhận cổ tức cổ phiếu (+{new_shares} CP)",
                                    "Price": 0.0,
                                    "Quantity": new_shares,
                                }
                            )

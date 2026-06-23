import os
import jinja2
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio
from typing import Dict, Any, Union

try:
    from markupsafe import Markup
except ImportError:
    from jinja2 import Markup

# Use dark template for Plotly by default
pio.templates.default = "plotly_dark"

# Khởi tạo Jinja2 Environment lấy từ thư mục templates cục bộ
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
_JINJA_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
    autoescape=True,
    undefined=jinja2.StrictUndefined,
)


class ReportGenerator:
    """
    Generates a premium, interactive HTML report for the backtest results.
    Includes performance metrics dashboard, equity curve, drawdown, and trade signals.
    """

    def __init__(self, output_dir: str = "reports"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def _generate_plotly_html(
        self,
        equity_df: pd.DataFrame,
        trades_df: pd.DataFrame,
        stock_df: Union[pd.DataFrame, Dict[str, pd.DataFrame]],
        benchmark_df: Union[pd.DataFrame, Dict[str, pd.DataFrame]] = None,
        benchmark_symbol: str = "VNINDEX",
    ) -> tuple[str, str, str, str]:
        """Create the interactive Plotly figures and return their HTML snippets."""
        # 1. Chart 1: Equity Curve vs Benchmark (Normalized to 100)
        fig_equity = go.Figure()

        # Strategy normalized equity
        strategy_normalized = (equity_df["Equity"] / equity_df["Equity"].iloc[0]) * 100
        fig_equity.add_trace(
            go.Scatter(
                x=strategy_normalized.index,
                y=strategy_normalized,
                name="Chiến lược (VN-Backtest)",
                line=dict(color="#00ffcc", width=3),
                fill="tozeroy",
                fillcolor="rgba(0, 255, 204, 0.05)",
            )
        )

        # Benchmark normalized equity (supports DataFrame or Dict of DataFrames)
        if benchmark_df is not None:
            benchmarks_to_plot = {}
            if isinstance(benchmark_df, dict):
                benchmarks_to_plot = benchmark_df
            elif isinstance(benchmark_df, pd.DataFrame) and not benchmark_df.empty:
                benchmarks_to_plot = {benchmark_symbol: benchmark_df}

            for bench_name, df_bench in benchmarks_to_plot.items():
                if df_bench.empty:
                    continue
                # Drop timezone information if present
                bench_close = df_bench["Close"].copy()
                bench_close.index = (
                    bench_close.index.tz_localize(None)
                    if bench_close.index.tz is not None
                    else bench_close.index
                )
                strategy_index = (
                    equity_df.index.tz_localize(None)
                    if equity_df.index.tz is not None
                    else equity_df.index
                )

                bench_close_aligned = (
                    bench_close.reindex(strategy_index).ffill().bfill()
                )
                bench_normalized = (
                    bench_close_aligned / bench_close_aligned.iloc[0]
                ) * 100
                fig_equity.add_trace(
                    go.Scatter(
                        x=bench_normalized.index,
                        y=bench_normalized,
                        name=f"Benchmark ({bench_name})",
                        line=dict(width=2, dash="dash"),
                    )
                )

        fig_equity.update_layout(
            title="<b>TĂNG TRƯỞNG TÀI SẢN TÍCH LŨY (Chuẩn hóa về 100)</b>",
            xaxis_title="Ngày",
            yaxis_title="Giá trị tài sản (%)",
            hovermode="x unified",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(x=0.01, y=0.99, bgcolor="rgba(15, 23, 42, 0.8)"),
            margin=dict(l=20, r=20, t=50, b=20),
            height=450,
        )
        fig_equity.update_xaxes(showgrid=True, gridcolor="rgba(255,255,255,0.05)")
        fig_equity.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.05)")

        # 2. Chart 2: Drawdown Area Chart
        fig_dd = go.Figure()
        running_max = equity_df["Equity"].cummax()
        drawdown = ((equity_df["Equity"] - running_max) / running_max) * 100

        fig_dd.add_trace(
            go.Scatter(
                x=drawdown.index,
                y=drawdown,
                name="Sụt giảm (Drawdown)",
                line=dict(color="#ff4d4d", width=1.5),
                fill="tozeroy",
                fillcolor="rgba(255, 77, 77, 0.15)",
            )
        )

        fig_dd.update_layout(
            title="<b>MỨC SỤT GIẢM TÀI SẢN (Drawdown %)</b>",
            xaxis_title="Ngày",
            yaxis_title="Sụt giảm (%)",
            hovermode="x unified",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=20, r=20, t=50, b=20),
            height=250,
        )
        fig_dd.update_xaxes(showgrid=True, gridcolor="rgba(255,255,255,0.05)")
        fig_dd.update_yaxes(
            showgrid=True, gridcolor="rgba(255,255,255,0.05)", range=[-100, 5]
        )

        # 3. Chart 3: Stock Close Price & Buy/Sell Signals (with Interactive Ticker Dropdown)
        fig_signals = go.Figure()

        if isinstance(stock_df, dict):
            tickers = list(stock_df.keys())
        else:
            tickers = ["PORTFOLIO"]
            stock_df = {"PORTFOLIO": stock_df}

        ticker_trace_indices = {}
        trace_idx = 0

        for i, ticker in enumerate(tickers):
            ticker_trace_indices[ticker] = []
            df = stock_df[ticker]
            df_no_tz = df.copy()
            df_no_tz.index = (
                df_no_tz.index.tz_localize(None)
                if df_no_tz.index.tz is not None
                else df_no_tz.index
            )

            # Close Price Trace
            fig_signals.add_trace(
                go.Scatter(
                    x=df_no_tz.index,
                    y=df_no_tz["Close"],
                    name=f"Giá đóng cửa {ticker}",
                    line=dict(width=2, color="#3b82f6" if len(tickers) == 1 else None),
                    opacity=0.8,
                    visible=(i == 0),
                )
            )
            ticker_trace_indices[ticker].append(trace_idx)
            trace_idx += 1

            # Buy/Sell Signals Traces
            if not trades_df.empty:
                trades_df_no_tz = trades_df.copy()
                trades_df_no_tz["Date"] = pd.to_datetime(trades_df_no_tz["Date"])
                if trades_df_no_tz["Date"].dt.tz is not None:
                    trades_df_no_tz["Date"] = trades_df_no_tz["Date"].dt.tz_localize(
                        None
                    )

                ticker_trades = trades_df_no_tz[trades_df_no_tz["Ticker"] == ticker]
                buys = ticker_trades[ticker_trades["Action"] == "BUY"]
                sells = ticker_trades[ticker_trades["Action"] == "SELL"]

                # Add Buy markers
                fig_signals.add_trace(
                    go.Scatter(
                        x=buys["Date"] if not buys.empty else [],
                        y=buys["Price"] if not buys.empty else [],
                        mode="markers",
                        name=f"MUA ({ticker})",
                        marker=dict(
                            symbol="triangle-up",
                            size=12,
                            color="#00ff00",
                            line=dict(color="#052e16", width=1.5),
                        ),
                        text=(
                            [
                                f"Mua: {q} CP @ {p:,.0f}"
                                for q, p in zip(buys["Quantity"], buys["Price"])
                            ]
                            if not buys.empty
                            else []
                        ),
                        hoverinfo="text+x",
                        visible=(i == 0),
                    )
                )
                ticker_trace_indices[ticker].append(trace_idx)
                trace_idx += 1

                # Add Sell markers
                fig_signals.add_trace(
                    go.Scatter(
                        x=sells["Date"] if not sells.empty else [],
                        y=sells["Price"] if not sells.empty else [],
                        mode="markers",
                        name=f"BÁN ({ticker})",
                        marker=dict(
                            symbol="triangle-down",
                            size=12,
                            color="#ff0000",
                            line=dict(color="#450a0a", width=1.5),
                        ),
                        text=(
                            [
                                f"Bán: {q} CP @ {p:,.0f}"
                                for q, p in zip(sells["Quantity"], sells["Price"])
                            ]
                            if not sells.empty
                            else []
                        ),
                        hoverinfo="text+x",
                        visible=(i == 0),
                    )
                )
                ticker_trace_indices[ticker].append(trace_idx)
                trace_idx += 1
            else:
                # Add empty traces to keep structure consistent
                fig_signals.add_trace(
                    go.Scatter(
                        x=[],
                        y=[],
                        mode="markers",
                        name=f"MUA ({ticker})",
                        visible=(i == 0),
                    )
                )
                ticker_trace_indices[ticker].append(trace_idx)
                trace_idx += 1
                fig_signals.add_trace(
                    go.Scatter(
                        x=[],
                        y=[],
                        mode="markers",
                        name=f"BÁN ({ticker})",
                        visible=(i == 0),
                    )
                )
                ticker_trace_indices[ticker].append(trace_idx)
                trace_idx += 1

        # Generate dropdown menu buttons
        updatemenus = []
        if len(tickers) > 1:
            buttons = []
            total_traces = len(fig_signals.data)
            for i, ticker in enumerate(tickers):
                visibility = [False] * total_traces
                for idx in ticker_trace_indices[ticker]:
                    visibility[idx] = True

                button = dict(
                    label=ticker,
                    method="update",
                    args=[
                        {"visible": visibility},
                        {"title": f"<b>ĐIỂM GIAO DỊCH TRÊN ĐỒ THỊ GIÁ: {ticker}</b>"},
                    ],
                )
                buttons.append(button)

            updatemenus = [
                dict(
                    buttons=buttons,
                    direction="down",
                    pad={"r": 10, "t": 10},
                    showactive=True,
                    x=0.01,
                    xanchor="left",
                    y=1.15,
                    yanchor="top",
                    bgcolor="rgba(15, 23, 42, 0.9)",
                    bordercolor="rgba(255, 255, 255, 0.15)",
                    font=dict(color="#f3f4f6"),
                )
            ]

        fig_signals.update_layout(
            title=f"<b>ĐIỂM GIAO DỊCH TRÊN ĐỒ THỊ GIÁ: {tickers[0]}</b>",
            xaxis_title="Ngày",
            yaxis_title="Giá (VND)",
            hovermode="x unified",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(x=0.01, y=0.99, bgcolor="rgba(15, 23, 42, 0.8)"),
            margin=dict(l=20, r=20, t=80, b=20),
            height=480,
            updatemenus=updatemenus,
        )
        fig_signals.update_xaxes(showgrid=True, gridcolor="rgba(255,255,255,0.05)")
        fig_signals.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.05)")

        # 4. Chart 4: Asset Allocation Stacked Area Chart
        fig_alloc = go.Figure()
        pos_cols = [col for col in equity_df.columns if col.startswith("Val_")]
        total_equity = equity_df["Equity"]

        # Split Cash and Margin Debt
        cash_only = equity_df["Cash"].clip(lower=0)
        margin_debt = equity_df["Cash"].clip(upper=0)

        cash_pct = (cash_only / total_equity) * 100
        margin_pct = (margin_debt / total_equity) * 100

        # Draw Margin Debt (negative, stackgroup="two")
        fig_alloc.add_trace(
            go.Scatter(
                x=equity_df.index,
                y=margin_pct,
                name="NỢ MARGIN (Margin Debt)",
                stackgroup="two",
                mode="lines",
                line=dict(width=0.5, color="#ef4444"),
                fillcolor="rgba(239, 68, 68, 0.2)",
            )
        )

        # Draw Cash (positive, stackgroup="one")
        fig_alloc.add_trace(
            go.Scatter(
                x=equity_df.index,
                y=cash_pct,
                name="TIỀN MẶT (Cash)",
                stackgroup="one",
                mode="lines",
                line=dict(width=0.5, color="#9ca3af"),
                fillcolor="rgba(156, 163, 175, 0.25)",
            )
        )

        for col in pos_cols:
            ticker_name = col.replace("Val_", "")
            val_pct = (equity_df[col] / total_equity) * 100
            fig_alloc.add_trace(
                go.Scatter(
                    x=equity_df.index,
                    y=val_pct,
                    name=ticker_name,
                    stackgroup="one",
                    mode="lines",
                    line=dict(width=0.5),
                )
            )

        fig_alloc.update_layout(
            title="<b>PHÂN BỔ TỶ TRỌNG TÀI SẢN THEO THỜI GIAN (%)</b>",
            xaxis_title="Ngày",
            yaxis_title="Tỷ trọng (%)",
            hovermode="x unified",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(x=0.01, y=0.99, bgcolor="rgba(15, 23, 42, 0.8)"),
            margin=dict(l=20, r=20, t=50, b=20),
            height=320,
            yaxis=dict(ticksuffix="%"),
        )
        fig_alloc.update_xaxes(showgrid=True, gridcolor="rgba(255,255,255,0.05)")
        fig_alloc.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.05)")

        # Convert to HTML snippets (div tags)
        equity_html = pio.to_html(fig_equity, include_plotlyjs=False, full_html=False)
        dd_html = pio.to_html(fig_dd, include_plotlyjs=False, full_html=False)
        signals_html = pio.to_html(fig_signals, include_plotlyjs=False, full_html=False)
        allocation_html = pio.to_html(
            fig_alloc, include_plotlyjs=False, full_html=False
        )

        return equity_html, dd_html, signals_html, allocation_html

    def generate_report(
        self,
        metrics: Dict[str, Any],
        equity_curve: pd.DataFrame,
        trades: pd.DataFrame,
        stock_data: Union[pd.DataFrame, Dict[str, pd.DataFrame]],
        ticker: str,
        strategy_name: str,
        benchmark_data: Union[pd.DataFrame, Dict[str, pd.DataFrame]] = None,
        filename: str = "backtest_report.html",
        benchmark_symbol: str = "VNINDEX",
    ) -> str:
        """
        Generate the beautiful, fully-styled HTML report.

        Returns:
            str: Path to the generated report file.
        """
        # Generate chart HTML snippets
        equity_chart, dd_chart, signals_chart, allocation_chart = (
            self._generate_plotly_html(
                equity_curve, trades, stock_data, benchmark_data, benchmark_symbol
            )
        )

        # Prepare HTML template variables
        report_title = f"Báo cáo Backtest: {ticker} - {strategy_name}"

        # Convert trades to a list of dicts for rendering, limit to last 100 for size
        trades_list = []
        if not trades.empty:
            # Filter out daily margin interest logs to avoid flooding the trade history table
            real_trades = trades[trades["Action"] != "MARGIN_INTEREST"]
            trades_sorted = real_trades.sort_values("Date", ascending=False)
            for idx, r in trades_sorted.iterrows():
                note = r["Note"] if "Note" in r.index and pd.notna(r["Note"]) else ""
                trades_list.append(
                    {
                        "date": r["Date"].strftime("%d/%m/%Y"),
                        "ticker": r["Ticker"],
                        "action": r["Action"],
                        "qty": f"{r['Quantity']:,}",
                        "price": f"{r['Price']:.2f}",
                        "val": (
                            f"{r['Value']:,.0f}"
                            if r["Value"] > 1000
                            else f"{r['Value']:.2f}"
                        ),
                        "fee": f"{r['Fee']:.2f}",
                        "tax": f"{r['Tax']:.2f}",
                        "total": (
                            f"{r['TotalValue']:,.0f}"
                            if r["TotalValue"] > 1000
                            else f"{r['TotalValue']:.2f}"
                        ),
                        "note": note,
                    }
                )

        # Calculate ticker performance summary
        completed_trades = metrics.get("completed_trades", [])
        ticker_summary = []
        if completed_trades:
            df_comp = pd.DataFrame(completed_trades)
            for tk, g in df_comp.groupby("ticker"):
                wins = g[g["profit"] > 0]
                total_pnl = g["profit"].sum()
                win_rate = len(wins) / len(g) if len(g) > 0 else 0.0
                avg_ret = g["return"].mean()
                best_ret = g["return"].max()
                worst_ret = g["return"].min()
                ticker_summary.append(
                    {
                        "ticker": tk,
                        "total_trades": len(g),
                        "win_rate": f"{win_rate * 100:.1f}%",
                        "pnl": f"{total_pnl:,.0f} VND",
                        "pnl_raw": total_pnl,
                        "avg_return": f"{avg_ret * 100:.2f}%",
                        "best_trade": f"{best_ret * 100:.2f}%",
                        "worst_trade": f"{worst_ret * 100:.2f}%",
                    }
                )

        # Read external template files from Jinja2 Environment
        template = _JINJA_ENV.get_template("backtest_report.html")
        html_content = template.render(
            title=report_title,
            ticker=ticker,
            strategy_name=strategy_name,
            metrics=metrics,
            trades=trades_list[:100],  # Show last 100 trades in table
            total_trades_count=len(trades_list),
            equity_chart=Markup(equity_chart),
            dd_chart=Markup(dd_chart),
            signals_chart=Markup(signals_chart),
            allocation_chart=Markup(allocation_chart),
            ticker_summary=ticker_summary,
            benchmark_symbol=benchmark_symbol,
        )

        output_path = os.path.join(self.output_dir, filename)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return output_path

    def generate_optimization_report(
        self,
        results_df: pd.DataFrame,
        ticker: str,
        strategy_name: str,
        filename: str = "backtest_opt_report.html",
    ) -> str:
        """Loads HTML template from external file and generates the parameter optimization leaderboard."""
        # 1. Identify parameter columns vs metric columns
        metric_cols = {
            "total_return",
            "cagr",
            "sharpe_ratio",
            "sortino_ratio",
            "calmar_ratio",
            "recovery_factor",
            "information_ratio",
            "expectancy",
            "max_drawdown",
            "win_rate",
            "profit_factor",
            "total_trades",
            "is_bankrupt",
        }
        param_cols = [col for col in results_df.columns if col not in metric_cols]

        # Sort results by Sharpe Ratio descending
        results_sorted = results_df.sort_values(by="sharpe_ratio", ascending=False)
        best_row = results_sorted.iloc[0]

        # Prepare parameters description for best config
        best_params_str = ", ".join([f"{p}={best_row[p]}" for p in param_cols])

        # 2. Draw Plotly visualization based on number of parameter columns
        fig_opt = go.Figure()

        if len(param_cols) == 2:
            p1 = param_cols[0]
            p2 = param_cols[1]

            # Construct a pivot table for the heatmap
            pivot_df = results_df.pivot_table(
                index=p1, columns=p2, values="sharpe_ratio", aggfunc="mean"
            )

            fig_opt.add_trace(
                go.Heatmap(
                    x=pivot_df.columns,
                    y=pivot_df.index,
                    z=pivot_df.values,
                    colorscale="Viridis",
                    colorbar=dict(title="Sharpe Ratio"),
                    hovertemplate=f"{p2}: %{{x}}<br>{p1}: %{{y}}<br>Sharpe: %{{z:.2f}}<extra></extra>",
                )
            )

            fig_opt.update_layout(
                title=f"<b>BẢN ĐỒ NHIỆT SHARPE RATIO ({p1.upper()} vs {p2.upper()})</b>",
                xaxis_title=p2.upper(),
                yaxis_title=p1.upper(),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=40, r=20, t=50, b=40),
                height=450,
            )
        elif len(param_cols) == 1:
            p1 = param_cols[0]
            df_sorted_p = results_df.sort_values(by=p1)

            fig_opt.add_trace(
                go.Scatter(
                    x=df_sorted_p[p1],
                    y=df_sorted_p["sharpe_ratio"],
                    mode="lines+markers",
                    name="Sharpe Ratio",
                    line=dict(color="#00ffcc", width=3),
                    marker=dict(size=8, color="#3b82f6"),
                )
            )

            fig_opt.update_layout(
                title=f"<b>HIỆU QUẢ SHARPE RATIO THEO THAM SỐ {p1.upper()}</b>",
                xaxis_title=p1.upper(),
                yaxis_title="Sharpe Ratio",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=40, r=20, t=50, b=40),
                height=450,
            )
        else:
            top_n = min(15, len(results_sorted))
            top_df = results_sorted.head(top_n)

            labels = []
            for _, r in top_df.iterrows():
                lbl = ", ".join([f"{p}:{r[p]}" for p in param_cols])
                labels.append(lbl)

            fig_opt.add_trace(
                go.Bar(
                    x=labels,
                    y=top_df["sharpe_ratio"],
                    marker_color="#00ffcc",
                    opacity=0.85,
                )
            )

            fig_opt.update_layout(
                title="<b>BẢNG XẾP HẠNG TOP THAM SỐ (Sharpe Ratio)</b>",
                xaxis_title="Tổ hợp tham số",
                yaxis_title="Sharpe Ratio",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=40, r=20, t=50, b=100),
                height=500,
            )

        opt_chart_html = pio.to_html(fig_opt, include_plotlyjs=False, full_html=False)

        # 3. Format results rows for HTML table
        leaderboard = []
        for idx, (_, r) in enumerate(results_sorted.iterrows(), 1):
            leaderboard.append(
                {
                    "rank": idx,
                    "params": ", ".join([f"{p}={r[p]}" for p in param_cols]),
                    "ret": f"{r['total_return']*100:.2f}%",
                    "cagr": f"{r['cagr']*100:.2f}%",
                    "sharpe": f"{r['sharpe_ratio']:.2f}",
                    "sortino": f"{r['sortino_ratio']:.2f}",
                    "drawdown": f"{r['max_drawdown']*100:.2f}%",
                    "win_rate": f"{r['win_rate']*100:.1f}%",
                    "profit_factor": (
                        f"{r['profit_factor']:.2f}"
                        if r["profit_factor"] != float("inf")
                        else "∞"
                    ),
                    "trades": int(r["total_trades"]),
                }
            )

        best_metrics = {
            "params": best_params_str,
            "total_return": best_row["total_return"],
            "cagr": best_row["cagr"],
            "sharpe_ratio": best_row["sharpe_ratio"],
            "sortino_ratio": best_row["sortino_ratio"],
            "max_drawdown": best_row["max_drawdown"],
            "win_rate": best_row["win_rate"],
            "profit_factor": (
                best_row["profit_factor"]
                if best_row["profit_factor"] != float("inf")
                else 999.0
            ),
            "total_trades": int(best_row["total_trades"]),
        }

        report_title = f"Báo cáo Tối ưu hóa: {ticker} - {strategy_name}"

        # Read external template files from Jinja2 Environment
        template = _JINJA_ENV.get_template("backtest_opt_report.html")
        html_content = template.render(
            title=report_title,
            ticker=ticker,
            strategy_name=strategy_name,
            best=best_metrics,
            leaderboard=leaderboard,
            chart_html=Markup(opt_chart_html),
        )

        output_path = os.path.join(self.output_dir, filename)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return output_path

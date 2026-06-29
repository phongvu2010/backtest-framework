# 📈 vn-backtest

**vn-backtest** là một framework kiểm thử chiến lược giao dịch (backtesting) mã nguồn mở bằng Python, được thiết kế và tối ưu hóa **đặc thù cho Thị trường Chứng khoán Việt Nam (HOSE, HNX, UPCoM)**. 

Thư viện hỗ trợ mô phỏng chính xác các luật giao dịch thực tế của Việt Nam qua các thời kỳ lịch sử, kiểm soát rủi ro Look-Ahead Bias, đồng bộ dòng tiền khả dụng, hỗ trợ ký quỹ (margin), xử lý các sự kiện doanh nghiệp và tạo báo cáo HTML tương tác trực quan cao cấp.

---

## ✨ Tính Năng Nổi Bật

### 1. Đặc Thù Giao Dịch Chứng Khoán Việt Nam
*   ⏱️ **Chu kỳ thanh toán & vòng quay tiền T+1.5 / T+2:** Giả lập chính xác thời gian cổ phiếu về tài khoản (settlement lock) và tiền bán chờ về.
    *   *Lịch sử thay đổi:* Tự động chuyển đổi chu kỳ thanh toán theo mốc lịch sử thực tế (T+3 trước 2016, T+2 trước 29/08/2022 và T+1.5 từ 29/08/2022 trở đi).
*   ⚡ **Mô phỏng Lệnh định kỳ ATO / ATC & Khớp Liên Tục:**
    *   **Lệnh ATO:** Khớp chính xác tại giá mở cửa (`Open`) của ngày thực thi, không áp dụng sai số trượt giá (slippage = 0).
    *   **Lệnh ATC:** Khớp chính xác tại giá đóng cửa (`Close`) của ngày thực thi, không áp dụng sai số trượt giá (slippage = 0).
    *   **Cơ chế hủy phần dư (Fill-or-Kill/Partial Fill Cancel):** Phần khối lượng chưa khớp của lệnh ATO/ATC sẽ tự động hủy ngay sau phiên khớp lệnh định kỳ, không tồn đọng hoặc đẩy lùi sang ngày hôm sau.
    *   **Hủy lệnh khi mất thanh khoản:** Tự động hủy toàn bộ lệnh ATO/ATC nếu mã chứng khoán không phát sinh giao dịch (Volume = 0 hoặc bị tạm ngừng giao dịch) trong ngày thực thi.
*   💸 **Ứng trước tiền bán & Ký quỹ (Margin):**
    *   **Available Cash Sync:** Đồng bộ luồng tiền mặt khả dụng động loại bỏ hoàn toàn hiện tượng lệch dòng tiền (drift) khi đặt lệnh.
    *   **Timezone Alignment:** Tự động chuẩn hóa và loại bỏ múi giờ (timezone-naive) khỏi các dữ liệu lịch sử đầu vào, loại bỏ triệt để lỗi xung đột chỉ mục thời gian khi ghép nối dữ liệu trong Pandas.
    *   **Ứng trước tiền bán:** Tự động tính toán phí ứng trước tiền bán khi bạn thực hiện mua mới trước ngày tiền bán về tài khoản.
    *   **Margin Trading:** Hỗ trợ cấu hình tỷ lệ ký quỹ (`margin_ratio`), lãi suất vay margin năm, tự động cảnh báo ký quỹ (Margin Call) và tự động giải chấp tài khoản (Force Sell) khi tài sản ròng vi phạm tỷ lệ duy trì tối thiểu. Tự động kiểm tra an toàn và log cảnh báo khi lệnh bán giải chấp thất bại do trắng bên mua (Floor Lock).
*   📏 **Quy tắc bước giá (Tick Size) & Lịch sử biên độ dao động:**
    *   **Bước giá động:** Tự động áp dụng bước giá HOSE/HNX/UPCoM (ví dụ: luật bước giá mới của HOSE từ 12/09/2016).
    *   **Biên độ Trần/Sàn lịch sử:** Tự động kiểm tra giá đặt lệnh với giới hạn trần/sàn theo quy định từng sàn qua từng thời kỳ (ví dụ: mốc thay đổi biên độ sàn HOSE từ 5% lên 7%, HNX từ 7% lên 10%).
    *   **Từ chối lệnh do tắc nghẽn thanh khoản:** Từ chối lệnh mua tại giá trần khi trắng bên bán (hoặc bán sàn khi trắng bên mua).
*   🏢 **Sự kiện Doanh nghiệp (Corporate Actions):**
    *   Tự động xử lý điều chỉnh giá và số lượng cổ phiếu cho cổ tức bằng tiền mặt (Cash Dividend), cổ tức bằng cổ phiếu (Stock Dividend), và quyền mua phát hành thêm (Rights Issue).
    *   Khấu trừ thuế thu nhập cá nhân đầu tư chứng khoán **5%** đối với cổ tức theo quy định (Nghị định 126).
    *   Mô phỏng độ trễ niêm yết cổ phiếu thưởng/quyền mua về tài khoản (mặc định 90 ngày).

### 2. Quản Trị Rủi Ro & Phân Tích Kỹ Thuật
*   🛡️ **Tự động phát hiện Look-Ahead Bias:** Cảnh báo đỏ ngay lập tức tại hàm đăng ký chỉ báo `self.I()` nếu phát hiện chỉ báo vô tình tham chiếu dữ liệu tương lai. Hỗ trợ bỏ qua kiểm tra bằng `check_lookahead=False` để tăng tốc độ trong quá trình tối ưu hóa tham số. Hoặc truy cập dữ liệu an toàn qua thuộc tính `self.safe_data`.
*   ⚖️ **Hỗ trợ tỷ lệ đơn vị giá (`price_scale`):** Giải quyết sai lệch tính toán biên độ trần/sàn và bước giá khi nguồn dữ liệu đầu vào sử dụng đơn vị nghìn đồng (ví dụ: giá FPT hiển thị là `85.5` thay vì `85,500` VND từ CafeF/FireAnt).
*   📈 **So sánh đa chỉ số tham chiếu (Multi-Benchmark):** Cho phép truyền nhiều DataFrame chỉ số tham chiếu (như VN-Index, VN30, HNX-Index) để so sánh hiệu quả tăng trưởng tài sản đồng thời, tính toán các chỉ số **Alpha**, **Beta**, **Tracking Error**, và **Information Ratio**.
*   📉 **Đo lường Rủi ro Động (MAE / MFE):** Tự động tính toán mức sụt giảm lớn nhất trong vị thế (**Maximum Adverse Excursion**) và mức lợi nhuận lớn nhất tiềm năng (**Maximum Favorable Excursion**) cho từng vị thế giao dịch đã đóng nhằm hỗ trợ phân tích điểm dừng lỗ/chốt lời tối ưu.
*   📊 **Biểu đồ Phân bổ Tài sản động (Asset Allocation Chart):** Hiển thị trực quan sự thay đổi tỷ trọng phân bổ vốn giữa các mã cổ phiếu, Tiền mặt (Cash) và Nợ Margin (Margin Debt) qua từng ngày dưới dạng Stacked Area.
*   📋 **Báo cáo hiệu suất từng mã (Ticker Performance Summary):** Nhóm các giao dịch đã đóng theo quy tắc FIFO để tính toán các chỉ số chi tiết cho từng mã (Win Rate, Profit Factor, số giao dịch, lệnh thắng/thua lớn nhất).

---

## ⚙️ Cài Đặt

Framework yêu cầu **Python >= 3.12**.

Cài đặt ở chế độ phát triển (development mode):
```bash
git clone https://github.com/phongvu2010/backtest-framework.git
cd vn-backtest
pip install -e .
```

---

## 🚀 Hướng Dẫn Sử Dụng Nhanh (Quick Start)

Dưới đây là ví dụ xây dựng chiến lược giao dịch đa tài sản (HPG, FPT, MWG) sử dụng kết hợp tín hiệu chỉ báo, đặt lệnh ATO/ATC đặc thù, so sánh nhiều chỉ số benchmark và xuất báo cáo HTML cao cấp:

```python
import pandas as pd
from vn_backtest.strategy import Strategy
from vn_backtest.engine import BacktestEngine
from vn_backtest.analysis import PerformanceAnalyzer
from vn_backtest.reporter import ReportGenerator

# 1. Định nghĩa chỉ báo Simple Moving Average (SMA)
def SMA(data, period, column="Close"):
    return data[column].rolling(window=period).mean()

# 2. Xây dựng Chiến lược đa tài sản
class MultiAssetSmaCross(Strategy):
    sma_fast = 10
    sma_slow = 30

    def init(self):
        self.fast_ma = {}
        self.slow_ma = {}
        
        # Đăng ký chỉ báo cho từng mã qua self.I() để tự động kiểm tra Look-Ahead Bias
        for ticker in self.data.keys():
            self.fast_ma[ticker] = self.I(lambda df: SMA(df, self.sma_fast), name=f"Fast_{ticker}")
            self.slow_ma[ticker] = self.I(lambda df: SMA(df, self.sma_slow), name=f"Slow_{ticker}")

    def next(self):
        idx = self.current_idx
        # Bỏ qua các ngày đầu chưa đủ dữ liệu tính toán chỉ báo chậm
        if idx < self.sma_slow:
            return

        for ticker in self.data.keys():
            # Lấy giá trị chỉ báo hiện tại và hôm qua
            fast_curr = self.fast_ma[ticker].iloc[idx]
            fast_prev = self.fast_ma[ticker].iloc[idx - 1]
            slow_curr = self.slow_ma[ticker].iloc[idx]
            slow_prev = self.slow_ma[ticker].iloc[idx - 1]
            
            # Tín hiệu MUA: Đường nhanh cắt lên đường chậm (Golden Cross)
            if fast_prev <= slow_prev and fast_curr > slow_curr:
                # Đặt lệnh MUA ATO (khớp tại Open ngày hôm sau, phân bổ 30% sức mua)
                self.buy(ticker, size=0.3, order_type="ATO")

            # Tín hiệu BÁN: Đường nhanh cắt xuống đường chậm (Death Cross)
            elif fast_prev >= slow_prev and fast_curr < slow_curr:
                # Đặt lệnh BÁN ATC (khớp tại Close ngày hôm sau, bán toàn bộ vị thế đang nắm giữ)
                if self.positions.get(ticker, 0) > 0:
                    self.sell(ticker, order_type="ATC")

# 3. Chuẩn bị dữ liệu OHLCV (Giá chia 1000 từ FireAnt/CafeF)
dates = pd.date_range(start="2023-01-01", periods=100, freq="D")
stock_data = {
    "FPT": pd.DataFrame({"Open": 80.0, "High": 82.0, "Low": 79.0, "Close": 81.0, "Volume": 100000}, index=dates),
    "HPG": pd.DataFrame({"Open": 25.0, "High": 26.0, "Low": 24.5, "Close": 25.5, "Volume": 150000}, index=dates),
    "MWG": pd.DataFrame({"Open": 40.0, "High": 41.5, "Low": 39.5, "Close": 40.5, "Volume": 80000}, index=dates)
}

# 4. Chuẩn bị dữ liệu Benchmark để đối chiếu hiệu quả
benchmarks = {
    "VNINDEX": pd.DataFrame({"Close": 1000.0 + (dates.day * 2)}, index=dates),
    "VN30": pd.DataFrame({"Close": 1010.0 + (dates.day * 1.5)}, index=dates)
}

# 5. Cấu hình và chạy Backtest Engine
engine = BacktestEngine(
    data=stock_data,
    strategy_class=MultiAssetSmaCross,
    initial_cash=100_000_000.0,   # Khởi đầu với 100 triệu VND
    price_scale=1000.0,           # Quy đổi giá đầu vào sang VND thực tế (nhân 1000)
    lot_size=100,                 # Lô chẵn 100 cổ phiếu
    exchange="hose"               # Áp dụng quy tắc sàn HOSE
)

results = engine.run()
equity_df = results["equity_curve"]
trades_df = results["trades"]

# 6. Tính toán thống kê hiệu suất chuyên sâu
metrics = PerformanceAnalyzer.calculate_metrics(
    equity_curve=equity_df,
    trades=trades_df,
    benchmark_data=benchmarks,
    initial_cash=100_000_000.0,
    risk_free_rate=0.04           # Lãi suất phi rủi ro 4%/năm tại Việt Nam
)

# 7. Sinh báo cáo HTML cao cấp dạng tương tác trực quan
reporter = ReportGenerator(output_dir="reports")
report_path = reporter.generate_report(
    metrics=metrics,
    equity_curve=equity_df,
    trades=trades_df,
    stock_data=stock_data,
    ticker="FPT,HPG,MWG",
    strategy_name="MultiAssetSmaCross",
    benchmark_data=benchmarks,
    filename="multi_asset_report.html",
    benchmark_symbol="VNINDEX"
)
print(f"Backtest hoàn tất! Báo cáo đã được xuất ra tại: {report_path}")
```

---

## 🛠️ Tối Ưu Hóa Tham Số (Parameter Optimization)

Bạn có thể tìm kiếm tổ hợp tham số tối ưu bằng cách sử dụng `ParameterOptimizer` hỗ trợ xử lý song song đa tiến trình (multiprocessing):

```python
from vn_backtest.optimizer import ParameterOptimizer

param_grid = {
    "sma_fast": [5, 10, 15],
    "sma_slow": [20, 30, 50]
}

optimizer = ParameterOptimizer(
    data=stock_data,
    strategy_class=MultiAssetSmaCross,
    param_grid=param_grid,
    initial_cash=100_000_000.0,
    exchange="hose",
    n_jobs=-1  # Chạy tối đa toàn bộ nhân CPU của máy
)

# Cách 1: Chạy Grid Search quét toàn bộ và sắp xếp kết quả theo tỷ số Sharpe giảm dần
opt_results = optimizer.run_optimization(sort_by="sharpe_ratio", ascending=False)
print(opt_results.head())

# Cách 2: Chạy tối ưu hóa Bayes bằng thư viện Optuna (Yêu cầu cài đặt thêm gói optuna)
# Xác định không gian tìm kiếm tham số
param_space = {
    "sma_fast": ("int", 5, 20),
    "sma_slow": ("int", 20, 100)
}
opt_results_bayes = optimizer.run_optuna(
    n_trials=50,
    sort_by="sharpe_ratio",
    ascending=False,
    param_space=param_space
)
print(opt_results_bayes.head())
```

---

## 📖 Chi Tiết Cấu Hình `BacktestEngine`

Dưới đây là mô tả chi tiết toàn bộ các tham số khởi tạo của lớp `BacktestEngine`:

| Tham Số | Kiểu Dữ Liệu | Mặc Định | Mô Tả |
| :--- | :--- | :--- | :--- |
| `data` | `DataFrame` \| `Dict[str, DataFrame]` | *(Bắt buộc)* | Dữ liệu lịch sử giá. Phải chứa cột `Open`, `High`, `Low`, `Close`, `Volume`. Index định dạng `DatetimeIndex`. |
| `strategy_class` | `Type[Strategy]` | *(Bắt buộc)* | Lớp chiến lược giao dịch kế thừa từ `Strategy`. |
| `corporate_actions` | `Dict[str, DataFrame]` | `None` | Dữ liệu sự kiện doanh nghiệp của các mã chứng khoán (Cổ tức, phát hành thêm). |
| `initial_cash` | `float` | `100,000,000.0` | Số tiền mặt khởi đầu cho tài khoản backtest (đơn vị: VND). |
| `buy_fee` | `float` | `0.0015` | Tỷ lệ phí giao dịch mua chứng khoán (ví dụ: `0.0015` = 0.15% giá trị giao dịch). |
| `sell_fee` | `float` | `0.0015` | Tỷ lệ phí giao dịch bán chứng khoán. |
| `sell_tax` | `float` | `0.001` | Tỷ lệ thuế thu nhập cá nhân khi bán chứng khoán tại Việt Nam (mặc định: 0.1%). |
| `settlement_days` | `int` | `2` | Chu kỳ thanh toán cổ phiếu mặc định (T+2). Sẽ tự động áp dụng chu kỳ lịch sử nếu bật `dynamic_rules`. |
| `lot_size` | `int` | `100` | Quy định lô giao dịch mặc định. Tự động chuyển đổi theo lịch sử sàn nếu bật `dynamic_rules`. |
| `exchange` | `str` \| `Dict[str, str]` | `"hose"` | Sàn giao dịch của cổ phiếu để tính Trần/Sàn và bước giá (`hose`, `hnx`, `upcom`). Nhận vào chuỗi hoặc một dict ánh xạ từng mã. |
| `execution_at` | `str` | `"open"` | Thời điểm thực thi giao dịch liên tục cho phiên kế tiếp (`"open"`: Khớp tại Open, `"close"`: Khớp tại Close). |
| `restrict_ceiling_buy` | `bool` | `True` | Nếu bật, lệnh mua sẽ bị từ chối/hủy nếu giá thị trường chạm giá trần (trắng bên bán). |
| `restrict_floor_sell` | `bool` | `True` | Nếu bật, lệnh bán sẽ bị từ chối/hủy nếu giá thị trường chạm giá sàn (trắng bên mua). |
| `slippage` | `float` | `0.0` | Tỷ lệ trượt giá áp dụng cho lệnh liên tục (ví dụ: `0.001` = 0.1% trượt giá). ATO/ATC không áp dụng. |
| `dynamic_rules` | `bool` | `True` | Kích hoạt cơ chế luật giao dịch thay đổi theo lịch sử thực tế của TTCK Việt Nam. |
| `advance_interest_rate` | `float` | `0.12` | Lãi suất ứng trước tiền bán năm (mặc định: 12%/năm) để mua cổ phiếu trước ngày tiền về. |
| `auto_close_at_end` | `bool` | `True` | Tự động tất toán (bán) toàn bộ cổ phiếu nắm giữ ở phiên cuối cùng của chuỗi dữ liệu. |
| `allow_odd_lot` | `bool` | `False` | Cho phép giao dịch lô lẻ dưới 100 cổ phiếu (ví dụ: 1-99). |
| `max_volume_ratio` | `float` | `None` | Giới hạn khối lượng khớp tối đa theo tỷ lệ thanh khoản ngày hôm đó (ví dụ: `0.01` nghĩa là chỉ được khớp tối đa 1% tổng Volume giao dịch của ngày). |
| `adjust_corporate_actions` | `bool` | `False` | Bật mô phỏng điều chỉnh giá/số lượng do cổ tức/quyền mua của cổ phiếu chưa được điều chỉnh (raw data). |
| `force_adjusted` | `bool` | `None` | Ép buộc trạng thái dữ liệu đầu vào. `True`: Đã điều chỉnh giá (Adj_Close), `False`: Giá gốc. |
| `margin_ratio` | `float` | `1.0` | Tỷ lệ ký quỹ tối thiểu. `1.0`: Không dùng margin. `0.5`: Margin 1:1 (Sức mua gấp đôi tài sản ròng). |
| `margin_interest_rate` | `float` | `0.13` | Lãi suất vay ký quỹ (margin loan) năm (mặc định: 13%/năm). |
| `margin_maintenance_ratio` | `float` | `0.35` | Tỷ lệ duy trì ký quỹ duy trì tối thiểu. Khi giá trị tài sản ròng / tổng tài sản dưới ngưỡng này sẽ kích hoạt Margin Call/Force Sell. |
| `ticker` | `str` | `None` | Tên mã chứng khoán nếu `data` truyền vào là một DataFrame duy nhất. |
| `strategy_params` | `Dict[str, Any]` | `None` | Bộ tham số truyền trực tiếp vào lớp chiến lược tại thời điểm khởi tạo. |
| `market_impact_coef` | `float` | `0.0` | Hệ số tác động thị trường dùng để tính toán trượt giá động dựa trên tỷ lệ khối lượng đặt lệnh so với Volume ngày. |
| `rights_listing_delay` | `int` | `90` | Số ngày chờ niêm yết cổ phiếu thưởng/quyền mua về tài khoản giao dịch (mặc định: 90 ngày). |
| `dividend_tax_rate` | `float` | `0.05` | Tỷ lệ khấu trừ thuế thu nhập cá nhân đối với cổ tức nhận được (mặc định: 5%). |
| `price_scale` | `float` | `1.0` | Tỷ lệ điều chỉnh đơn vị giá. Đặt `1000.0` nếu dữ liệu đầu vào đã bị chia cho 1000 (ví dụ: giá hiển thị 85.5 thay vì 85,500 VND). |
| `listing_dates` | `Dict[str, Timestamp]` | `None` | Ngày niêm yết chính thức của các mã chứng khoán dùng để kích hoạt quy định biên độ giá đặc biệt trong ngày đầu tiên lên sàn (Listing Day). |
| `check_lookahead` | `bool` | `True` | Bật/tắt lớp kiểm tra tĩnh phát hiện Look-Ahead Bias khi đăng ký chỉ báo qua `self.I()`. Tự động vô hiệu hóa trong optimizer để tăng tốc độ. |

---

## 📂 Cấu Trúc Thư Mục Dự Án

```plaintext
vn-backtest/
├── src/
│   └── vn_backtest/
│       ├── __init__.py          # Export các lớp và hàm chính
│       ├── engine.py            # Core Engine mô phỏng khớp lệnh, T+, margin, dòng tiền, sự kiện DN
│       ├── strategy.py          # Lớp Strategy cơ sở và đăng ký chỉ báo
│       ├── trading_rules.py     # Quản lý bước giá, lô giao dịch, trần/sàn và chu kỳ T+ lịch sử
│       ├── corporate_actions.py # Xử lý chia tách cổ phiếu, cổ tức và quyền mua phát hành thêm
│       ├── margin.py            # Quản lý ký quỹ, tính toán lãi vay và gọi ký quỹ/giải chấp
│       ├── orders.py            # Khai báo các loại lệnh (ATO, ATC, LIMIT, OCO) và trạng thái lệnh
│       ├── holidays.py          # Quản lý lịch nghỉ lễ và các ngày giao dịch của TTCK Việt Nam
│       ├── analysis.py          # Phân tích hiệu suất chi tiết, đo lường rủi ro (Sharpe, MAE/MFE, Alpha/Beta)
│       ├── optimizer.py         # Grid Search đa tiến trình và Tối ưu hóa Bayes (Optuna)
│       ├── reporter.py          # Sinh báo cáo HTML tương tác (Plotly, Jinja2, Stacked Allocation)
│       └── templates/           # Thư mục chứa các mẫu giao dịch HTML và CSS cho báo cáo
├── pyproject.toml               # Cấu hình cài đặt package và quản lý phụ thuộc
└── README.md                    # Tài liệu hướng dẫn sử dụng
```

---

## 🛡️ Chi Tiết Cơ Chế Chặn Look-Ahead Bias

Look-Ahead Bias là lỗi phổ biến nhất khiến kết quả backtest của bạn "đẹp như mơ" nhưng khi giao dịch thực tế lại thua lỗ vì thuật toán vô tình sử dụng dữ liệu giá của tương lai để ra quyết định hôm nay.

`vn-backtest` cung cấp **2 lớp bảo vệ**:

1.  **Kiểm tra tĩnh trong `self.I()`:** 
    Khi bạn đăng ký một chỉ báo qua `self.I()`, hệ thống sẽ tự động chạy hàm tính toán chỉ báo đó trên 2 lát cắt dữ liệu: toàn bộ dữ liệu lịch sử và dữ liệu bị cắt ngắn (sliced) tại một ngày ngẫu nhiên trong quá khứ. Nếu giá trị chỉ báo tại ngày đó khác nhau, hệ thống lập tức ném ra **cảnh báo đỏ** kèm theo giá trị sai lệch để bạn biết chỉ báo của mình đang bị rò rỉ thông tin tương lai.
    *(Lưu ý: Có thể tắt lớp bảo vệ này bằng tham số `check_lookahead=False` khi khởi động để tối ưu hóa hiệu năng, đặc biệt khi chạy Grid Search hoặc Optuna).*
2.  **Truy cập an toàn qua `self.safe_data`:**
    Trong hàm `next()`, thay vì thao tác trực tiếp trên `self.data` (chứa toàn bộ dữ liệu lịch sử), bạn có thể gọi `self.safe_data`. Thuộc tính này sẽ trả về một DataFrame chứa dữ liệu được cắt nghiêm ngặt từ ngày đầu tiên đến ngày giao dịch hiện tại (`current_idx`), đảm bảo logic giao dịch của bạn tuyệt đối không thể nhìn trước tương lai.

---

## ⚠️ Khuyến Cáo Dữ Liệu (Survival Bias)

Kết quả backtest của bất kỳ hệ thống nào cũng có nguy cơ bị ảnh hưởng bởi **Thiên lệch sống sót (Survivorship Bias)** nếu bạn chỉ chạy kiểm thử trên danh sách các mã cổ phiếu đang niêm yết hiện tại. 

Để kết quả phản ánh khách quan nhất:
*   Hãy bổ sung dữ liệu lịch sử của các mã cổ phiếu đã bị hủy niêm yết trong quá khứ.
*   Backtest Engine hỗ trợ cơ chế tự động đóng toàn bộ vị thế của mã chứng khoán tại ngày giao dịch cuối cùng trước khi bị hủy niêm yết để tính toán đúng lợi nhuận thực tế.

---

## 🤝 Đóng Góp Ý Kiến (Contributing)

Mọi đóng góp nhằm cải thiện thuật toán khớp lệnh định kỳ/liên tục, mở rộng tính năng phân tích rủi ro hoặc báo cáo lỗi phát sinh đều được hoan nghênh! Hãy mở một Issue hoặc gửi Pull Request trực tiếp trên kho lưu trữ Github của dự án.

## 📄 Giấy Phép (License)

Dự án được phát hành và phân phối theo các điều khoản của giấy phép **MIT**. Xem tệp `LICENSE` để biết thêm chi tiết.

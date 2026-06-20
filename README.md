# 📈 vn-backtest
**vn-backtest** là một framework kiểm thử chiến lược giao dịch (backtesting) bằng Python, được thiết kế và tối ưu hóa **dành riêng cho Thị trường Chứng khoán Việt Nam**. 

Khác với các thư viện quốc tế thông thường, `vn-backtest` mô phỏng chính xác các quy định giao dịch đặc thù và các sự kiện tài chính phức tạp tại Việt Nam (HOSE, HNX, UPCOM), giúp kết quả backtest của bạn phản ánh sát nhất với thực tế giao dịch.


## ✨ Tính Năng Nổi Bật
* ⏱️ **Chu kỳ thanh toán T+1.5 / T+2:** Giả lập chính xác thời gian cổ phiếu về tài khoản (settlement lock) và tiền bán chờ về.

* 💸 **Ứng trước tiền bán & Ký quỹ (Margin):** * Tự động tính toán phí ứng trước tiền bán.
  * Hỗ trợ giao dịch Margin với tỷ lệ vay (leverage), lãi suất qua đêm.
  * Tự động xử lý Giải chấp (Margin Call / Force Sell) khi vi phạm tỷ lệ duy trì.

* 📏 **Luật giao dịch theo lịch sử (Dynamic Rules):** * Áp dụng quy tắc lô chẵn (10, 100), lô lẻ (1-99).
  * Bước giá (tick size) và Biên độ dao động (Trần/Sàn) tự động thay đổi theo các mốc lịch sử thực tế của từng sàn.
  * Từ chối lệnh Mua giá Trần / Bán giá Sàn.

* 🏢 **Sự kiện Doanh nghiệp (Corporate Actions):** Tự động xử lý chính xác (bao gồm cả thuế thu nhập 5%):
  * Cổ tức bằng tiền mặt (Cash Dividends).
  * Cổ tức bằng cổ phiếu (Stock Dividends).
  * Thực hiện quyền mua (Rights Issues).

* 🛡️ **Quản trị Rủi ro (Risk Management):** Tích hợp sẵn cơ chế **Stop Loss** (Cắt lỗ) và **Trailing Stop** (Cắt lỗ động/Chốt lời động) tính toán trực tiếp trong engine.

* 📊 **Báo cáo Trực quan Cao cấp (Premium HTML Reports):** Tự động xuất báo cáo Interactive bằng `Plotly` (Giao diện Darkmode/Glassmorphism) với các chỉ số tài chính chuyên sâu (CAGR, Sharpe, Sortino, Max Drawdown, Alpha, Beta).

* 🚀 **Tối ưu hóa Chiến lược (Optimization):** Hỗ trợ Grid Search đa luồng (multiprocessing) để tìm ra bộ tham số chiến lược tốt nhất, kèm báo cáo Heatmap trực quan.


## ⚙️ Cài Đặt
Yêu cầu hệ thống: **Python >= 3.12**

Cài đặt trực tiếp từ mã nguồn ở chế độ phát triển (khuyến nghị):

```bash
git clone [https://github.com/phongvu2010/vn-backtest.git](https://github.com/phongvu2010/vn-backtest.git)
cd vn-backtest
pip install -e .
```

## 🚀 Hướng Dẫn Sử Dụng Nhanh (Quick Start)
Dưới đây là ví dụ xây dựng một chiến lược giao dịch cắt qua đường trung bình giá (Moving Average Crossover):

```python
import pandas as pd
from vn_backtest.strategy import Strategy
from vn_backtest.engine import BacktestEngine
from vn_backtest.reporter import ReportGenerator

# 1. Hàm tính toán chỉ báo (ví dụ: SMA)
def SMA(data, period, column='Close'):
    return data[column].rolling(window=period).mean()

# 2. Định nghĩa chiến lược
class SmaCrossStrategy(Strategy):
    # Định nghĩa tham số chiến lược (có thể dùng để Optimize sau này)
    sma_fast = 10
    sma_slow = 30

    def init(self):
        # Thiết lập quản trị rủi ro
        self.stop_loss = 0.07       # Cắt lỗ 7%
        self.trailing_stop = 0.10   # Trailing stop 10%

        # Đăng ký các chỉ báo
        self.fast_ma = self.I(SMA, self.sma_fast)
        self.slow_ma = self.I(SMA, self.sma_slow)

    def next(self):
        if self.current_idx == 0:
            return

        # Lấy giá trị chỉ báo hiện tại và phiên trước
        fast_curr = self.fast_ma.iloc[self.current_idx]
        fast_prev = self.fast_ma.iloc[self.current_idx - 1]
        slow_curr = self.slow_ma.iloc[self.current_idx]
        slow_prev = self.slow_ma.iloc[self.current_idx - 1]

        # Tín hiệu MUA: SMA nhanh cắt lên SMA chậm
        if fast_prev <= slow_prev and fast_curr > slow_curr:
            if self.positions.get('HPG', 0) == 0:
                self.buy('HPG') # Mua full sức mua khả dụng

        # Tín hiệu BÁN: SMA nhanh cắt xuống SMA chậm
        elif fast_prev >= slow_prev and fast_curr < slow_curr:
            if self.positions.get('HPG', 0) > 0:
                self.sell('HPG') # Bán toàn bộ vị thế

# 3. Chuẩn bị dữ liệu OHLCV
# Lưu ý: Yêu cầu DataFrame có index là Datetime và các cột: Open, High, Low, Close, Volume
df = pd.read_csv('HPG_data.csv', index_col='Date', parse_dates=True)

# 4. Khởi tạo Engine và chạy Backtest
engine = BacktestEngine(
    data=df, 
    strategy_class=SmaCrossStrategy,
    initial_cash=100_000_000, # 100 triệu VND
    exchange="hose",
    buy_fee=0.0015,           # Phí giao dịch 0.15%
    sell_fee=0.0015,
    margin_ratio=1.0          # 1.0 là không dùng margin, 0.5 là tỷ lệ 1:1
)

results = engine.run()

# 5. Xuất báo cáo HTML
reporter = ReportGenerator(output_dir="reports")
reporter.generate_report(
    metrics=results,
    equity_curve=results['equity_curve'],
    trades=results['trades'],
    stock_data=df,
    ticker="HPG",
    strategy_name="SMA Crossover Strategy"
)
print("Backtest hoàn tất. Vui lòng mở file HTML trong thư mục /reports để xem kết quả.")
```

## 🔬 Tối Ưu Hóa Tham Số (Parameter Optimization)
Bạn có thể dễ dàng tìm ra tham số tối ưu nhất cho chiến lược bằng `ParameterOptimizer`. Hệ thống sẽ chạy song song (multiprocessing) để tiết kiệm thời gian.

```python
from vn_backtest.optimizer import ParameterOptimizer

param_grid = {
    'sma_fast': [5, 10, 15],
    'sma_slow': [20, 30, 50],
    'stop_loss': [0.05, 0.07, 0.10]
}

optimizer = ParameterOptimizer(
    data=df,
    strategy_class=SmaCrossStrategy,
    param_grid=param_grid,
    initial_cash=100_000_000,
    exchange="hose",
    n_jobs=-1 # Sử dụng tối đa CPU cores
)

opt_results = optimizer.run_optimization(sort_by="sharpe_ratio", ascending=False)

# Xuất báo cáo Heatmap
reporter.generate_optimization_report(
    results_df=opt_results,
    ticker="HPG",
    strategy_name="SMA Crossover Optimization"
)
```

## 📂 Cấu Trúc Dự Án
```plaintext
vn-backtest/
├── vn_backtest/
│   ├── __init__.py      # Export các module chính
│   ├── engine.py        # Core Engine (khớp lệnh, T+, margin, corporate actions)
│   ├── strategy.py      # Lớp Strategy cơ sở cho người dùng định nghĩa logic
│   ├── analysis.py      # Tính toán Metrics (CAGR, Sharpe, Drawdown, v.v.)
│   ├── optimizer.py     # Grid Search Tối ưu hóa tham số đa luồng
│   └── reporter.py      # Sinh báo cáo HTML tương tác (Plotly, Jinja2)
├── pyproject.toml       # Cấu hình đóng gói Package
└── README.md
```

## ⚠️ Khuyến Cáo Dữ Liệu (Survival Bias)
Kết quả backtest thường dựa trên các mã cổ phiếu hiện đang hoạt động. Để kiểm thử các chiến lược một cách khách quan nhất và tránh thiên lệch sống sót (Survivorship Bias), hãy đảm bảo tệp dữ liệu của bạn bao gồm cả những mã đã bị hủy niêm yết (delisted) trong quá khứ. Engine có hỗ trợ tự động tất toán vị thế vào ngày giao dịch cuối cùng trước khi hủy niêm yết.

## 🤝 Đóng Góp (Contributing)
Mọi đóng góp (Pull Request) để cải thiện thuật toán khớp lệnh, thêm tính năng mới hoặc báo cáo lỗi (Issues) đều được hoan nghênh! Vui lòng đọc kỹ mã nguồn hiện tại và tạo PR trực tiếp trên GitHub.

## 📄 Giấy phép (License)
Dự án được phân phối dưới giấy phép **MIT**. Xem file `LICENSE` để biết thêm chi tiết.

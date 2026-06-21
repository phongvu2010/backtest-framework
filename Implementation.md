# Yêu cầu hệ thống: Tái cấu trúc dự án VN-Backtest thành kiến trúc Core-Plugin (Core & Pro)
Bạn là một Chuyên gia Kiến trúc Phần mềm (Software Architect) và Kỹ sư Python. Nhiệm vụ của bạn là tái cấu trúc (refactor) mã nguồn của dự án backtest hiện tại thành 2 packages riêng biệt dựa trên nguyên lý Kế thừa (Subclassing):
1. `vn_backtest`: Phiên bản Core (Mã nguồn mở, cơ bản).
2. `vn_backtest_pro`: Phiên bản Pro (Thương mại, nâng cao).

Hãy đọc kỹ toàn bộ mã nguồn hiện tại và thực hiện chính xác theo các bước sau. KHÔNG làm hỏng logic giao dịch cốt lõi.

## Bước 1: Thiết lập cấu trúc thư mục mới
Tạo cấu trúc thư mục như sau:
```
src/
├── vn_backtest/          # Package Core
│   ├── __init__.py
│   ├── engine.py
│   ├── strategy.py
│   ├── analysis.py
│   ├── optimizer.py
│   └── reporter.py
└── vn_backtest_pro/      # Package Pro
    ├── __init__.py
    ├── engine.py         # Kế thừa từ vn_backtest.engine.BacktestEngine
    ├── optimizer.py      # Kế thừa từ vn_backtest.optimizer.ParameterOptimizer
    ├── reporter.py       # Chứa logic Plotly/HTML
    └── rules.py          # Chứa logic Historical Dynamic Rules
```

## Bước 2: "Cắt tỉa" và Đơn giản hóa vn_backtest (Bản CORE)
Chỉnh sửa các file trong vn_backtest thành phiên bản cơ bản nhất:
1. engine.py (Core):
- XÓA bỏ toàn bộ các biến, tham số và logic liên quan đến: margin_ratio, margin_interest_rate, margin_maintenance_ratio, advance_interest_rate, corporate_actions, dividend_tax_rate, rights_listing_delay, dynamic_rules.

- Cố định luật giao dịch hiện tại: settlement_days = 2 (T+2.5), lot_size = 100, không cho phép giao dịch lô lẻ (allow_odd_lot = False).

- Xóa các hàm _process_corporate_actions và các đoạn code tính lãi vay margin/ứng trước. Mặc định mua/bán chỉ dùng self.cash.

2. trading_rules.py (Core): Đơn giản hóa, chỉ trả về các mức giá trần/sàn và bước giá hiện tại của thị trường. Bỏ các mốc thời gian lịch sử trong quá khứ.

3. optimizer.py (Core): Chỉ giữ lại class ParameterOptimizer với hàm run_optimization (Grid Search tuần tự/đa luồng). XÓA hàm run_optuna.

4. reporter.py (Core): XÓA toàn bộ logic Plotly và Jinja2 HTML. Thay thế bằng class BasicReporter chỉ in kết quả Text ra Console.

## Bước 3: Xây dựng vn_backtest_pro (Bản PRO) bằng Kế thừa
Tạo các file trong vn_backtest_pro bằng cách import và kế thừa từ bản Core:
1. vn_backtest_pro/engine.py:
- Tạo class ProBacktestEngine(BacktestEngine):
- Ghi đè (Override) hàm __init__ để nhận thêm các tham số Margin, Corporate Actions.
- Ghi đè hàm _apply_dynamic_rules() để gọi logic biến đổi T+ và Lô giao dịch theo lịch sử.
- Viết lại hàm _process_corporate_actions() (chuyển logic xử lý chia cổ tức, quyền mua, trừ thuế từ code cũ sang đây).
- Ghi đè hàm tính toán tiền/equity ở mỗi bước next() để tính lãi Margin và Force Sell.

2. vn_backtest_pro/optimizer.py:
- Tạo class ProParameterOptimizer(ParameterOptimizer):
- Di chuyển hàm run_optuna() (Bayesian Optimization bằng thư viện Optuna) từ code cũ vào class này.

3. vn_backtest_pro/reporter.py:
- Di chuyển toàn bộ class ReportGenerator (sử dụng Plotly, Jinja2, HTML templates) từ code cũ sang file này. Bản Pro sẽ độc quyền tính năng xuất báo cáo biểu đồ.

## Bước 4: Tách biệt Dependencies (Quản lý thư viện)
Cập nhật file pyproject.toml (hoặc requirements.txt):
* vn_backtest (Core) CHỈ cần: pandas, numpy. (Tuyệt đối không require plotly, jinja2, optuna).
* vn_backtest_pro (Pro) SẼ CẦN: vn_backtest, plotly, jinja2, optuna.

Yêu cầu thực thi đối với AI:
Hãy bắt đầu bằng cách tái cấu trúc vn_backtest/engine.py (Core) trước, xuất ra mã nguồn cho file này.
Sau đó, viết vn_backtest_pro/engine.py (Pro) kế thừa từ Core.
Chờ tôi xác nhận xem kiến trúc kế thừa đã chuẩn chưa rồi mới tiến hành làm tiếp các file optimizer và reporter.
Bắt đầu thực hiện Bước 1 và Bước 2 cho file engine.py.

### 💡 Tại sao prompt này hiệu quả với Antigravity/AI?
1. **Phân rã tác vụ (Task Decomposition):** Bắt AI làm toàn bộ project cùng lúc thường dẫn đến việc nó "cắt bớt code" (lazy coding). Bằng cách yêu cầu "Chờ tôi xác nhận... rồi mới làm tiếp", AI sẽ tập trung toàn bộ token vào việc viết file `engine.py` cho thật chi tiết và chính xác.

2. **Khai báo rõ ranh giới dependencies:** Cảnh báo AI không được cho `plotly` hay `optuna` vào bản Core. Điều này giúp bản Core của bạn thực sự nhẹ nhàng và thuần khiết.

3. **Định danh kiến trúc rõ ràng:** Cụm từ `class ProBacktestEngine(BacktestEngine):` "ép" AI phải dùng kế thừa (Inheritance), không cho phép nó copy-paste lại toàn bộ hàm của bản Core sang bản Pro.

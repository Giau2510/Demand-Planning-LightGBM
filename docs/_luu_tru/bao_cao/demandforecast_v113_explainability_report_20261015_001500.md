# Báo cáo batch 1.1.3: giải thích forecast, lịch sử demand & Excel, chỉ số chất lượng, quá trình huấn luyện LightGBM

Thời điểm: 14/10/2026 22:50 – 15/10/2026 00:15 (giờ Việt Nam).

**Kết quả:**
- Mọi hạng mục A–H đã hoàn thành, có bằng chứng kiểm thử.
- **Đã cài 1.1.3 vào ứng dụng thật lúc 00:11 ngày 15/10/2026** sau preflight và backup đã xác minh. Không cần migration (schema 3).
- Kiểm thử trên app thật chỉ ở chế độ đọc.

---

## 1. Phiên bản

| | |
|---|---|
| Nguồn ban đầu | 1.1.2 (đang chạy trên máy thật) |
| Kết quả | **1.1.3** (`backend/app/__init__.py`, `frontend/package.json`, `VERSION` trong gói) |
| Gói 1.1.2 | không bị thay hay sửa (`dist\DemandForecast-1.1.2-win64-portable.zip` giữ nguyên) |

## 2. File đã thay đổi

**Backend**

| File | Nội dung |
|---|---|
| `backend/app/ml/feature_catalog.py` (mới) | Danh mục 33 feature viết theo đúng `features_at`: công thức, khoảng ngày cụ thể so với ngày dự báo, có gồm ngày dự báo không, xử lý thiếu/0, đơn vị, ý nghĩa, vai trò nhóm |
| `backend/app/ml/explain.py` | Chuỗi bước đầy đủ (`contrib_sum`, `model_output` = `booster.predict`, kiểm tra khớp link, `clipped`, `n_features`, `attribution_method`). Mỗi feature có catalog, khoảng ngày, hiệu ứng tăng/giảm/không đáng kể. Lịch sử có `weekday` và `used_by` (feature nào đọc ngày đó). Khối chất lượng có Σ, fold, cấu hình backtest, có chồng ngày hay không. |
| `backend/app/ml/training_explain.py` (mới) | Tổng quan huấn luyện chỉ đọc. Tái lập điểm backtest trong bộ nhớ, chỉ trả kết quả khi khớp chỉ số đã lưu. |
| `backend/app/ml/model.py` | `backtest(..., collect=True)` trả từng điểm đánh giá; không đổi kết quả mặc định |
| `backend/app/explain_export.py` (mới) | Excel lịch sử demand và Excel điểm backtest |
| `backend/app/api/forecast_routes.py` | API mới (đều GET, chỉ đọc): `/forecast-runs/{id}/explain/history.xlsx`, `/features/catalog`, `/model/training-explain`, `/training-runs/{id}/backtest-points.xlsx` |

**Frontend**

| File | Nội dung |
|---|---|
| `frontend/src/pages/ExplainPanel.tsx` | Viết lại theo 3 tầng: Tóm tắt → Cách tính → Chi tiết kỹ thuật |
| `frontend/src/pages/TrainingExplain.tsx` (mới) | "Mô hình được huấn luyện như thế nào?" và "Danh mục feature" |
| `frontend/src/pages/Methodology.tsx` | Gắn hai khu vực trên vào trang Thuật toán & thuật ngữ, thêm vào mục lục |
| `frontend/src/components/ui.tsx` | `fmtX`, `fmtPctX` (tối đa 2 chữ số thập phân, `<0,01` giữ dấu); `weekdayName` |
| `frontend/src/styles.css` | Style cho các khu vực mới |

**Test:** mới `backend/tests/test_v113.py` (11) và `frontend/src/v113.test.tsx` (5); cập nhật `frontend/src/v112.test.tsx` (thêm cột Thứ).

**Tài liệu:** `docs/MO-HINH-VA-CHI-SO.md`, `docs/HUONG-DAN-SU-DUNG.md`.

## 3. Nguyên nhân gốc của thiếu sót trong phần giải thích cũ

- Công thức `exp(1,9888 + Σ đóng góp -0,0999) = …` gộp mọi bước vào một dòng. Không nói giá trị nền là gì, tổng của những số nào, vì sao dùng `exp`, và giá trị nào được publish.
- Bảng feature chỉ có tên kỹ thuật, giá trị, đóng góp và một câu mô tả ngắn. Thiếu khoảng ngày cụ thể, mẫu số của trung bình, cách xử lý thiếu/0. Không tách yếu tố làm tăng và làm giảm.
- Lịch sử không có thứ trong tuần và không xuất được ra file.
- Mục chất lượng chỉ có ba con số. Không có tử số/mẫu số, quy ước dấu của Bias, định nghĩa "điểm đánh giá", ngưỡng của quality gate.
- Không có màn hình nào mô tả dữ liệu huấn luyện, tham số thật và quy trình kiểm định.

## 4. Objective, hàm liên kết và công thức forecast (đã xác minh từ code)

- **Huấn luyện** (`ml/model.py::lgb_params, train`):
  - objective cấu hình, mặc định `tweedie` (`tweedie_variance_power` 1,2);
  - `num_boost_round` 300, `learning_rate` 0,05, `num_leaves` 31, `min_data_in_leaf` 20, feature/bagging fraction 0,9, `lambda_l2` 1, seed 7, deterministic.
- **Dự báo** (`model.forecast`):
  - `booster.predict(X)` trả **exp(điểm thô)** với tweedie/poisson, hoặc chính điểm thô với regression/regression_l1;
  - sau đó `np.clip(≥ 0)`;
  - giá trị chưa làm tròn được dùng làm lịch sử cho ngày tiếp theo (đệ quy);
  - khi publish (`pipeline._publish_run`) làm tròn 4 chữ số.
- **Giải thích** (`ml/explain.py`):
  - tái lập đúng dòng từ file mô hình (đã kiểm sha256) và cùng dữ liệu (đã kiểm dấu vân tay dữ liệu);
  - `booster.predict(X, pred_contrib=True)` (TreeSHAP chính xác của LightGBM) cho đóng góp từng feature và giá trị nền (phần tử cuối), ở thang điểm thô.
- **Các kiểm tra tự động** (`test_lightgbm_formula_chain_is_exact_for_the_published_value`):
  - giá trị nền + Σ đóng góp = điểm thô;
  - exp(điểm thô) = `booster.predict(X)`;
  - làm tròn 4 chữ số = giá trị đã publish.
- **Với objective identity** (`regression`): không có exp; đã có test riêng.

## 5. Ví dụ thật: giá trị nền, từng đóng góp, tổng đóng góp

Đây là dòng được truy nguyên đúng với ví dụ trong yêu cầu:

- Run `FCR-20261014111845-8B81D1`, **DEMO-SKU-028 · FC-HCM · 14/10/2026** (Thứ Tư, ngày thứ 1).
- Mô hình `MV-20261014-150621-DF32`, 300 cây, 33 feature.
- Dữ liệu DEMO, tái lập trên bản sao DB thật.

| Bước | Giá trị đầy đủ | Hiển thị |
|---|---|---|
| 1. Giá trị nền (base value, điểm thô kỳ vọng do TreeSHAP tính) | 1,988838 | 1,99 |
| 2–3. Tổng 33 đóng góp | −0,099898 | -0,1 |
| 4. Điểm thô = 1,988838 − 0,099898 | 1,888940 | 1,89 |
| 5. exp(1,888940) = đầu ra mô hình (`booster.predict`) | 6,612353 | 6,61 |
| 6. Cắt ≥ 0 (không cần) → làm tròn 4 chữ số | 6,6124 | |
| 7. Forecast đã publish (bảng, Excel) | 6,6124 ✓ khớp | 6,61 |

**Đóng góp lớn nhất của dòng này** (trên thang điểm thô):

| Feature | Giá trị | Đóng góp |
|---|---|---|
| `zero_share_28` (tỷ lệ ngày 0 trong 28 ngày) | 0,036 | +0,894 |
| `roll_mean_14` | 6,07 | −0,491 |
| `roll_mean_28` | 5,68 | −0,309 |
| `roll_mean_7` | 5,86 | −0,166 |
| `roll_mean_56` | 6,18 | −0,083 |
| `dow` (2 = Thứ Tư) | 2 | +0,054 |
| `roll_std_28` | 2,32 | −0,043 |
| `lag_2` | 8 | +0,029 |
| `series_age` | 730 | +0,028 |
| `days_since_last_sale` | 1 | +0,025 |

Còn 23 feature, mỗi feature có |đóng góp| < 0,015. Tổng 33 đóng góp = −0,099898; số này đã được kiểm khớp đến độ chính xác máy.

## 6. Danh mục feature thực tế (33 feature, lấy từ code)

- **Ngày dự báo t.** Mọi feature lag/rolling/giá/khuyến mãi chỉ đọc các ngày **trước** t. Feature lịch mô tả chính ngày t.
- **Định danh:** `sku_code`, `fc_code` (biến danh mục theo thứ tự đã sắp xếp lúc huấn luyện), `series_age` (t − ngày đơn đầu tiên).
- **Lag** `lag_1…7, 14, 21, 28`: số lượng của **đúng** ngày t−k. Ngày thiếu → thiếu (NaN), không lấy ngày khác thay; ngày có dữ liệu nhưng không có đơn → 0.
- **Rolling:**
  - `roll_mean_7/14/28/56` = tổng ÷ **số ngày đã biết** trong w ngày lịch trước t (mẫu số không phải w).
  - `roll_std_7/28` = độ lệch chuẩn tổng thể (ddof = 0), cần ≥ 2 ngày đã biết.
  - `zero_share_28` = ngày đã biết bằng 0 ÷ ngày đã biết; ngày không rõ không nằm ở tử hay mẫu.
  - `roll_max_28` = giá trị lớn nhất trong 28 ngày.
  - `days_since_last_sale` = số ngày từ ngày gần nhất có số lượng > 0,5, xét trong 180 ngày; không có ngày nào → 181.
- **Lịch** (của chính ngày t): `dow` (0 = Thứ Hai … 6 = Chủ Nhật), `dom`, `month`, `weekofyear` (ISO), `is_weekend`, `days_to_month_end`.
- **Giá:** `price_last` (giá bình quân ngày t−1, forward-fill), `price_rel_28` (`price_last` ÷ trung bình giá 28 ngày), `disc_last`.
- **Khuyến mãi:** `promo_last`, `promo_mean_7` (chia 7; khuyến mãi không rõ = 0 theo thiết kế).
- **Sau mốc dự báo:** lịch sử của ngày sau gồm chính dự báo của mô hình; giá giữ ở giá trị cuối; khuyến mãi = 0.
- **Nơi xem:**
  - Trong "Xem cách tính", mỗi feature có khoảng ngày thật, ví dụ `roll_mean_7` của ngày 14/10/2026 = 07/10–13/10/2026.
  - Trang Thuật toán → Danh mục feature.
  - API `/api/features/catalog`.
- **Test kiểm giá trị khớp dữ liệu nguồn:** lag_1/2/7, roll_mean_7 (mẫu số = ngày đã biết), zero_share_28, roll_std_28 (ddof 0), dow, không đọc sau data-as-of.

## 7. Formatter và bằng chứng không đổi độ chính xác nội bộ

- Phần giải thích, bảng feature, kết quả và chất lượng hiển thị **tối đa 2 chữ số thập phân**, bỏ số 0 thừa, dấu phẩy thập phân với tiếng Việt.
  - 1,9888 → 1,99; −0,0999 → -0,1; 6,612353 → 6,61; 7,2 → 7,2; 10 → 10; 0,5 → 0,5.
- Số khác 0 nhỏ hơn 0,01 hiện `<0,01` (giữ dấu: `-<0,01`, `+<0,01`).
- Phần trăm tối đa 2 chữ số thập phân: 19,25%, +1,52%.
- Số đếm là số nguyên: 2.072 điểm.
- Formatter chỉ ở tầng trình bày (`fmtX`, `fmtPctX`). Các giá trị dùng để so sánh hay tính đều là số gốc từ API:
  - quality gate so sánh ở độ chính xác đầy đủ (test kiểm `passed` = so sánh giá trị gốc với ngưỡng);
  - mục "Chi tiết kỹ thuật" hiện số đầy đủ (ví dụ 1,888939552626655), có test;
  - giá trị lưu trong DB không đổi (kiểm bằng số dòng và tổng trước/sau).

## 8. WAPE, Bias, số điểm đánh giá, quality gate (theo `ml/metrics.py`, `pipeline.quality_gate`)

- **WAPE** = Σ|A−F| ÷ ΣA.
  - Ví dụ thật, LightGBM: 9.278,44 ÷ 48.201 = **19,25%**.
  - Σ|A−F| = MAE × số điểm; ΣA, ΣF được lưu cùng lần huấn luyện.
- **Bias** = (ΣF − ΣA) ÷ ΣA, **dương = dự báo dư** (đúng quy ước trong code).
  - Ví dụ: (48.933,55 − 48.201) ÷ 48.201 = **+1,52%**, tức tổng dự báo cao hơn tổng thực tế 1,52%.
- **Điểm đánh giá** = một cặp (thực tế, dự báo) của một SKU×FC×ngày trong một fold backtest. Ngày không rõ thực tế bị loại; thực tế = 0 vẫn tính.
  - 2.072 là số điểm **của phương pháp LightGBM**; gộp mọi phương pháp là 3.274.
  - Cấu hình: 3 fold × 14 ngày, bước 7 ngày; các fold có mốc 16/09, 23/09, 30/09/2026.
  - Các fold chồng ngày nên **1.084** SKU×FC×ngày được đếm ở 2 fold; số SKU×FC×ngày khác nhau là 2.190.
  - **2.072 không phải 2.072 ngày.**
- **Quality gate** gồm: backtest đủ tin cậy, đủ số điểm (≥ 200), WAPE gộp ≤ 60%, |Bias| ≤ 20%; tùy chọn tốt hơn baseline.
  - Dùng chỉ số **gộp mọi phương pháp**, ngưỡng từ cấu hình lúc huấn luyện.
  - Ngưỡng **chưa được nghiệp vụ phê duyệt**, nên giao diện cảnh báo "Đạt" chỉ là đạt theo cấu hình hiện tại.
- **Tải các điểm backtest** (Excel): tái lập trong bộ nhớ.
  - Trên app thật: 3.274 điểm, WAPE và Bias khớp tuyệt đối với giá trị đã lưu; số dòng mọi bảng DB trước/sau bằng nhau.

## 9. Huấn luyện LightGBM thực tế và các nhóm

- **Mô hình hiện hành trên máy thật:** training run `TRN-20261014080606-47DF32`.
  - Dữ liệu DEMO (mô phỏng), có nhãn rõ trên giao diện.
  - Khoảng dữ liệu 14/10/2024 → 13/10/2026 (cutoff 13/10/2026).
  - 49.365 hàng huấn luyện; 84 chuỗi, 30 SKU, 4 FC.
  - File `MV-20261014-150621-DF32.txt`, sha256 khớp, 300 cây.
- **Hàng huấn luyện** = mọi (SKU×FC, ngày) có target đã biết, từ ngày thứ 7 và sau ngày chuỗi bắt đầu, tối đa 4 triệu hàng.
- **Target** = Σ `order_qty` theo ngày lịch Việt Nam.
- **Không có tập validation riêng, không early stopping**; số cây cố định. Chất lượng đo bằng backtest walk-forward: mỗi fold huấn luyện mô hình riêng chỉ với dữ liệu trước mốc.
- **Nhóm:**
  - **một mô hình chung**; SKU và FC là feature danh mục;
  - không có mô hình riêng theo SKU, FC, nhóm sản phẩm hay khoảng dự báo (7/15/30 dùng cùng một mô hình, đệ quy);
  - quy tắc chọn phương pháp theo từng chuỗi: run đầu tiên có LightGBM 53, chuỗi mới 10, gián đoạn 16, ngừng bán 5;
  - báo cáo đánh giá có gộp và tách theo phương pháp;
  - bộ lọc SKU/FC trên giao diện chỉ là lọc hiển thị.
- Màn hình hiện các điều kiện bỏ qua hoặc không publish: `NO_NEW_DATA`, `DATA_NOT_TRAINABLE`, `STALE_DATA_BLOCKED`, `QUALITY_GATE_FAILED`, `FORECAST_TOO_LARGE`, `TRAINING_FAILED`, `PUBLISH_FAILED`, `TIMEOUT`.
- Mở trang **không** gây huấn luyện hay ghi DB (có test).

## 10. Lịch sử demand và Excel

- **Bảng lịch sử** Ngày | **Thứ** | Demand | Trạng thái | Dùng trong phép tính (+ "Feature dùng ngày này" với LightGBM), theo thứ tự cũ → mới, đến hết data-as-of.
  - Thứ tính từ chính ngày lịch.
  - Có dữ liệu > 0, có dữ liệu = 0 và không rõ ("—") được tách biệt.
- **Lịch sử lấy từ nhu cầu ngày (`demand_daily`), không dùng snapshot trong ngày.** Test: sau 2 lần đồng bộ D0 cùng ngày, lịch sử không đổi.
- **Excel** (nút "Xuất Excel lịch sử"):
  - sheet Thông tin gồm run ID, model, SKU, FC, ngày dự báo, phương pháp, cutoff, khoảng ngày dùng, tổng, múi giờ;
  - sheet Lịch sử demand: ngày là ô ngày thật `DD/MM/YYYY`, demand là số (trống khi không rõ), cột thứ, header cố định, có bộ lọc.
- **Đã kiểm bằng đọc lại file:**
  - test: số dòng, kiểu ngày, thứ, demand, tổng các dòng dùng;
  - E2E bản sao và app thật: từng dòng khớp API.

## 11. Kết quả kiểm thử

| Bộ | PASS | FAIL | SKIP |
|---|---|---|---|
| Backend pytest (`logs\development\tests_20261014_234214.log`) | **137** | 0 | 0 |
| Frontend vitest | **36** | 0 | 0 |
| Typecheck `tsc -b` / production build | Đạt / Đạt | — | — |
| Lint | Dự án không cấu hình công cụ lint | | |
| E2E trình duyệt, mã nguồn 1.1.3 trên bản sao DB thật (nguồn DEMO trên bản sao) | **86** | 0 | 0 |
| Gói 1.1.3 cô lập: cài mới (smoke chung + kiểm tra 1.1.x) | 24 + 30 | 0 | 0 |
| Gói 1.1.3 cô lập: nâng cấp trên bản sao DB thật | 13 | 0 | 0 |
| **E2E chỉ đọc trên app thật 1.1.3** | **60** | 0 | 0 |
| Tải điểm backtest trên app thật (GET), đối chiếu chỉ số đã lưu, DB không đổi | Đạt | | |

## 12. E2E và lỗi đã sửa

**Lỗi ứng dụng phát hiện và sửa trong batch:**
- `days_since_last_sale` ban đầu chỉ được ghi là "dùng ngày này" khi ngày đó đã có feature khác dùng. Thực tế feature này quét 180 ngày; đã sửa cho đúng `features_at`.
- Trang huấn luyện và danh mục feature bị crash nếu API trả dữ liệu thiếu trường. Đã thêm kiểm tra và hiện "Không có dữ liệu để xác minh".

**Lần E2E đầu trên bản sao: 84/86.** Cả 2 FAIL do điều kiện kiểm của script, đã sửa script và chạy lại đạt 86/86:
- dấu "✓ khớp" của dòng dự phòng nằm ở dòng kế tiếp;
- nội dung nằm trong mục đang thu gọn.

## 13. Gói phân phối

- `D:\Buymed\Lightgbm AI\dist\DemandForecast-1.1.3-win64-portable.zip`, 101 373 945 byte.
- **SHA256 `5EA4A3280271650A09E90302BD6C8B50055AD717EEDCE859F53152EDDC0F64BE`**, đã băm lại lần hai và khớp.
- Giải nén ra `release\DemandForecast-1.1.3\`: 64 file chương trình trùng khớp mã nguồn đã test; 3 script dành cho phát triển không đóng gói.

## 14. Backup

- `D:\Buymed\Lightgbm AI\backups\backup-20261015-001048-manual.zip` (SHA256 `E3F7A050888BF7167166E00CAFB865E96C1F11F8BA4F5BE45BBB80B0B5082008`).
  - Đã mở; integrity ok, khóa ngoại 0, schema 3, 3 run.
  - Mọi số liệu khớp DB đang chạy.
- Installer tạo thêm `backup-20261015-001114-cli.zip`.
- Mọi backup cũ được giữ nguyên.

## 15. Trạng thái triển khai

- **Đã cài 1.1.3** (00:11:15, 15/10/2026). Preflight đạt: không job chạy, không biến `DF_*`, `storage.json` không đổi, không autostart.
- **Sau cài:**
  - phiên bản 1.1.3 (pid 30220, `Programs\DemandForecast\1.1.3`);
  - DB `D:\Buymed\Lightgbm AI\data\runtime\db\app.db` qua `storage.json`;
  - hash `storage.json` không đổi; marker `6cff0821634b0447`; `storage-verify` ok; integrity ok;
  - schema 3, không migration;
  - dữ liệu nghiệp vụ không đổi (chỉ thêm 1 dòng audit của lần backup);
  - log không lỗi; shortcut trỏ 1.1.3.
- **Quay lại 1.1.2:** dừng app → chạy `%LOCALAPPDATA%\Programs\DemandForecast\1.1.2\Start.bat`. Cùng schema 3, không cần khôi phục DB, không mất dữ liệu. Bước này chưa chạy thử.

## 16. Hạn chế và mục chưa xác minh

- **Nguồn đang hoạt động trên máy thật hiện là DEMO, không phải MANUAL_IMPORT như mô tả bối cảnh.**
  - Audit log ghi nguồn được chuyển qua lại qua giao diện trong khoảng 23:09–23:14 ngày 14/10; lần cuối sang DEMO lúc 23:14:48.
  - Phiên của tôi không tạo các thay đổi này và không đổi nguồn trong batch.
- Trên app thật chỉ kiểm thử đọc: không huấn luyện, không bổ sung khoảng, không import. Mô hình hiện hành được huấn luyện trên **dữ liệu DEMO**. Chưa có mô hình nào huấn luyện trên dữ liệu thật; điều kiện cần là import và xác nhận một lô Excel.
- **Giải thích LightGBM, lịch sử và tải điểm backtest** cần dữ liệu không đổi kể từ lúc huấn luyện. Nếu dữ liệu đổi, giao diện báo không tái lập được và không hiện số ước đoán. Tải điểm backtest phải huấn luyện lại tạm trong bộ nhớ nên mất vài giây.
- **SHAP** mô tả cách mô hình tính, không phải quan hệ nhân quả. Đóng góp ở thang log nên không cộng thẳng ra số lượng.
- **Ngưỡng quality gate** vẫn là giá trị ví dụ, chưa được phê duyệt.
- MAPE không được giải thích chi tiết trong batch này (ngoài phạm vi).
- **Chưa thử:** máy Windows khác, thiết bị cảm ứng thật, lịch bật lên của nút 📅. BigQuery vẫn bị chặn.

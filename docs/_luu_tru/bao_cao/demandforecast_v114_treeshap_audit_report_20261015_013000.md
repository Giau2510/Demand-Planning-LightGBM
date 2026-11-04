# Báo cáo batch 1.1.4: trace TreeSHAP kiểm toán được

Thời điểm: 15/10/2026 00:30 – 01:30 (giờ Việt Nam).

**Kết quả:**
- Người dùng có thể truy ra cách LightGBM tạo một giá trị SHAP cụ thể, ví dụ `zero_share_28 = 0 → +0,84`. Chuỗi truy vết gồm cây, lá, đường đi, trọng số Shapley và từng số hạng.
- Mỗi trace được đối soát tự động với `pred_contrib` của LightGBM, với điểm thô của model và với giá trị đã công bố.
- Ví dụ của người dùng đã được tìm thấy trong dữ liệu thật và có trạng thái **VERIFIED**. Engine trùng **từng bit** với LightGBM: chênh lệch SHAP lớn nhất là 0.
- **Đã cài 1.1.4 vào ứng dụng thật lúc 01:22 ngày 15/10/2026**, sau khi E2E trên bản sao DB, kiểm thử cô lập và backup đã xác minh đều đạt.
  - Không có migration (schema 3).
  - Không đổi `storage.json`, nguồn dữ liệu, dữ liệu nghiệp vụ hay model.
  - Kiểm thử trên app thật chỉ ở chế độ đọc.

---

## 1. Kiến trúc và API

### Thành phần

**`backend/app/ml/treeshap_trace.py` (mới) — engine trace**
- Port đúng từng phép tính của LightGBM **v4.7.0**: `src/io/tree.cpp` (`ExtendPath`, `UnwindPath`, `UnwoundPathSum`, `TreeSHAP`, `ExpectedValue`) và `include/LightGBM/tree.h` (`Decision`, `NumericalDecision`, `CategoricalDecision`, `kZeroThreshold = 1e-35f`, kiểu missing, bit default-left, `FindInBitset`).
- Thứ tự phép cộng/nhân giữ nguyên như bản C++. Vì vậy kết quả trùng từng bit, không chỉ "gần đúng".
- Đọc cây trực tiếp từ file model text đang dùng. Không retrain, không xấp xỉ, không nhiễu loạn từng feature.
- Mỗi số hạng được ghi lại dưới dạng `(cây, lá, feature, one_fraction, zero_fraction, w, giá trị lá, số hạng)`, kèm đường đi `(node, nhánh, dòng có đi nhánh này không, tỷ lệ cover)`.

**`backend/app/ml/shap_audit.py` (mới) — kiểm toán một dòng forecast**
- Dựng lại feature row bằng đúng cơ chế giải thích của 1.1.3, chạy engine, rồi đối soát (mục 5).
- Cache LRU 6 mục, khóa `(sha256 model, run, sku, fc, ngày, hash feature row)`.
- Giới hạn: 60 giây và 3.000.000 số hạng mỗi lần trace. Phân trang tối đa 200 dòng.

**`backend/app/explain_export.py`** — xuất Excel (4 sheet) và CSV (UTF-8 BOM, số ở dạng `repr` đầy đủ, không làm tròn).

**`backend/app/api/forecast_routes.py`** — 3 route chỉ đọc (GET):

| Route | Nội dung |
|---|---|
| `GET /api/forecast-runs/{id}/shap-trace?sku_id&fc_id&target_date[&feature&page&page_size&sort]` | Trạng thái, danh tính (run, model, hash), bảng đối soát, các giá trị chưa làm tròn, SHAP 33 feature. Có `feature` thì thêm tóm tắt và danh sách cây phân trang. |
| `GET .../shap-trace/tree?…&feature&tree` | Từng lá của một cây: giá trị lá, count, `one`, `zero`, `w`, số hạng, đường đi |
| `GET .../shap-trace.xlsx` / `.csv` `[?feature]` | Trace một feature hoặc cả 33 feature |

**Mã lỗi mới:** `NOT_LIGHTGBM` (409, dòng fallback), `UNKNOWN_FEATURE`, `TRACE_TOO_LARGE`, `TRACE_TIMEOUT`, `UNSUPPORTED_MODEL`.

**Frontend**
- `frontend/src/pages/ShapTrace.tsx` (mới): cửa sổ "Vì sao feature này có đóng góp như vậy?", mở từ nút **Vì sao?** trên từng dòng feature trong phần giải thích (`ExplainPanel.tsx`).
  - **Mức A — nghiệp vụ:** thang điểm thô, số cây/số hạng, tổng dương/âm, ý nghĩa.
  - **Mức B — tính toán:** bảng cây phân trang 20 dòng (điều kiện tách, dòng đi nhánh nào, lá thực tế). Bấm một cây để xem từng lá với `w·(one−zero)·v` và đường đi.
  - **Mức C — thuật toán và đối soát:** công thức, bảng đối soát với dung sai, giá trị đầy đủ chữ số, liên kết tài liệu, tải Excel/CSV.
- Trạng thái FAILED không bao giờ hiển thị như kết quả chính xác. Với NOT_REPRODUCIBLE, màn hình hiển thị "Không đủ dữ liệu để tái hiện chính xác" và không hiển thị số nào.

### Tài liệu nguồn đã đối chiếu

- Mã nguồn LightGBM v4.7.0 (`src/io/tree.cpp`, `include/LightGBM/tree.h`). Đã tải về và port theo đúng phiên bản đang dùng (4.7.0 trong cả venv và gói).
- Lundberg, Erion & Lee (2018), *Consistent Individualized Feature Attribution for Tree Ensembles*, arXiv:1802.03888, Algorithm 2 (path-dependent TreeSHAP). Đây là thuật toán mà `pred_contrib=True` của LightGBM cài đặt.
- `docs/MO-HINH-VA-CHI-SO.md`: thêm mục "Trace TreeSHAP kiểm toán được (v1.1.4)" và sửa định nghĩa base value.

## 2. Định nghĩa base value

**Base value không phải trung bình điểm thô của dữ liệu.** Giải thích cũ (1.1.3) có câu gần với ý đó; câu này đã được sửa ở cả UI và tài liệu.

**Định nghĩa:**

> base value = Σ trên 300 cây của ExpectedValue(cây), với ExpectedValue(cây) = Σ_lá (leaf_count / internal_count của gốc) × leaf_value

- `leaf_count` là số dòng huấn luyện **sau bagging** (bagging_fraction 0,9) rơi vào lá khi cây được dựng. Đây là `leaf_count`/`internal_count` trong file model.
- Lá của cây 0 đã bao gồm điểm khởi tạo `boost_from_average`. Vì vậy cây 0 đóng góp phần lớn base value.
- Base value của ví dụ: engine cho **1.9888380316076457**, LightGBM (cột cuối của `pred_contrib`) cũng cho **1.9888380316076457**. Chênh lệch 0.
- Base value nằm trên **thang điểm thô** (log, objective tweedie). Forecast là `exp(base + Σ SHAP)`; không cộng SHAP trực tiếp vào số lượng.

## 3. Ví dụ của người dùng — trace thật

**Đây là trace thật trên dữ liệu runtime**, đọc từ bản sao DB và lặp lại chỉ đọc trên app thật sau khi cài 1.1.4. Kết quả hai lần giống nhau.

| | |
|---|---|
| Forecast run | `FCR-20261014111845-8B81D1` (nguồn DEMO, scope `DEMO-20261014080556-5342EB`) |
| Dòng | `DEMO-SKU-001 · FC-HCM · 14/10/2026` (ngày dự báo thứ 1) |
| Model | `MV-20261014-150621-DF32`, tweedie, link exp, 300 cây, 33 feature |
| SHA256 file model | `ec507fd6387602f2b3d22f4445f69239d3d6e36f762763129f3bd7fc49bd6c26` |
| Hash feature row (float32) | `5c079ed731c8ebaa4731f1dfccbe6a73a1d868c9f0aad9e79cb752f1d84e9676` |
| Trạng thái | **VERIFIED**, 11/11 kiểm tra đạt, 0,4 giây |

### Từ base value đến số đã công bố

| Bước | Giá trị |
|---|---|
| Base value | 1.9888380316076457 |
| Σ SHAP 33 feature | 1.4698339468198012 |
| Điểm thô = base + Σ SHAP | 3.458671978427447 |
| Điểm thô do model tính (`raw_score=True`) | 3.4586719784274385 (chênh 8,4e-15) |
| exp(điểm thô) = đầu ra model | 31.774750927933475 |
| Sau chặn ≥ 0 | 31.774750927933475 |
| Làm tròn 4 chữ số = giá trị đã công bố | **31,7748** = 31,7748 trong DB |

### Ba feature trong ví dụ

| Feature | Giá trị vào | SHAP (engine = LightGBM) | Số cây có tách theo feature | Số hạng | Σ số hạng dương | Σ số hạng âm |
|---|---|---|---|---|---|---|
| `zero_share_28` | 0 | **+0.8394028043306269** | 172 / 300 | 3.195 | +1,3024 | −0,4630 |
| `roll_mean_14` | 31.714284896850586 | **+0.32756807706338065** | 203 / 300 | 2.754 | +2,7186 | −2,3911 |
| `roll_mean_7` | 36.42856979370117 | **+0.20078518271561818** | 133 / 300 | 1.520 | +0,2329 | −0,0321 |

**Ý nghĩa:**
- Một feature chỉ có số hạng trong những cây có tách theo nó. 128 cây không tách theo `zero_share_28` đóng góp đúng 0 cho feature này.
- **`zero_share_28 = 0`:** SKU không có ngày nào bằng 0 trong 28 ngày.
  - Mọi cây có tách theo feature này đều đưa dòng sang nhánh "≤ 0,0536", tức nhánh của các chuỗi bán đều.
  - Theo cây, tổng dương là +0,84286 và tổng âm là −0,00346: gần như mọi cây đều đẩy lên.
- **`roll_mean_14`:** cây 0 có +2,318 và −2,292 gần như triệt tiêu nhau, vì lá cây 0 chứa điểm khởi tạo. Tổng thực sau triệt tiêu chỉ +0,0268.
  - Đây là lý do Σ số hạng dương/âm lớn trong khi SHAP chỉ +0,33.

### Một cây cụ thể có thể tính tay (cây 19, `zero_share_28`)

**Thông số cây:** ExpectedValue −0.013495370311577591; count gốc 44.373; dòng rơi vào lá 25. Cây có 31 số hạng, tổng 0.01659461691473846.

| Lá | Giá trị lá | Count | Dòng có tới không | one | zero | w | Số hạng = w·(one−zero)·v |
|---|---|---|---|---|---|---|---|
| 1 | −0,058367 | 11.380 | không | 0 | 0,256462 | 1 | **+0,014969** |
| 25 | +0,012910 | 523 | **có** | 1 | 0,743538 | 0,295031 | **+0,000977** |
| 13 | +0,008210 | 1.509 | không | 1 | 0,743538 | 0,086207 | +0,000182 |

**Cách đọc:**
- **Lá 1** nằm bên phải của phép tách `zero_share_28 ≤ 0,0536`; dòng **không** đi nhánh đó, nên one = 0.
  - zero = 11.380 / 44.373 = 0,256462 là tỷ lệ cover của nhánh.
  - Số hạng = 1 × (0 − 0,256462) × (−0,058367) = +0,014969.
  - Ý nghĩa: biết `zero_share_28 = 0` thì loại được nhánh "nhiều ngày 0" có giá trị âm, nên đóng góp là dương.
- **Lá 25** là lá dòng thực sự rơi vào. Đường đi: `zero_share_28 ≤ 0,0536 → trái` > `roll_mean_14 ≤ 20,46 → phải` > `lag_14 ≤ 31,5 → trái` > `lag_7 ≤ 26,5 → phải` > `roll_mean_28 ≤ 25,98 → phải` > `dow ≤ 4,5 → trái` > `roll_mean_7 ≤ 34,59 → phải`.

Mỗi số hạng trong Excel/CSV đều tính lại được bằng công thức này. E2E đã tính lại từng số hạng trong file với sai số ≤ 1e-15.

## 4. Trace thật và dữ liệu tổng hợp

**Trace thật (model runtime, không retrain):**
- So engine với LightGBM trên 25 dòng ngẫu nhiên của model `MV-20261014-150621-DF32`.
  - Chênh SHAP lớn nhất 0, chênh base 0.
  - Đường đi tới lá trùng `pred_leaf` ở cả 300 cây, cho mọi dòng.
  - 0,26 giây/dòng; khoảng 53.555 số hạng/dòng.
- Ví dụ ở mục 3: kiểm tra trên bản sao DB, trên app thật (chỉ đọc), và qua Excel/CSV tải về.
- Kiểm thử cô lập "nâng cấp" (bản sao DB thật, runtime nhúng của gói): run cũ nhất `FCR-20261014080621-8D88F1` cũng VERIFIED.

**Dữ liệu tổng hợp (chỉ trong unit test, oracle là LightGBM 4.7.0 cùng phiên bản):**
- model 1 feature;
- nhiều feature có tương tác và tách lặp cùng feature;
- NaN và `zero_as_missing`;
- feature categorical (category chưa gặp, âm, NaN);
- giá trị đúng bằng ngưỡng tách;
- tweedie + bagging + link exp với đóng góp dương, âm và rất nhỏ.

Tất cả đều khớp `pred_contrib` với dung sai 1e-12. Không có số liệu tổng hợp nào được dùng trong báo cáo này như số liệu thật.

## 5. Bảng đối soát

Mỗi trace chạy 11 kiểm tra. **Chỉ cần một kiểm tra hỏng là FAILED**. Thiếu hoặc đổi artifact thì NOT_REPRODUCIBLE ("Không đủ dữ liệu để tái hiện chính xác").

| Kiểm tra | So sánh | Dung sai | Ví dụ mục 3 |
|---|---|---|---|
| `MODEL_SHA256` | sha256 file model = giá trị lúc huấn luyện | khớp đúng | đạt |
| `FEATURE_NAMES` | tên/thứ tự feature: file model = booster = cấu hình training run | khớp đúng | đạt |
| `FEATURE_COUNT` | số feature của dòng = của model | khớp đúng | 33 = 33 |
| `TREE_COUNT` | số cây engine đọc = booster | khớp đúng | 300 = 300 |
| `LEAF_PATHS` | lá engine đi tới = `pred_leaf` | khớp đúng | 300/300 |
| `SHAP_ENGINE_VS_LIGHTGBM` | 33 SHAP engine vs `pred_contrib` | 1e-12 | chênh 0 |
| `BASE_VALUE_ENGINE_VS_LIGHTGBM` | base engine vs cột cuối `pred_contrib` | 1e-12 | chênh 0 |
| `RAW_SCORE_ATTRIBUTION_VS_MODEL` | base + Σ SHAP vs `predict(raw_score=True)` | 1e-9 | 8,4e-15 |
| `MODEL_OUTPUT_IS_LINK_OF_RAW` | exp(điểm thô) vs `predict()` | tương đối 1e-12 | chênh 0 |
| `PUBLISHED_VALUE` | chặn + làm tròn vs giá trị trong DB | 1e-9 | 31,7748 = 31,7748 |
| `COMPONENTS_SUM_TO_SHAP` | Σ số hạng đã ghi theo feature vs SHAP | 1e-9 | chênh 0 |

**Ghi chú:** Excel/CSV cộng số hạng theo thứ tự khác với thuật toán đệ quy, nên Σ trong file có thể lệch SHAP ở chữ số thứ 15–16. Ví dụ: Σ `zero_share_28` trong Excel = 0.8394028043306252, chênh 1,7e-15. Đây là sai số cộng dấu phẩy động, không phải sai khác thuật toán. CSV đủ 33 feature cho chênh lớn nhất 0 so với LightGBM.

## 6. Giới hạn

- **Chỉ trace dòng LightGBM.** Dòng fallback (ví dụ `FALLBACK_NEW_SERIES`) trả `NOT_LIGHTGBM`, vì không có cây nào để giải thích. Fallback vẫn dùng phần giải thích công thức của 1.1.3.
- **Mô hình hỗ trợ:**
  - Chỉ hỗ trợ model một đầu ra, cây thường.
  - Linear tree và multiclass trả `UNSUPPORTED_MODEL`. Model hiện tại không thuộc loại này.
- **Thuật toán:** path-dependent TreeSHAP, tức đúng phép tính của `pred_contrib`. Đây không phải interventional SHAP và không phải SHAP interaction values.
- **Cache:** 6 trace gần nhất, chỉ trong bộ nhớ, mất khi khởi động lại. Không ghi gì vào DB.
- **Giới hạn mỗi trace:** 60 giây và 3.000.000 số hạng; vượt thì trả `TRACE_TIMEOUT` / `TRACE_TOO_LARGE`. Model hiện tại cần 0,3–0,4 giây và 53.555 số hạng.
- **Tái hiện dòng phụ thuộc dữ liệu:** dòng được dựng lại từ dữ liệu demand và artifact model hiện có. Nếu artifact bị xóa/đổi, hoặc dữ liệu lịch sử không còn khớp giá trị đã công bố, trace dừng ở NOT_REPRODUCIBLE. Không bao giờ hiển thị số trong trường hợp đó.
- **Đường dẫn dài:** đường dẫn trong gói dài tối đa 107 ký tự. Khi cài vào `%LOCALAPPDATA%\Programs\DemandForecast\1.1.4` thì vẫn dưới giới hạn 260 ký tự của Windows.
  - Trong kiểm thử cô lập, thư mục cài nằm rất sâu trong thư mục tạm, nên một số file cache `.pyc`, test và header của thư viện vượt 260 ký tự và không chép được.
  - Ứng dụng vẫn chạy và kiểm thử đều đạt. Trên máy thật, file cài đặt không gặp lỗi này.

## 7. Kết quả kiểm thử

| Kiểm thử | Kết quả |
|---|---|
| Backend `pytest` toàn bộ (`logs\development\tests_20261015_005200.log`) | **151 PASS**, 0 FAIL, 0 SKIP. Gồm 14 test mới `tests/test_v114_treeshap.py`: 8 test oracle trên model tổng hợp + 6 test kiểm toán/API trên run DEMO |
| Frontend `vitest` | **39 PASS**, 0 FAIL, 0 SKIP (gồm 3 test mới `src/v114.test.tsx`: VERIFIED/phân trang/lá, FAILED, NOT_REPRODUCIBLE) |
| TypeScript `tsc` + `vite build` | đạt |
| E2E trình duyệt trên **bản sao DB** (Chrome headless, port 8879) | **99 PASS**, 0 FAIL |
| Kiểm thử cô lập gói — cài mới | **24 + 33 PASS**, 0 FAIL (gồm trace VERIFIED trên runtime nhúng) |
| Kiểm thử cô lập gói — nâng cấp trên bản sao DB thật | **16 PASS**, 0 FAIL (trace VERIFIED trên run cũ nhất) |
| E2E **chỉ đọc trên app thật** 1.1.4 | **73 PASS**, 0 FAIL; trình duyệt không gửi request ghi nào |

**Lần chạy E2E đầu tiên trên bản sao DB:** 98 PASS / 1 FAIL. Lỗi nằm ở **điều kiện kiểm thử**: test so chuỗi `"0.0"` (Python) với `"0"` mà UI hiển thị (JavaScript). Đã sửa test và chạy lại trên bản sao DB mới: 99/0. Ứng dụng không phải sửa.

**Không kiểm thử trên máy Windows khác.**

## 8. Phiên bản, gói, backup, cài đặt, rollback

| | |
|---|---|
| Phiên bản trước | 1.1.3 (pid 30220), nguồn DEMO, scope `DEMO-20261014080556-5342EB`, schema 3, không job đang chạy |
| Phiên bản mới | **1.1.4** (`backend/app/__init__.py`, `frontend/package.json`, `VERSION` trong gói) |
| Gói | `dist\DemandForecast-1.1.4-win64-portable.zip`, 101.392.463 byte |
| SHA256 (tính 2 lần, trùng nhau) | `D4E66387EACB867DAFFBD74C06B36F0F9F6494F91959FD81B0038E87DB4538F7` |
| Đã giải nén | `release\DemandForecast-1.1.4` (8.233 file). `backend/app`, `web`, `docs`, `install.ps1` trùng mã nguồn |
| Gói 1.1.3 | không đổi: SHA256 vẫn `5EA4A3280271650A09E90302BD6C8B50055AD717EEDCE859F53152EDDC0F64BE` |
| Backup trước khi sửa mã | `backups\backup-20261015-003833-manual.zip` (SHA256 `177709A2…FDBC71`), đọc được, khớp DB |
| Backup độc lập trước khi cài | `backups\backup-20261015-012210-manual.zip` (SHA256 `449E3194EB1A36B49E57D1CF259288C65711808288E55E68F112F73AEF683424`). Đã giải nén và đọc: gồm `db\app.db` và file model đang dùng; số liệu khớp DB thật, không chênh |
| Backup tự động của trình cài | `backups\backup-20261015-012239-cli.zip` |
| Cài đặt | 01:22, 15/10/2026, bằng `release\DemandForecast-1.1.4\…\scripts\install.ps1`. `storage-verify` đạt trước khi dừng 1.1.3. Không migration (3 → 3). App mới pid 27956 tại `%LOCALAPPDATA%\Programs\DemandForecast\1.1.4`, shortcut trỏ 1.1.4 |
| Sau cài | log không có lỗi; `storage-verify` ok; integrity ok, 0 lỗi khóa ngoại |

### Rollback về 1.1.3 (chưa chạy thử)

1. Dừng app: `%LOCALAPPDATA%\Programs\DemandForecast\1.1.4\Stop.bat`.
2. Chạy `%LOCALAPPDATA%\Programs\DemandForecast\1.1.3\Start.bat`. Thư mục 1.1.3 vẫn còn nguyên.
3. Nếu muốn shortcut và `current.txt` cũng trỏ về 1.1.3: chạy `release\DemandForecast-1.1.3\DemandForecast-1.1.3\scripts\install.ps1`.

**Không cần khôi phục DB:** 1.1.4 dùng cùng schema 3, không thêm bảng hay cột, không ghi gì cho trace. Rollback không mất dữ liệu.

## 9. DB, storage ID, nguồn và dữ liệu được giữ nguyên

| | Trước khi cài | Sau khi cài + E2E chỉ đọc |
|---|---|---|
| DB runtime | `D:\Buymed\Lightgbm AI\data\runtime\db\app.db` (qua `storage.json`) | như cũ |
| SHA256 `storage.json` | `8D79DBDD…00FDE047` | `8D79DBDD…00FDE047` |
| storage ID | `6cff0821634b0447` | `6cff0821634b0447` |
| Nguồn dữ liệu đang dùng | DEMO | DEMO (không tự đổi) |
| Scope | `DEMO-20261014080556-5342EB` | như cũ |
| Forecast run / giá trị | 3 run / 4.368 giá trị | 3 / 4.368 |
| Run cũ `FCR-20261014080621-8D88F1` | 588 dòng, tổng 10.395,456 | như cũ |
| Tổng demand | 1.015.057 | 1.015.057 |
| SHA256 file model đang dùng | `EC507FD6…49BD6C26` | như cũ (không retrain) |
| Thay đổi duy nhất trong DB | — | 1 dòng `audit_log` `BACKUP_CREATED` của lần backup độc lập |

**Ràng buộc đã tuân thủ:**
- Không chạy `storage-repair --apply`.
- Không import Excel thật.
- Không đổi ngưỡng chất lượng.
- Không xóa hay reset dữ liệu.
- Không dùng DB dự phòng làm DB runtime.
- Không commit Git.
- Mọi kiểm thử có ghi đều chạy trên bản sao DB hoặc `LOCALAPPDATA` cô lập.

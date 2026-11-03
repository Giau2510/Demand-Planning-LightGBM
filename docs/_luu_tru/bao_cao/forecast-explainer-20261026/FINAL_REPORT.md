# Hoàn tất dọn ổ đĩa an toàn và màn hình "Giải thích cách tính Forecast" (26/10/2026, 11:30-13:45)

## Trạng thái: `READY_FOR_PRODUCTION`

Mã đã xong và đã kiểm thử, nhưng **chưa commit, chưa đóng gói, chưa deploy**. Production 1.2.13 không bị thay đổi bởi lô
này. Để màn hình mới chạy trên production cần anh/chị duyệt commit, phát hành 1.2.14 và deploy.

| Phần | Kết quả |
|---|---|
| A1. Backup mới | `backup-20261026-113756-manual.zip`, đã xác minh và khôi phục thử trên bản sao cách ly |
| A2. Dọn tiếp | Xóa 337 file tạm rời có bằng chứng (55,8 MiB); các mục còn nghi vấn vẫn giữ, có lý do |
| A3. Thư mục staging của deploy | Đã sửa `deploy-upgrade.ps1`; 24 test đạt |
| B. Màn hình giải thích | Trang `/forecast-explainer`; tính lại đúng từng bước trên dữ liệu thật và khớp forecast đã lưu (36/36 mẫu) |
| Kiểm thử | Backend 879 đạt / 19 bỏ qua / 0 lỗi; frontend 165 đạt; typecheck, build OK; lint chưa cấu hình |

## 1. Backup và dọn dẹp

**Backup:** `backups\backup-20261026-113756-manual.zip`
- 249.363.253 byte, SHA-256 `E6514810967DF01E54B652F30C28D4C09DE1BFF0CB73EFCCA6A2431B8602D1E6`. Tính lại SHA lúc 13:05 vẫn
  khớp.
- Xác minh: testzip OK, 21 mục (20 file model), DB 2.777.382.912 byte, `integrity_check = ok`, schema 10. Số dòng:
  `demand_daily` 1.414.512, `forecast_values` 1.290.618
  (`evidence/backup-20261026-113756-verification.txt`).
- Khôi phục thử trên bản sao cách ly: `data-check` cho 34 OK / 3 WARN / 0 FAIL
  (`evidence/backup-restore-copy-data-check.txt`). Ba WARN đã biết từ trước:
  - `forecast_series_meta`: run cũ trước migration 0003;
  - `finalized_days_changed` (228);
  - `history_source_drift` (291).

**Đã xóa: 337 file tạm rời ở gốc TEMP, 58.526.739 byte.** Tất cả đều được xác định rõ, cũ hơn 7 ngày và không thuộc phiên
đang chạy:
- 256 file tạm của Microsoft Office (`~DF<hex>.TMP`), 36,4 MB;
- 81 file chẩn đoán CPU của VS Code (`exthost-<hex>.cpuprofile`), 19,4 MB.

Mỗi file có một dòng trong kế hoạch và kết quả: 337/337 `DELETED`, 0 lỗi (`evidence/loose-temp-plan.csv`,
`loose-temp-results.csv`). Không dùng wildcard, không xóa qua Recycle Bin, không ép mở khóa file.

**Giữ lại (vẫn còn đến 13:40):**

| Mục | Dung lượng | Lý do giữ |
|---|---|---|
| `bt` (bản sao DB trong scratchpad) | 2,47 GiB | Báo cáo backtest 22/10 gắn với đúng bản sao này (SHA `8ABD356D…`), và runner từ chối chạy trên bản khác. Backup mới chứa dữ liệu sau nhiều lần D-1, không tái tạo lại được trạng thái 23/10 10:20 |
| `Rar$EXa672.19942` | 2,07 GiB | Không tìm thấy file nén gốc (không có archive ≥ 500 MB trong hồ sơ người dùng hay trên D:), nên không chứng minh được có thể giải nén lại |
| 5 thư mục `DemandForecast-deploy-*` cũ | 1,25 GiB | Build không có gói trong `dist`: đây là bản duy nhất |
| Bản cài 1.0.0-1.1.5 | 1,9 GiB | Không có gói phát hành để khôi phục |
| File rời khác ở gốc TEMP | khoảng 6 GiB | Không xác định được chủ sở hữu, một phần mới ghi trong ngày |

Muốn xóa các mục này cần anh/chị xác nhận từng mục (xem mục 7).

## 2. Script dọn thư mục staging của deploy

Trước đây `deploy-upgrade.ps1` giải nén gói vào `%TEMP%\DemandForecast-deploy-<thời điểm>` và không bao giờ xóa. Cách
làm mới:
- Gói được giải nén vào **một** thư mục quản lý `%TEMP%\DemandForecast-deploy\<yyyyMMdd-HHmmss>`, có file đánh dấu
  `.df-deploy-staging.json` (stamp, phiên bản, SHA-256 của gói, PID, người dùng).
- Helper mới: `scripts/_deploy_staging.ps1` (ASCII, đã thêm vào danh sách đóng gói).

Thư mục chỉ bị xóa khi **tất cả** điều kiện sau đúng:
- nâng cấp đạt post-check;
- `current.txt` là phiên bản mới;
- bản mới có `python\python.exe`, không phải link;
- bản rollback vẫn còn;
- không tiến trình nào chạy từ thư mục staging;
- không file nào trong đó đang mở;
- đường dẫn chuẩn hóa nằm đúng trong thư mục quản lý;
- không có junction hay reparse point;
- file đánh dấu khớp lần chạy này.

Các trường hợp khác:
- **Deploy lỗi:** giữ thư mục để điều tra.
- **Không xóa được** (đang dùng, thiếu quyền): giữ lại, ghi cảnh báo vào log. Exit code giữ nguyên như trước.
- **Không bao giờ đụng tới:** thư mục cũ dạng `DemandForecast-deploy-<stamp>` và thư mục không có file đánh dấu của lần
  chạy này.
- **Thứ tự xóa:** nội dung trước, file đánh dấu sau cùng, nên một lần xóa dở vẫn chạy lại được.
- **Đường dẫn dài hơn 260 ký tự:** xử lý được.

**Test:** `backend/tests/test_v1214_deploy_staging.py`, 24 đạt. Đây là PowerShell thật trên thư mục tạm; hai test chạy
nguyên script deploy trong bản cài giả cách ly. Các trường hợp được thử:
- thành công;
- thất bại;
- post-condition không đạt;
- tiến trình chạy từ staging;
- thư mục lạ hoặc file đánh dấu sai;
- 5 kiểu đường dẫn ngoài phạm vi;
- junction;
- file đang mở;
- thiếu quyền (ACL deny), rồi chạy lại sau khi trả quyền;
- thư mục không tồn tại;
- chạy lặp lại;
- kiểm tra tĩnh: ASCII và vị trí gọi.

## 3. Màn hình "Giải thích cách tính Forecast"

**Vị trí:**
- Trang `/forecast-explainer`, menu *Dự báo*.
- API: `GET /api/forecast-explainer[?sku_id=&fc_id=&target_date=]` và `GET /api/forecast-explainer/trees?offset=&limit=`.

**Trang không dùng SHAP hay feature importance.** Nó đi lại đúng đường production đã dùng để tạo ra con số, gồm năm bước;
mỗi bước hiện công thức trước, rồi thay số thật:
1. **Dữ liệu nguồn:**
   - các dòng `demand_daily` của SKU × FC trong cửa sổ huấn luyện;
   - bảng 56 ngày gần nhất, đánh dấu ô nào là đầu vào của model;
   - danh sách thay đổi sau khi tạo forecast, mỗi thay đổi ghi rõ có phải đầu vào hay không.
2. **36 feature:**
   - mỗi feature có ý nghĩa, công thức tổng quát và phép thay số;
   - giá trị đưa vào model được tính bằng đúng hàm production (`build_panel` → `origin_features` + `direct_extra`,
     float32);
   - mỗi feature được tính lại độc lập để đối chiếu.
3. **300 cây:**
   - với từng cây: nút, feature, ngưỡng, giá trị thật, rẽ trái hay phải (gồm giá trị thiếu và tập mã phân loại), lá và
     giá trị lá;
   - hiển thị theo trang 20 cây.
4. **Tổng hợp:**
   - điểm thô = tổng giá trị lá;
   - objective tweedie dùng hàm liên kết log, nên dự đoán = e^(điểm thô).
5. **Kết quả:**
   - `max(0, ·)` → làm tròn 4 chữ số khi lưu → số nguyên `⌊x + 0,5⌋`;
   - so với giá trị đã lưu. Nếu khác: hiện cảnh báo kèm nguyên nhân, **không sửa số**.

**Phần kiểm tra:** 9 kiểm tra đối chiếu với chính LightGBM:
- `pred_leaf`, `raw_score`, `predict`;
- feature tính lại;
- giá trị đã lưu;
- đầu vào đúng như lúc tạo run;
- quy tắc giờ mở bán.

**Chọn SKU:**
- Mặc định là chuỗi LightGBM của run đang dùng có nhiều ngày dữ liệu nhất trong 28 ngày cuối, sau đó đến forecast lớn
  nhất của ngày, vào ngày dự báo đầu tiên tính từ hôm nay.
- Chuỗi dùng quy tắc dự phòng trả `NOT_LIGHTGBM`; dữ liệu DEMO trả `NO_FORECAST`.

**Đúng các ràng buộc của yêu cầu:**
- **Chỉ đọc, không có hành động nào khác:**
  - chỉ có GET; POST/PUT/PATCH/DELETE trả 405;
  - không train, không promote, không tạo job, không ghi; test so sánh số dòng mọi bảng trước và sau.
- **Không đổi gì của production:** feature engineering, model, lịch chạy, SQL nguồn và schema đều giữ nguyên.
- **Không lộ thông tin nội bộ:** phản hồi không chứa `scope_key`, tên project / bảng BigQuery, đường dẫn trên máy hay
  thông tin đăng nhập.
- **Hiển thị số:**
  - định dạng Việt Nam, tối đa 2 chữ số thập phân;
  - giá trị khác 0 nhưng nhỏ hơn 0,005 hiện `≈0,00`;
  - forecast cuối là số nguyên;
  - khi các phần đã làm tròn không cộng đúng tổng, trang ghi chú sai số làm tròn.

## 4. Kiểm thử

| Bộ | Loại | Kết quả |
|---|---|---|
| Backend toàn bộ (`pytest -q -p no:cacheprovider`, 13:00-13:15) | unit + integration với fake | **879 passed / 19 skipped / 0 failed** (15 phút, máy đang tải) |
| `test_v1214_forecast_explainer.py` | integration: model LightGBM DIRECT thật, train trên dữ liệu tổng hợp trong DB test cách ly | 12 passed |
| `test_v1214_deploy_staging.py` | PowerShell thật, bản cài giả cách ly | 24 passed |
| Frontend `npm test` | unit (backend được mock) | **165 passed** (27 file), trong đó `v1214.test.tsx` 6 |
| `npm run typecheck`, `npm run build` | | OK, OK |
| Lint | | chưa cấu hình |
| Dữ liệu thật | instance cách ly trên bản sao DB, không phải production | xem mục 5 |

Test explainer bao gồm:
- chọn chuỗi và run đang dùng;
- feature bằng đúng hàng dự báo của production;
- lá của mọi cây bằng `pred_leaf` và giá trị lá trong file model;
- tổng, hàm liên kết, làm tròn, số nguyên;
- SKU yêu cầu, chuỗi dự phòng, tham số sai;
- không có forecast / DEMO;
- không dùng cache cũ khi có run mới hay dữ liệu đổi; với dữ liệu đổi ×0,01 thì `match = false` và có cảnh báo;
- thay đổi đã ghi log được hoàn về lúc tạo run;
- đọc theo khóa cho đúng các dòng như đọc theo khoảng;
- chỉ đọc, không lộ thông tin;
- bộ nhớ dưới 50 MB và có cache;
- màn hình "Xem cách tính" cũ vẫn chạy.

## 5. Mức độ khớp với forecast production

**Run đang dùng đã đổi trong lúc làm.** Lúc 11:40:31, model `MV-20261026-105345-C73F` được promote qua ứng dụng (audit
`MODEL_PROMOTED`, `promoted_from: PROMOTION_REVIEW_REQUIRED`) và tạo run `FCR-20261026044021-330262`. Phiên này không gửi
yêu cầu promote nào. Yêu cầu ghi duy nhất của phiên tới production là tạo backup theo phần A
(`POST /api/system/backups`, 11:37:54); mọi lệnh gọi khác đều là GET. Backup chụp DB trước lúc promote (trong backup,
run mới nhất là `4EEFD8`). Vì vậy tôi kiểm tra trên cả hai trạng thái.

| Bản sao (cách ly, `DF_DISABLE_SCHEDULER=1`) | Run / model | Giá trị | Kết quả |
|---|---|---|---|
| Backup 11:37 | `FCR-20261024163842-4EEFD8` / `MV-20261024-163642-EA7D` | MEDX.DMTS-DON-SIL-001 × BD, 26/10, horizon 3 | điểm thô 7,795147905253907 = LightGBM (chênh 0); e^ = 2428,788628512767; lưu 2428,7886 = đã lưu → **2429** |
| DB sống, chép bằng backup API (`mode=ro`) lúc 13:14 | `FCR-20261026044021-330262` / `MV-20261026-105345-C73F` (đang dùng) | cùng SKU × FC, 26/10, horizon 1 | điểm thô 7,527942146475376 = LightGBM; e^ = 1859,2754475280374; lưu 1859,2754 = đã lưu → **1859** |
| Như trên | như trên | **mẫu ngẫu nhiên** 12 chuỗi (6 BD, 6 HN) × horizon 1 / 7 / 15, giá trị từ 0,30 đến 71,10 | **36/36 verified, đều khớp giá trị đã lưu**, 0 kiểm tra lỗi; một chuỗi dự phòng trả `NOT_LIGHTGBM` |

- Ở cả hai trạng thái: 36/36 feature tính lại khớp và lá của 300/300 cây bằng LightGBM.
- Bằng chứng:
  - `evidence/explainer-real-copy-direct-call.json`;
  - `explainer-live-copy-1314-auto.json`;
  - `explainer-live-copy-sample-match.json`;
  - ảnh chụp trang `explainer-page-live-copy-run-in-use.png` (forecast cuối 1.859, "Khớp forecast đã lưu").

## 6. Tài nguyên

**Đo trên server cách ly** (`evidence/timing-cold-open-and-key-lookups.txt`):

| | Trước | Sau |
|---|---|---|
| Mở lần đầu sau khi khởi động server | 31,9 s (bộ nhớ đệm tệp đã bị Windows đẩy ra; máy còn khoảng 1,5 GB RAM trống) | **2,5-2,6 s** |
| SKU hoặc ngày khác | 1,4-1,5 s | 1,5-1,6 s (36 lần gọi: trung bình 1,5 s, tối đa 1,85 s) |
| Mở lại (cache) | 12,4 s nếu tham số khác lần trước | 0,1 s |
| Trang 20 cây | 1,2 s | 0,1 s |
| Bộ nhớ riêng của server | +33,5 MB | +33,7 MB lần đầu, +41 MB sau 5 lần gọi; peak working set khoảng 205 MB |

**Nguyên nhân chậm và cách sửa:**
- Bảng `demand_daily` có khóa `(scope_key, order_date, sku_id, fc_id)`. Đọc một chuỗi theo khoảng ngày buộc SQLite quét cả
  cửa sổ, khoảng 1,4 triệu dòng; nhật ký thay đổi cũng 1,37 triệu dòng.
- Nay dòng của chuỗi, danh sách ngày và nhật ký được đọc bằng một lần tra khóa cho mỗi ngày. Kết quả giống hệt (đã kiểm
  bằng test và trên dữ liệu thật); thời gian nóng giảm từ 0,27-0,30 s xuống 0,005 s.
- Đếm ngày để chọn SKU giờ chỉ đọc index, không còn tra bảng.
- Không thêm index, không đổi schema.

**Giới hạn tài nguyên:**
- Mỗi lúc chỉ tính một lần.
- Cache giữ 4 kết quả, xóa sau 30 phút không dùng. Khóa cache gồm run, lần huấn luyện, SHA của model, SKU, FC, ngày, dữ
  liệu của chuỗi, số ngày có dữ liệu và các thay đổi; một bản ghi thay đổi mới làm cache mất hiệu lực ngay.
- Không bao giờ dựng panel toàn phạm vi.

Số "sau" đo ngay sau khi script đo chạy trên cùng file, nên một phần dữ liệu có thể vẫn nằm trong bộ nhớ đệm. Không xóa
được bộ nhớ đệm của Windows mà không có quyền admin. Dù vậy, cách đọc mới chỉ chạm khoảng 300 trang khóa cho mỗi chuỗi.

## 7. Giới hạn và quyết định cần anh/chị phê duyệt

1. **Commit:** chưa commit. Cần anh/chị duyệt; danh sách file ở dưới.
2. **Phát hành và deploy 1.2.14:** cần phê duyệt riêng.
   - Quy trình: `release.ps1`, rồi `deploy-upgrade.ps1 -CheckOnly`, rồi deploy, ngoài các khung giờ chạy lịch.
   - Đây cũng là lần đầu thư mục staging được dọn tự động.
3. **Link công khai chỉ đọc:**
   - `readonly_proxy` chặn `/api/forecast-explainer` (403) ở cả hai chế độ, nên người xem từ xa chưa mở được trang này.
   - Mở cho họ là thay đổi cấu hình link, cần anh/chị cho phép.
   - Thêm nữa, theo kiểm tra bộ nhớ ngày 25/10, link đã ngừng từ 25/10 09:57 và chưa được bật lại.
4. **Các mục giữ lại ở mục 1:** xóa `Rar$EXa672.19942` nếu anh/chị còn giữ file nén gốc. Xóa `bt` khi không cần tái tạo
   backtest 22/10. Build hoặc bản cài cũ không có gói và file rời ở gốc TEMP chỉ xóa khi anh/chị xác nhận.
5. **Model đang dùng:**
   - Đã đổi sang `MV-20261026-105345-C73F` lúc 11:40 qua ứng dụng.
   - Candidate `MV-20261025-225737-C635` vẫn `PROMOTION_REVIEW_REQUIRED`; tôi không promote gì.
6. **Giới hạn của màn hình:**
   - chỉ giải thích model DIRECT (model RECURSIVE trả `UNSUPPORTED_STRATEGY`);
   - chỉ giải thích giá trị do LightGBM tạo, không giải thích quy tắc dự phòng;
   - với run tạo trước 1.2.13, thay đổi dữ liệu xảy ra trước khi có `demand_change_log` không hoàn về được. Nếu nó làm
     lệch kết quả, trang báo không khớp và không sửa số.

## File đã thay đổi trong lô này (chưa commit)

- **Mới:**
  - `backend/app/ml/forecast_explainer.py`
  - `backend/app/api/explainer_routes.py`
  - `backend/tests/test_v1214_forecast_explainer.py`
  - `backend/tests/test_v1214_deploy_staging.py`
  - `frontend/src/explainer.ts`
  - `frontend/src/pages/ForecastExplainer.tsx`
  - `frontend/src/v1214.test.tsx`
  - `scripts/_deploy_staging.ps1`
- **Sửa:**
  - `backend/app/main.py` (thêm router);
  - `frontend/src/App.tsx` (menu và route);
  - `frontend/src/i18n.tsx`;
  - `frontend/src/v125.test.tsx` (danh sách route);
  - `scripts/deploy-upgrade.ps1` (phần staging);
  - `scripts/build-package.ps1` (thêm helper);
  - `CHANGELOG.md`, `docs/MO-HINH-VA-CHI-SO.md`, `docs/VAN-HANH.md`, `docs/CHECKPOINT.md`.
- **Đã có từ các lô trước, chưa commit, lô này không sửa:** công cụ link từ xa (`scripts/remote/*`, `*.bat`,
  `REMOTE_ACCESS_GUIDE.md`, `test_remote_link.py`) và `test_v1213_deploy_preflight.py`.
- **Kiểm tra:** file PS1 chỉ ASCII (có test kiểm tĩnh); không có bí mật trong mã, test hay báo cáo.
- **Git:** `main`, HEAD `e682cf3`, đi trước origin 37 commit, chưa push.
- **Checkpoint trước khi sửa:** `checkpoints/source-1.2.13-before-explainer-staging-20261026.zip`, SHA-256
  `D3614D628831861A072EB24C943D2D8ACD2D92E6BE78356E430AB56368089505`.

## Trạng thái production (chỉ đọc)

- 1.2.13, PID 11964, `current.txt` = 1.2.13, `storage.json` `8D79DBDD…` (không đổi), không có job đang chạy (13:05).
- `data-check` chỉ đọc trên DB sống lúc 13:25 (bằng runtime 1.2.13 đã cài): **34 OK / 3 WARN / 0 FAIL**. Ba WARN giống
  hệt bản backup (`evidence/production-data-check-after.txt`).
- So với backup 11:37:
  - `demand_daily` 1.414.512 dòng và `demand_change_log` 1.374.849 dòng: không đổi;
  - `forecast_runs` 9 → 10, `forecast_values` 1.290.618 → 1.547.868 (+257.250): đúng bằng run được promote lúc 11:40
    (audit ghi `rows: 257250`).
- **Ghi duy nhất:** backup theo phần A (`POST /api/system/backups`; app ghi audit `BACKUP_CREATED`).
- **Không:** deploy, khởi động lại app, đổi lịch, promote, ghi dữ liệu nghiệp vụ, sửa `storage.json` hay cấu hình link.
- **Dọn file tạm của chính phiên:** đã xóa 2 bản sao DB (5,28 GB), profile Edge và `scripts/remote/__pycache__` (do test
  tạo ra).

## Bước tiếp theo nhỏ nhất

Anh/chị xem lại và duyệt commit. Sau đó tôi chạy `release.ps1` cho 1.2.14 và chuẩn bị lệnh deploy để anh/chị tự chạy.

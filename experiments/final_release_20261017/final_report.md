# Báo cáo batch xuyên đêm 1.2.0 — 17/10/2026 (01:40–03:05, giờ Việt Nam)

## A. Trạng thái tổng thể: `PARTIAL`

- Gói 1.2.0 đã build, xác minh và diễn tập cô lập đạt.
- Model ứng viên có Giá đã huấn luyện và chạy inference đạt trên bản sao dữ liệu thật.
- E0 đã xong.

Có hai việc **chưa** làm được:
- **Deploy production bị hệ thống quyền chặn** ("Production Deploy", 02:34). Lệnh bị chặn trước khi chạy và không thay đổi gì.
- **Nguồn BigQuery chưa có ngày 16/10** (`WAIT_FOR_SOURCE`).

Production vẫn chạy 1.1.9 nguyên trạng. Chưa model nào học từ giá được kích hoạt trên production.

## B. Kết quả từng milestone

| Milestone | Trạng thái | Bằng chứng | Blocker |
|---|---|---|---|
| A — Build/release 1.2.0 | `RELEASED` (gói phát hành; **chưa cài lên production**) | Commit cục bộ `775644e` (release) và `577b925` (script E0). `release.ps1` exit 0: backend 324 đạt / 2 bỏ qua, frontend 66/66, typecheck và build đạt. Gói `dist\DemandForecast-1.2.0-win64-portable.zip` (SHA-256 `2343261C8C921AAC0B831760DEC22C029F2C52BF1783900CD142854BAC37F666`, commit `577b925`, `dirty=False`). Diễn tập cô lập 35/37, hai mục còn lại chạy lại tay và đạt | — |
| B — BigQuery/Price/training/inference | `PARTIAL` | Bản sao dữ liệu thật: chuỗi API mapping → kiểm tra toàn kỳ → bật sản xuất; D-1 thử khô; D-0; huấn luyện DIRECT có giá; phát hành ngoại lệ; giải thích; khởi động lại; kiểm tra inference độc lập. Tất cả đạt | Production: deploy bị chặn quyền; ngày 16/10 chưa có trong nguồn |
| C — E0 | Hoàn thành | `e0_report.md`, `e0_results.json`. Tái lập đúng WAPE 0,808117 / 0,805953 | — |

## C. Các tác vụ đã chạy tay

| Tác vụ | Đã chạy tay? | Mode | Kết quả | Run ID / log | Blocker |
|---|---|---|---|---|---|
| BigQuery D-1 | Có | `READ_ONLY_TEST` (BigQuery thật) | Bảng có, 8.893.414 dòng, cập nhật lần cuối 14:08 ngày 16/10. Ngày mới nhất **15/10**. D-1 thử khô trên bản sao: các bước mapping, trùng, tổng hợp, đối soát, so sánh đều PASSED; bước đủ ngày là WARNING (16/10 chưa có); không ghi | `rehearsal/bq_probe.py`; `rehearsal/iso120p_checks.txt` | Ngày 16/10: `WAIT_FOR_SOURCE` |
| BigQuery D-0 | Có | `READ_ONLY_TEST` | Bảng có 9.329 dòng, **chỉ ngày 16/10**, cập nhật lần cuối 14:15 ngày 16/10. 66 dòng thiếu giá | `bq_probe` | Bảng D-0 chưa có ngày 17/10 |
| Price mapping | Có (chỉ bản sao) | `COPY_PIPELINE_TEST` | `POST /api/bigquery/mapping` lưu `unit_price ← sales_price` và tắt sản xuất. Kiểm tra toàn kỳ đạt (3.489.574.092 byte; cảnh báo `KEY_NOT_UNIQUE`, `MISSING_DAYS`, `TARGET_OUTLIER`; không có lỗi chặn). Bật lại sản xuất đạt | `iso120p_checks.txt` | Production: deploy bị chặn |
| D-1 sync | Bản sao: nạp lại toàn kỳ lúc 00:3x (8.893.414 dòng đọc; 1.347.346 không đổi số lượng) | `COPY_PIPELINE_TEST` | Độ phủ giá 99,98 % | `price_decision.md` §5 | Production: deploy bị chặn và chờ nguồn |
| D-0 sync | Có (chỉ bản sao) | `COPY_PIPELINE_TEST` | Job SUCCEEDED, 0 chuỗi: bảng D-0 chưa có ngày 17/10. Không đổi lịch nào | `iso120p_checks.txt` | Nguồn D-0 chưa cập nhật |
| Training có Price | Có (bản sao) | `TRAIN_CANDIDATE` | `TRN-20261016191030-54E15C` → `MV-20261017-022215-E15C`, 804 s. Quality gate chuẩn REJECTED; model được giữ lại để xem xét | `iso120p_checks.txt` | — |
| Candidate inference | Có (bản sao) | `TRAIN_CANDIDATE` | Phát hành ngoại lệ trên bản sao. 257.055 giá trị, 0 NaN / Inf / âm, tái lập sai khác 0,0, nạp lại giống hệt, giá +10 % làm đổi 4.140/4.287 chuỗi LightGBM | `rehearsal/candidate_inference_check_result.json` | — |
| Build / smoke test | Có | Gói thật trên bản sao | Cài 1.1.9 → deploy 1.2.0 (sai SHA và sai token đều bị từ chối) → settings và lịch không đổi → data-check không FAIL → khởi động lại → rollback 1.1.9 → khôi phục | `iso120p_checks.txt` | — |
| E0 | Có | Phân tích chỉ đọc trên bản sao | 3.353.298 điểm, 21 phút | `e0_report.md` | — |

## D. Release

| Mục | Giá trị |
|---|---|
| Version | 1.2.0 |
| Commit | `775644e` (mã + test + tài liệu); `577b925` (script E0; gói build từ commit này) |
| Gói | `D:\Buymed\Lightgbm AI\dist\DemandForecast-1.2.0-win64-portable.zip`, 87,8 MB, SHA-256 `2343261C8C921AAC0B831760DEC22C029F2C52BF1783900CD142854BAC37F666`, source fingerprint `9B946109AD3B7D12` |
| Nội dung gói | Không có `__pycache__`, DB, dữ liệu hay thông tin xác thực (chỉ có chứng chỉ CA của thư viện); `BUILD-INFO` khớp |
| Test | Backend 324 đạt / 2 bỏ qua; frontend 66/66; typecheck và build đạt (log `logs\development\tests_20261017_*.log`). Lint: chưa cấu hình |
| `release.ps1` | Có. Lần 1 dừng ở bước build vì cây làm việc có file mới (cơ chế an toàn đúng). Lần 2 exit 0 |
| Smoke test | Diễn tập `rehearsal/iso120p.ps1`: 35/37 đạt. Hai mục khôi phục lỗi do script đưa tên file trần; chạy lại bằng đường dẫn đầy đủ thì đạt. Đã sửa script và ghi vào `docs/VAN-HANH.md` |
| Backup / rollback | Production **không thay đổi**: fingerprint trước và sau trùng khớp, `storage.json` giữ `8D79DBDD…`, `current.txt` vẫn 1.1.9. Backup production mới nhất: `backups\backup-20261016-235420-manual.zip`. Rollback 1.2.0 → 1.1.9 và khôi phục backup đã diễn tập đạt |
| Push | Không |

## E. BigQuery và dữ liệu

- **Bảng đã xác minh:**
  - D-1 `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm`: 17 cột, asia-southeast1.
  - D-0 `…_D0`: 12 cột.
- **Ngày cuối cùng:** D-1 có đến 15/10 (13/10: 19.473 dòng, 14/10: 20.133, 15/10: 18.992). D-0 chỉ có 16/10.
- **Giá ở nguồn:**
  - D-1, ba ngày gần nhất: 0,6–0,7 % số dòng thiếu giá; 0 dòng giá 0, 0 dòng giá âm.
  - D-0: 66/9.329 dòng thiếu giá.
- **Sau tổng hợp (bản sao):**
  - Độ phủ 99,98 %: 239 ngày-chuỗi NULL, 83 ngày-chuỗi giá bình quân = 0 (giữ nguyên, chưa có quy tắc nghiệp vụ).
  - Không thay giá thiếu bằng giá giả.
- **Byte đã đọc (BigQuery thật, chỉ đọc):**
  - kiểm tra mới nhất: 420.643.426 + 439.415 byte;
  - kiểm tra toàn kỳ trên bản sao: 3.489.574.092 byte;
  - D-1 thử khô trên bản sao: phạm vi tăng dần.
- **Mapping:** đã lưu trên **bản sao**. Production **chưa** lưu (`unit_price` vẫn chưa ánh xạ).
- **Tác động lên production:** không có lần đồng bộ nào ghi vào production.

## F. Model

| Mục | Giá trị |
|---|---|
| Ứng viên | `MV-20261017-022215-E15C` (`TRN-20261016191030-54E15C`). Chỉ có trong môi trường diễn tập cô lập |
| `feature_price` | `true`, lưu tường minh |
| `feature_groups.price.used` | `true` (`DATA_OK`, độ phủ 0,99982) |
| Feature giá trong file model | `price_last`, `price_rel_28` (tổng 31 feature) |
| WAPE / bias / MAE (backtest 7 fold) | 0,808117 / +0,071829 / 6,7517. Quality gate chuẩn (WAPE ≤ 0,60, \|bias\| ≤ 0,20): **không đạt về WAPE**. Đây là rủi ro chất lượng đã biết; luồng ngoại lệ được diễn tập. Ngưỡng chuẩn không đổi |
| Inference | Đạt (§C) |
| Leakage | Test đơn vị `test_price_features_never_read_the_origin_day_or_later`, `test_direct_features_use_only_data_before_the_origin`, `test_direct_backtest_never_sees_the_evaluated_window` đều đạt trong QA |
| Kích hoạt production | **Chưa.** Deploy 1.2.0 bị chặn quyền. Production 1.1.9 không có DIRECT và không có luồng ngoại lệ. Nguồn cũng chưa có 16/10 để nạp lại giá |

## G. E0

- Báo cáo `e0_report.md`; số liệu `e0_results.json`. 3.353.298 điểm, 7 fold.
- **Phát hiện chính:**
  - Sai số tập trung ở chuỗi bán nhiều: ≥ 5/ngày chiếm 85,6 % tổng sai số. 191/9.661 SKU gây 50 %. Chuỗi LightGBM chiếm
    93,6 %.
  - WAPE tăng theo kỳ dự báo: 0,70 ở ngày 1–7, 0,85 ở ngày 16–30.
  - HN kém hơn BD.
  - Model kém ở giai đoạn đổi mức (tháng 3–4, từ giữa tháng 8).
  - Chuỗi giá ổn định có WAPE 0,76, chuỗi giá thay đổi 0,88–0,94. Khi giá sau mốc tăng > 3 %, model dư +0,50 (chỉ là
    tương quan).
- **Hạn chế:** một giai đoạn; giá theo lần nạp mới nhất; giá bình quân phụ thuộc cơ cấu đơn.
- **Không chạy E2, E3, E4.**

## H. Các quyết định đã giữ nguyên

- Price **không** bị tắt ở bất kỳ đâu. Production 1.1.9 vẫn bật (mặc định).
- Lịch D-0 không đổi: tắt, 08:00–18:00 mỗi 2 giờ.
- D-1 03:00 (đang tắt) và training 09:00 (đang bật) không đổi. Training 09:00 hôm nay sẽ **chờ** D-1 theo lịch. D-1 đang
  tắt, nên sẽ không có lần huấn luyện tự động nào.
- Không push Git. Không có thay đổi production nào.
- Chế độ D-0 của production (SQL, chưa có phiên bản) không bị động tới; chỉ bản sao được đổi sang TABLE.

## I. Tiếp tục

- **Checkpoint cuối:** CP4 (gói) và CP8 (E0) hoàn thành. CP5–CP7 trên production dừng ở bước deploy.
- **Điều kiện tiếp tục:**
  1. Chủ dự án cho phép deploy production: thêm quyền, hoặc tự chạy lệnh deploy dưới đây.
  2. Nguồn D-1 có ngày 16/10 (theo hôm qua là khoảng 12:00–14:10).
- **Một lượt production, khi được phép** (thứ tự đã diễn tập):
  1. `scripts\deploy-upgrade.ps1 -Package "D:\Buymed\Lightgbm AI\dist\DemandForecast-1.2.0-win64-portable.zip" -ExpectedSha256 2343261C8C921AAC0B831760DEC22C029F2C52BF1783900CD142854BAC37F666 -ConfirmToken UPGRADE-1.2.0`
     (kiểm tra trước đã đạt lúc 02:33).
  2. Kiểm tra bảng D-0/D-1 → mapping `unit_price ← sales_price` → kiểm tra toàn kỳ → bật sản xuất → D-1 thử khô.
  3. Lưu `feature_price = true`, DIRECT.
  4. Khi nguồn có 16/10: chạy D-1 thủ công (nạp lại toàn kỳ, bản ghi trước/sau).
  5. Huấn luyện thủ công (khoảng 14 phút). Xác nhận `feature_groups.price.used = true`.
  6. Backup → phát hành ngoại lệ (phê duyệt của chủ dự án cho model có Price) → kiểm tra forecast, giải thích, fingerprint.

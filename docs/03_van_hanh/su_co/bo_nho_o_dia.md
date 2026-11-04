# Sự cố bộ nhớ (RAM) và ổ đĩa

Audit tài nguyên, bộ nhớ Windows và dọn ổ đĩa 22–26/10/2026.

Tài liệu gộp ngày 03/11/2026 theo bảng 1.3 (cấu trúc lại tài liệu). Nội dung từng nguồn được chép nguyên văn, chỉ hạ một cấp tiêu đề và sửa đường dẫn liên kết; số liệu và trạng thái là của thời điểm từng báo cáo, quy tắc hiện hành nằm trong các tài liệu chính (xem [README](../../README.md)). Dữ liệu đi kèm (parquet, csv, xlsx, zip, json) vẫn ở thư mục `reports\` gốc, ngoài Git.

## Nguồn

| # | File gốc (worktree) | Ngày sửa | Byte | SHA-256 |
|---|---|---|---:|---|
| 1 | `reports\resource-audit-20261022\FINAL_REPORT.md` (MAIN) | 22/10/2026 | 17319 | `A7118A92635636A9641964089FF9095B26ADFAFF86A9F90A1A9141898ADF732D` |
| 2 | `reports\windows-disk-cleanup-20261026-095823\BEFORE_AFTER.md` (MAIN) | 26/10/2026 | 3471 | `2A97F570BB2A277BD81BB86459E07269E49FC94134D77C112EEAB231C4337D12` |
| 3 | `reports\windows-disk-cleanup-20261026-095823\FINAL_REPORT.md` (MAIN) | 26/10/2026 | 10760 | `32E58A9D08449D51953FAED25D121583319434ED11BA48EDE1FE803F9DA36A0F` |
| 4 | `reports\windows-disk-cleanup-20261026-095823\ROLLBACK_NOTES.md` (MAIN) | 26/10/2026 | 5060 | `345F2579778A251448DFE5353C7657B67EB4BEE9E989682E8FE3A7F8A5D91ECA` |
| 5 | `reports\windows-memory-audit-20261025-223332\DEMANDFORECAST_MEMORY_AUDIT.md` (MAIN) | 25/10/2026 | 15709 | `7F3E92B6926EA4479B72C846F2CE418B40ED31207D6184FB92242EC1E7B6931B` |
| 6 | `reports\windows-memory-audit-20261025-223332\EVIDENCE.md` (MAIN) | 25/10/2026 | 9261 | `DFB0187C4EED186767B0548399645EEECDEE24E57A6EDFBFC50DF7FBBE5A3B85` |
| 7 | `reports\windows-memory-audit-20261025-223332\FINAL_REPORT.md` (MAIN) | 25/10/2026 | 18995 | `B7EE604C5DADB736F998F78570A079557F5FD0FF2E47B6BC5CF553A75FC02366` |
| 8 | `reports\windows-memory-audit-20261025-223332\REMEDIATION_PLAN.md` (MAIN) | 25/10/2026 | 11877 | `3F4726249B5D703AA95A47896A5FA0A1C7ED941D0D07BFFD054DCC7B425F5CE8` |

## 1. Audit và tối ưu tài nguyên - Demand Forecasting / LightGBM (22/10/2026)

Nguồn: `reports\resource-audit-20261022\FINAL_REPORT.md` (worktree MAIN).

**Trạng thái:** `READY_FOR_EXTERNAL_SETUP`.
- Mã đã sửa và kiểm chứng trên bản sao production. Chưa commit, chưa triển khai.
- Dọn ổ đĩa đã xác minh an toàn nhưng bị bộ phân loại quyền của Claude Code từ chối. Chủ hệ thống quyết định.

Bằng chứng nằm trong `evidence\` cạnh file này, workbook là `RESOURCE_AUDIT_*.xlsx`. Mọi số đo lấy trên bản sao cách ly
của database production: scheduler tắt, BigQuery chỉ đọc. Production chỉ được đọc trạng thái.

### 1. Trạng thái diễn tập

**Hoàn tất 13:50:54 - 14:58:16, `exit=0`:**
- 9/9 khối.
- Chạy lại không đổi gì: 0 dòng nhật ký mới, 0 dòng giữ mới.
- Rollback `RBK-20261022074834-EDB725` khôi phục đúng sha256 của khối, kể cả `loaded_at`.
- Áp lại cho đúng 35 bản ghi và 176 dòng giữ như lần đầu.
- Kiểm tra cuối MATCH 294/294 ngày.

Chi tiết: `reports\history-sync-20261022\`.

**Log và checkpoint đã lưu trước khi chuyển giai đoạn:**
- `reports\history-sync-20261022\evidence\rehearsal.log`, `rehearsal.json`;
- `checkpoints\source-1.2.13-history-sync-rehearsed-20261022.zip` (`64EB8205…2D0F`).

**Monitor im lặng: nguyên nhân thật là lệnh `cut` trong pipeline Git Bash.** `cut` gom toàn bộ output vào bộ đệm, nên không
có dòng nào ra. Lỗi không nằm ở `tail -f`.
- Cách sửa: watcher PowerShell đọc phần mới của file bằng `FileShare.ReadWrite` (không chặn tiến trình ghi), in từng
  dòng, dừng ở dấu kết thúc.
- Test trên Windows: một tiến trình khác giữ file mở và ghi, có một dòng ghi làm hai lần. Kết quả **PASS**, 5/5 dòng đúng
  thứ tự.
- Chính test này bắt được một lỗi của watcher: dải `0..-1` của PowerShell in dòng dở hai lần. Đã sửa.
- Lưu ý vận hành: Explorer / `Get-ChildItem` có thể hiện kích thước và giờ cũ của file đang mở. Ví dụ `app.log` hiện
  178.786 byte trong khi file thật 200.679 byte. Luôn mở file để đọc.

### 2. Nguyên nhân thiếu RAM / máy chậm (có số đo)

**1. Máy đầy bộ nhớ trước khi app chạy job.**
- RAM 16 GB. Lúc 15:15 chỉ còn **1.095 MB khả dụng (6,8 %)**, commit 84 % (44 / 52,6 GB), page file đang dùng 6,65 GB
  (đỉnh 8,78 GB).
- Bộ nhớ riêng (private) theo nhóm:
  - trình duyệt khoảng 13,6 GB: Chrome 20 tiến trình 5,96 GB; Edge WebView2 33 tiến trình 3,72 GB; Brave 18 tiến trình
    3,52 GB;
  - VS Code 4,57 GB; Claude Code 1,69 GB; Zalo 1,59 GB; Java 1,13 GB.
- Một tiến trình **python của tài khoản Windows khác** (PID 10412, chạy từ lúc khởi động 14/10) dùng **4,19 GB**. Không
  thuộc dự án, không chạm vào.

**2. Các tiến trình của dự án.**
- App production (PID 7316, 1.2.11): 2.752 MB private nhưng chỉ 29 MB nằm trong RAM. Windows đã đẩy phần còn lại ra page
  file. Đỉnh working set 2,6 GB.
- Proxy 16 MB; tunnel 71 MB.

**3. Job nặng nhất là huấn luyện**, chạy ngay trong tiến trình server.
- Baseline: **+2.403 MB private ở đỉnh**, 1.672 s, 25 lần fit LightGBM (12 fold + 12 fold đánh giá model đang dùng + 1
  fit cuối).
- RAM trống của máy rơi xuống **92 MB**; 18,5 triệu page fault.
- Diễn tập lịch sử chậm gấp đôi vì cùng lý do: CPU kernel bằng CPU user, 8,85 triệu page fault.

**4. Mã giữ bộ nhớ không cần** (dữ liệu production):
- ma trận huấn luyện ghép bằng `np.vstack`: giữ đồng thời các mảnh và bản ghép, **2 × 676 MB**;
- ma trận thô float32 (676 MB) nằm trong RAM suốt 300 vòng boosting của mỗi fit, dù LightGBM đã bin xong;
- khung dữ liệu đã nạp (khoảng 300 MB) được giữ đến hết job;
- xuất Excel dự báo: +1,17 GB khi tạo, **0,94 GB vẫn bị giữ sau khi trả về**. Đó là rác vòng của openpyxl, chỉ được thu
  khi Python tự dọn toàn bộ;
- cache giải thích: mục cũ giữ panel của phiên bản dữ liệu cũ (khoảng 190 MB mỗi phiên bản), tối đa 32 mục.

**5. Có thể chạy trùng.**
- Job quá timeout nhả khóa ngay trong khi luồng cũ vẫn chạy. Lần thử lại có thể chạy song song, ví dụ hai lần huấn luyện
  cùng lúc.
- Huấn luyện theo lịch không bị chặn khi job nặng khác đang chạy. Chỉ nút chạy tay kiểm tra điều này.

**6. Không có rò rỉ.**
- Lặp 3 lần báo cáo chất lượng, nạp dữ liệu và dựng panel trong một tiến trình: đối tượng Python còn sống **0,2 MB**.
  Bộ nhớ tiến trình tăng khoảng 10 MB mỗi lần (mức đỉnh bộ cấp phát giữ lại).
- 2,75 GB của server production **không quy được cho job nào trong log**:
  - 2 lần huấn luyện dừng ở cổng giờ mở bán trước khi nạp dữ liệu;
  - 3 lần D-1 có đỉnh khoảng +0,33 GB;
  - thao tác giao diện không có nhật ký request.
- Ứng viên đã đo: xuất Excel (đã sửa), panel giải thích (đã sửa), trang chất lượng dữ liệu (+1,0 GB đỉnh, giữ +175 MB).
  Từ nay mỗi job tự ghi số liệu tài nguyên.

**7. Ổ C: gần đầy: 9,8 GB trống / 375 GB.** Phần của dự án trên C: khoảng 35 GB: 29 GB bản sao tạm của các phiên Claude,
5,9 GB của 20 phiên bản đã cài.

### 3. Baseline (trước tối ưu)

Cùng một tiến trình, như server, trên bản sao production. Bộ nhớ sau khi import: 423 MB.

| Tác vụ | Thời gian | Đỉnh tăng | Còn giữ sau tác vụ | CPU |
|---|---|---|---|---|
| Nạp dữ liệu (1.364.268 dòng, 13 cột, khung 296 MB) | 28,5 s | +1.130 MB | (khung còn dùng) | 26,5 s |
| Dựng panel (17.134 chuỗi × 294 ngày, 192 MB) | 18,3 s | +544 MB | (panel còn dùng) | 17,0 s |
| Báo cáo chất lượng dữ liệu | 63,8 s | +1.008 MB | +175 MB | 48,1 s |
| D-1 thường + kiểm tra lịch sử (BigQuery thật) | 194 s | +331 MB | +105 MB | 155 s |
| Snapshot EOD | 6,6 s | +75 MB | +15 MB | 4,7 s |
| **Huấn luyện + backtest** | **1.672 s** | **+2.403 MB** (đỉnh 3.118) | +168 MB | 9.460 s |
| Xuất Excel dự báo (đo riêng) | 45,2 s | +1.169 MB | **+940 MB** đến khi GC | - |

- Huấn luyện production 20/10: 30 phút 17 giây.
- BigQuery của server production từ 21/10 18:08:

  | Loại truy vấn | Số lần | Ước tính |
  |---|---|---|
  | `daily` | 5 | 6,73 GB (67 s mỗi lần) |
  | `dup_check` | 5 | 8,49 GB |
  | `sufficiency` | 8 | 0,58 GB |
  | `product_names` | 3 | 0,07 GB |
  | `d0` | 4 | 3,5 MB |

  Khoảng 3,2 GB mỗi lần D-1, vì bảng nguồn không partition.
- Một lần D-1 đọc **12,6 GB** qua ReadFile, khoảng 15 lượt đọc database 850 MB, phần lớn từ cache của Windows.

### 4. Dung lượng

**Thư mục lớn nhất:**
- Ổ C:
  - bản sao tạm của phiên Claude: 29,0 GB, gồm `r7`-`r13` (10,4 GB) và các bản sao DB `p20`-`p31`;
  - 20 phiên bản đã cài: 5,9 GB.
- Ổ D:
  - `backups` 3,07 GB (64 file); `dist` 1,80 GB; `data` 0,87 GB; `.venv` 0,46 GB; `checkpoints` 0,46 GB.
  - Database 848 MB: WAL 0 byte, 0 trang trống, **không cần VACUUM**.

**Thu hồi an toàn, đã xác minh đủ 7 bước: 15,4 GB, chưa xóa.**
- Gồm: rehearsal cài đặt cách ly `r7`-`r12`; các file bản sao DB trong `p26` / `p27` / `p28` / `p30`.
- Kiểm tra từng mục:
  - không tiến trình nào đang dùng (kiểm tra bằng đổi tên);
  - gói cài tương ứng còn trong `dist` và SHA-256 khớp file `.sha256`;
  - trạng thái DB có backup chính thức bao phủ, đã kiểm tra bằng zip test;
  - log và JSON nhỏ được nén làm bằng chứng trước khi xóa.
- Lệnh xóa bị bộ phân loại quyền từ chối ("Irreversible Local Destruction"). **Không** tìm cách khác.
- Kế hoạch: `evidence\scratch_cleanup_plan_dryrun.json`.

**Kế hoạch cần chủ hệ thống duyệt:**
- 17 phiên bản đã cài, khoảng 5,0 GB trên C:. Giữ 1.2.11 (đang chạy), 1.2.10 (rollback) và 1.2.6 (proxy đang dùng Python
  của nó). Các bản schema cũ không còn chạy được trên database hiện tại.
- Bản sao `p21` / `p24` / `p25`: 2,95 GB. Trạng thái 20/10 19:15 - 21/10 01:16 không có backup chính thức, nên chỉ lập
  kế hoạch.
- `backups` / `dist`: theo `scripts\prune-artifacts.ps1`, chạy thử trước.

**Tăng trưởng database: khoảng 13 MB/ngày.**
- Snapshot EOD 11,8 MB/ngày, dọn 90 ngày bằng tay theo quy trình sẵn có.
- 1.2.13 thêm khoảng 3 MB/ngày: nhật ký thay đổi cho mỗi khóa mới.

### 5. Thay đổi đã thực hiện

Chưa commit, trên `24590d2` cùng 1.2.13.

| File | Thay đổi | Mức |
|---|---|---|
| `backend/app/jobs/resources.py` (mới) | Số liệu tiến trình và máy qua Win32 API (Windows) / `/proc` (Linux), không thêm gói. `JobMeter` lấy mẫu 2 s | A |
| `backend/app/jobs/runner.py` | Mỗi lần thử ghi `resources` vào kết quả job và log `job resources`. Luồng quá timeout giữ khóa đến khi thật sự kết thúc. Không bao giờ chạy hai job nặng cùng lúc. Kiểm tra bộ nhớ đo được trước job nặng: `INSUFFICIENT_MEMORY` có giới hạn, `PAGING_EXPECTED` | A |
| `backend/app/jobs/scheduler.py`, `ml/explain.py`, `ml/shap_audit.py` | Panel cũ bị bỏ ngay khi phiên bản đổi. Panel và vết SHAP trả lại sau 30 phút không dùng | A |
| `backend/app/ml/pipeline.py` | Bỏ khung dữ liệu sau khi dựng panel | A |
| `backend/app/ml/model.py` | Bỏ ma trận thô sau khi LightGBM bin xong | A |
| `backend/app/ml/features.py` | Ma trận huấn luyện ghi vào một mảng cấp phát sẵn thay vì `np.vstack`; nhánh `with_index` giữ nguyên | B |
| `backend/app/data/excel_io.py` | Thu rác vòng của workbook ngay sau khi xuất | A |
| `backend/app/messages.py` | Mã `INSUFFICIENT_MEMORY` (song ngữ) | - |
| `backend/tests/test_v1213_job_resources.py` (mới) | 17 test | - |
| `docs/03_van_hanh/SCHEDULER.md`, `docs/03_van_hanh/VAN-HANH.md`, `CHANGELOG.md`, `docs/03_van_hanh/CHECKPOINT.md` | Tài liệu | - |

**Đã thử nhưng không giữ:** `gc.collect` và nén heap sau mỗi job. Đo được 0 MB sau huấn luyện, 6 MB sau D-1.

**Không đổi:** tham số LightGBM, feature, số vòng, số fold, cửa sổ dữ liệu, quy tắc nghiệp vụ, lịch, cài đặt,
`customer_id` OFF, weekday.

### 6. Benchmark sau tối ưu

Cùng bản sao gốc, cùng các bước, cùng máy.

| Chỉ số | Trước | Sau | Thay đổi |
|---|---|---|---|
| Huấn luyện: đỉnh tăng | +2.403 MB | +1.670 MB | **−733 MB (−31 %)** |
| Huấn luyện: trung bình | 2.440 MB | 1.853 MB | **−587 MB (−24 %)** |
| Huấn luyện: còn giữ sau job | +168 MB | +95 MB | −73 MB |
| Dựng ma trận huấn luyện (5.210.362 × 34) | +1.439 MB | +759 MB | **−680 MB (−47 %)** |
| Xuất Excel: còn giữ khi trả về | +940 MB | +264 MB | **−676 MB** |
| Huấn luyện: thời gian | 1.672 s | 1.355 s | −19 %, xem ghi chú |
| Huấn luyện: CPU | 9.460 s | 12.612 s | không so sánh được, xem ghi chú |

**Ghi chú:**
- Thời gian và CPU phụ thuộc tải máy lúc chạy: RAM trống thấp nhất 92 MB khi chạy trước, 433 MB khi chạy sau. Khi máy
  phân trang, các luồng bị nghẽn (5,7 lõi so với 9,3 lõi). Không quy toàn bộ −19 % cho mã.
- Bộ nhớ là số đo theo tiến trình, không phụ thuộc tải máy.
- Bản đo sau chạy với lệnh dọn sau job, lệnh này sau đó đã bỏ. Chênh lệch tối đa 6 MB.
- Mã nạp dữ liệu, panel, báo cáo chất lượng và D-1 không đổi: chênh lệch của các bước đó giữa hai lần đo là sai số đo,
  không phải kết quả tối ưu.

**Số liệu job khớp bộ lấy mẫu ngoài** (0,2 s):
- huấn luyện: đỉnh 2.338,2 so với 2.339 MB; thời gian 1.354,4 so với 1.354,7 s;
- D-1: 871,8 so với 872 MB.
- Giới hạn: mẫu 2 s bỏ sót đỉnh của job dài 1 giây, ví dụ EOD.

### 7. Chất lượng model

Không đổi cấu hình huấn luyện. Huấn luyện trên hai bản sao giống nhau, trước và sau thay đổi:
- **file model giống từng byte**: SHA-256 `68b95f225cac824a5a945c0fb1d6e4cd1c38ca06bd82a17117ff018c06a78b2c`, 5.363.789 byte;
- WAPE 0,8074271198390075 và bias 0,0625360209 trên **cùng 3.364.320 điểm backtest**, giống hệt;
- quality gate và so sánh với model đang dùng giống hệt: WORSE, không promote.

### 8. Kiểm thử

| Bộ | Loại | Kết quả |
|---|---|---|
| Backend toàn bộ, mã cuối | unit + integration với nguồn giả, DB tạm cách ly | **768 passed / 19 skipped / 0 failed** (353 s, 17:02; 19 skipped = test BigQuery / D-0 thật tùy chọn) |
| `test_v1213_job_resources.py` | unit / integration | **17 passed**: số liệu job, khóa sau timeout, hai job nặng, bảo vệ bộ nhớ có giới hạn, job nhẹ không bị chặn, cache giải thích, ma trận và model giống hệt, Excel không để lại workbook |
| Lần chạy toàn bộ đầu tiên | - | 765 passed, 3 failed. Cả 3 lỗi nằm ở test mới (closure đọc biến sau khi đổi giá trị; id trùng trong dữ liệu test). Đã sửa test, không nới điều kiện nào |
| Monitor trên Windows | test thật, hai tiến trình | PASS 5/5 sau khi sửa lỗi dải `0..-1` |
| Ma trận trên dữ liệu production | DB copy | bằng nhau tuyệt đối (giá trị, NaN, kiểu, kích thước) |
| Lint | - | không cấu hình |

### 9. Báo cáo Excel

`reports\resource-audit-20261022\RESOURCE_AUDIT_RAM_CPU_DISK_20261022-1702.xlsx`
(SHA-256 `104C12AF08EBE2CDB29DA41CBEC76E2BCD92041F40B38BC1C8D2187BB6B8ED94`).

16 sheet, mọi chênh lệch / tỷ lệ là công thức, có bộ lọc:
- tổng quan và bất thường: `Executive_Summary`;
- bộ nhớ: `Memory_By_Task`, `Before_After` (cột ghi rõ bước nào có đổi mã), `Export_Fix`, `Matrix_Check`,
  `Model_Identity`, `Job_Resources`, `Leak_Check`;
- máy: `Processes`, `Machine_Memory`;
- ổ đĩa và dữ liệu: `Disk_Inventory` (phân loại từng thư mục), `Scratch_Cleanup_Plan`, `DB_Tables`, `BigQuery`;
- cấu hình và thay đổi: `LightGBM_Config`, `Changes_Tests`.

### 10. Checkpoint và backup

| Mục | Đường dẫn | SHA-256 |
|---|---|---|
| Trước khi sửa | `checkpoints\source-1.2.13-before-resource-audit-20261022.zip` | `B66AFA98D1F37D4967016612807E402081B14920293CA5C9248F906E6574D63D` |
| Sau khi sửa: 36 file đổi / mới của 1.2.13 + audit, trạng thái git, bằng chứng và script `p32`; 82 mục, đã kiểm tra | `checkpoints\source-1.2.13-after-resource-audit-20261022.zip` | `A388ECADE077071DA3CC04B3733151741CFDB9F5D3B14FE6DD8D77A13E7B1708` |

- Không ghi gì vào production, nên không cần backup production.
- Bản sao benchmark `b1`, `b2`, `bench_src` (khoảng 2,6 GB, ổ C:) là file tạm của phiên, có trong kế hoạch dọn.

### 11. Ảnh hưởng production

**Không có.**
- `/api/health` = 1.2.11 (PID 7316); `current.txt` 1.2.11; `storage.json` `8D79DBDD…E047`; DB schema 9.
- D-0 16:00 vẫn SUCCEEDED trong 5 s khi benchmark đang chạy.
- Không triển khai, không push, không đổi lịch, cài đặt, credentials hay hosting. Không promote.
- BigQuery chỉ đọc: hai lần D-1 trên bản sao, khoảng 3,5 GB mỗi lần.

### 12. Việc cần chủ hệ thống quyết định

1. **Dọn 15,4 GB trên C:** đã xác minh, bộ phân loại quyền chặn. Chủ hệ thống tự chạy
   lệnh sau trong PowerShell: chạy thử trước (không có `--apply`), xem kế hoạch, rồi thêm `--apply`. Hoặc cho phép
   thao tác này.

   ```powershell
   & "D:\Buymed\Lightgbm AI\.venv\Scripts\python.exe" "C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\p32\cleanup_scratch.py" "D:\Buymed\Lightgbm AI\reports\resource-audit-20261022\evidence\scratch_cleanup_manifest.json" --apply
   ```

   Có thể dọn thêm 2,6 GB bản sao benchmark và, nếu đồng ý, 2,95 GB `p21` / `p24` / `p25`.
2. **Gỡ 17 phiên bản đã cài cũ, khoảng 5,0 GB trên C:.** Giữ 1.2.11, 1.2.10 và 1.2.6.
3. **Commit 1.2.13** (đồng bộ lịch sử + tối ưu tài nguyên; cần duyệt theo AGENTS.md mục 8). Sau đó đóng gói và triển
   khai sau 1.2.12; 1.2.12 vẫn chờ chủ hệ thống chạy `deploy-upgrade`.
4. **Partition bảng nguồn D-1 theo ngày và cluster theo SKU / FC.** Bảng có ghi chú PIC giau.vo. Mỗi lần D-1 hiện quét
   khoảng 3,2 GB. Mức giảm chỉ đo được bằng dry run sau khi đổi.
5. **Xác định tiến trình python 4,19 GB** (PID 10412, tài khoản khác, chạy từ 14/10).
6. *(Tùy chọn)* Thử `num_threads` 12 / 10 / 8 có đo WAPE / bias. CPU i5-1335U có 2 lõi P và 8 lõi E. Cần khoảng 1-2 giờ
   máy rảnh; chưa chạy, chưa đổi gì.

## 2. Dung lượng trước và sau khi dọn (26/10/2026)

Nguồn: `reports\windows-disk-cleanup-20261026-095823\BEFORE_AFTER.md` (worktree MAIN).

**Đơn vị:** byte lấy từ Windows (`Win32_LogicalDisk.FreeSpace`); GiB = 1.024³ byte, cách Explorer hiển thị "GB".

### Ổ C: (375 GB) và D: (100 GB)

| Thời điểm | C: trống | D: trống | Ghi chú |
|---|---|---|---|
| 09:58:23, đo đầu phiên | 31.409.360.896 B (29,25 GiB) | 76.349.345.792 B (71,11 GiB) | Lúc này một D-1 chạy tay đang chạy |
| 10:54:10, ngay trước lần xóa đầu tiên | **30.891.614.208 B (28,77 GiB)** | 76.339.707.904 B (71,10 GiB) | Sau lần huấn luyện tay 10:18-10:53. Page file và dữ liệu tạm của các ứng dụng làm C: giảm 0,5 GB |
| 10:57:42, sau nhóm B (33 thư mục deploy) | 40.227.180.544 B (37,46 GiB) | 76.339.707.904 B | +9,34 GB |
| 10:58:54, sau nhóm D (12 bản app cũ) | 43.990.380.544 B (40,97 GiB) | 76.339.707.904 B | +3,76 GB |
| khoảng 11:00, nhóm A lần 1 (43 mục, dừng vì đường dẫn dài) | 64.774.914.048 B (60,33 GiB) | 76.339.707.904 B | +20,78 GB, đo lúc bắt đầu lần 2 |
| 11:03:15, sau nhóm A lần 2 (61 mục) | 76.705.755.136 B (71,44 GiB) | 76.339.707.904 B | +11,93 GB |
| 11:03:54, sau nhóm C (18 mục) | 84.467.982.336 B (78,67 GiB) | 76.339.707.904 B | +7,76 GB |
| 11:05:12, kiểm tra cuối | **84.463.898.624 B (78,66 GiB)** | **76.339.675.136 B (71,10 GiB)** | |

**Kết quả:**
- **C: tăng 53.572.284.416 byte (49,89 GiB)** so với ngay trước khi xóa, và tăng 49,41 GiB so với lúc bắt đầu phiên.
  Tổng byte của các mục đã xóa là 52.582.754.531 (48,97 GiB). Phần chênh là các cluster mà hơn 599 nghìn file nhỏ chiếm
  thêm ngoài kích thước thật.
- **D: không đổi do dọn dẹp.** Không xóa gì trên D:; script dọn từ chối mọi đường dẫn trên D:. Chênh 9,7 MB so với 09:58
  là do app ghi database và log trong các job của người dùng.

### Theo thư mục

| Thư mục | Trước | Sau |
|---|---|---|
| `%LOCALAPPDATA%\Temp` (toàn bộ) | 63,03 GiB (25/10 23:02) | **17,37 GiB** |
| `%LOCALAPPDATA%\Temp\claude` | 34,57 GiB (25/10 23:02) | **4,39 GiB** |
| Scratchpad phiên Claude `672ca914…` | 34,56 GiB | **4,37 GiB**: `bt` 2,47 GiB + `models\`, script, ảnh chụp, log được giữ |
| `%TEMP%\DemandForecast-deploy-*` | 38 thư mục, 9,52 GiB | **5 thư mục, 1,25 GiB** |
| `%LOCALAPPDATA%\Programs\DemandForecast` | 21 bản, 5,79 GiB | **9 bản, 2,48 GiB** |
| Thùng rác (Recycle Bin) của người dùng trên C: | - | 492 MB, mục mới nhất ngày 24/10: **không có gì được chuyển vào thùng rác** |

### Theo nhóm

| Nhóm | Ước tính trong báo cáo audit | Đã xóa | Số mục | Số file | Giữ lại |
|---|---|---|---|---|---|
| A. Thư mục tạm Claude | 34,6 GB | **30,18 GiB** (32.410.222.825 B) | 104 | 261.764 | 2,47 GiB (`bt`) + file nhỏ khoảng 1,9 GiB |
| B. `DemandForecast-deploy-*` | 9,5 GB (38) | **8,26 GiB** (8.872.108.196 B) | 33 | 235.688 | 5 thư mục, 1,25 GiB |
| C. File cài đặt tạm | 10,5 GB | **7,21 GiB** (7.743.185.122 B) | 18 | 791 | 9,6 GiB (xem `SKIPPED_FILES.csv`) |
| D. Bản app cũ | 5,5 GB ("21 bản", thực tế 19 bản cũ) | **3,31 GiB** (3.557.238.388 B) | 12 | 101.266 | 1.0.0-1.1.5 (7 bản, 1,93 GiB) + 1.2.11 + 1.2.13 |
| **Tổng** | 60-65 GB | **48,97 GiB** (52.582.754.531 B) | **167** | **599.509** | khoảng 17 GiB, chưa xác minh được hoặc cố ý giữ |

## 3. Dọn ổ đĩa an toàn: kết quả (26/10/2026, 09:58-11:10)

Nguồn: `reports\windows-disk-cleanup-20261026-095823\FINAL_REPORT.md` (worktree MAIN).

### Trạng thái: `PARTIAL`

**Đã làm:**
- Dọn hết các mục đã xác minh an toàn: **167 mục, 599.509 file, 48,97 GiB**.
- **C: trống từ 28,77 GiB lên 78,66 GiB (+49,89 GiB).**
- Kiểm tra sau dọn đều đạt.

**Chưa đạt mục tiêu 60-65 GB.** Khoảng **17 GiB** được giữ lại có chủ đích, vì không xác minh được là an toàn hoặc vì là bản
duy nhất. Danh sách ở `SKIPPED_FILES.csv`.

| Mục | Trước | Sau |
|---|---|---|
| C: trống | 30.891.614.208 B (28,77 GiB) ngay trước khi xóa; 29,25 GiB lúc 09:58 | **84.463.898.624 B (78,66 GiB)** |
| D: trống | 76.339.707.904 B (71,10 GiB) | 76.339.675.136 B (71,10 GiB): không xóa gì trên D: |
| Số mục đã xóa / bỏ qua | 167 mục trong kế hoạch | **167 đã xóa, 0 bị bỏ qua lúc chạy, 0 lỗi còn tồn tại**; 30 mục giữ lại từ bước lập kế hoạch |

| Nhóm | Đã giải phóng | Mục / file | Giữ lại |
|---|---|---|---|
| A. Thư mục tạm Claude (ước tính 34,6 GB) | **30,18 GiB** | 104 / 261.764 | `bt` 2,47 GiB (không có backup tương ứng) + model, script, ảnh chụp, log |
| B. `DemandForecast-deploy-*` (38 thư mục) | **8,26 GiB** | 33 / 235.688 | 5 thư mục, 1,25 GiB: build không tái tạo được từ `dist` |
| C. File cài đặt tạm (ước tính 10,5 GB) | **7,21 GiB** | 18 / 791 | 9,6 GiB: WinRAR tạm 2,07; Autodesk mới nhất 0,80; bản cập nhật VS Code; zip không rõ chủ; 5,6 GiB file rời ở gốc TEMP |
| D. Bản app cũ | **3,31 GiB** | 12 / 101.266 | 1.0.0-1.1.5 (không có gói), 1.2.11 (rollback), 1.2.13 (đang chạy) |

**Đính chính báo cáo audit 25/10:** máy có **21** bản cài (không phải 23), tức **19** bản cũ (không phải 21).

### 1. Cách xác định và xác minh

**Áp dụng cho mọi nhóm:**
- Đo bằng metadata (`robocopy /L` chỉ liệt kê, kích thước, thời gian). Không mở file cá nhân.
- Kiểm tra chỉ đọc rằng không ứng dụng nào dùng tới:
  - **tiến trình** chạy từ các vùng này: chỉ có app 1.2.13 (PID 11964);
  - **207 tác vụ** Scheduled Task (gồm cả tham số);
  - **168 shortcut** Desktop / Start Menu: hai shortcut app trỏ vào 1.2.13; bốn shortcut link trỏ vào `DemandForecastRemote`;
  - khóa Run;
  - `storage.json`, `runtime.json`, `link.json`.
- Kết quả: **không có tham chiếu nào tới mục bị xóa.**

**Nhóm A, scratchpad của phiên Claude:**
- **Bản sao database:** chỉ xóa khi có backup chính thức chứa **cùng trạng thái dữ liệu nhu cầu**, tức là giữa lúc sao chép và
  lúc backup không có lần D-1 hay backfill thành công nào (`evidence\dbcopy-coverage.csv`).
  - 23 bản sao lớn đã xóa đều đạt điều kiện này.
  - **`bt` không đạt**, nên được giữ. Đó là bản sao 23/10 10:20 sau lần nạp lại toàn bộ, trong khi backup chính thức mới nhất
    là 23/10 00:10.
  - Hai file nhỏ `inspect-copy.db` / `polluted-copy.db` (63 MB) không đưa vào kế hoạch và vẫn còn.
- **Chỉ xóa file / thư mục database và backup của bản sao.** `models\` được giữ, gồm cả các model chỉ có ở đây (8EB8, B675,
  9170); `copy.json`, script và log cũng được giữ.
- **Bản cài diễn tập `r7`-`r14`:** 24 thư mục build giống hệt gói `dist`. Kiểm tra từng file theo manifest: thiếu 0, khác
  kích thước 0, phần thêm chỉ là `.pyc`.
- **37 profile trình duyệt thử nghiệm:** chỉ xóa profile; ảnh chụp và kết quả bên cạnh được giữ.

**Nhóm B, thư mục giải nén gói:**
- Vòng đời: `deploy-upgrade.ps1:133-136` giải nén gói vào `%TEMP%`, rồi `install.ps1:115-118` chép sang `Programs`. Shortcut,
  autostart và `rollback-version.ps1` đều chỉ dùng `Programs`.
- **33 thư mục đã xóa** đều giống hệt gói trong `dist`, theo hai cách đối chiếu:
  - BUILD-INFO commit + fingerprint;
  - với 1.1.6 / 1.1.8: SHA-256 từng file.
  
  SHA-256 của mỗi zip cũng khớp file `.sha256`.
- **5 thư mục giữ lại:** 3 build bị thay thế (gói đã xóa theo chính sách), 1 bản 1.1.6 cũ khác gói ở 24 file, và 1.1.7 không có
  gói.

**Nhóm C, file cài đặt tạm:** chỉ xóa mục xác định được chủ, cũ hơn 7 ngày, không có trình cài nào đang chạy.
- 4 thư mục NSIS và 3 bản giải nén của AI Audio Studio: ứng dụng đã cài.
- 7 thư mục bộ cài / bản tải Autodesk. Autodesk hướng dẫn có thể xóa nội dung thư mục temp; file đang dùng sẽ không xóa được.
  Bản tải 22/10 được giữ vì có thể là bản cập nhật đang chờ.
- Thư mục `WinGet`.
- Gói cài cũ của Claude Desktop.

**Nhóm D, bản app cũ:**
- Giữ bản đang chạy 1.2.13 và bản rollback 1.2.11.
- Chỉ xóa bản giống hệt gói `dist` (zip đã kiểm SHA-256).
- 1.0.0-1.1.5 không có gói, nên giữ.

**Khi xóa:**
- Mỗi mục được **đổi tên trước**. Nếu có file đang mở, việc đổi tên thất bại và mục bị bỏ qua: không ép mở khóa. Lần này không
  mục nào bị bỏ qua.
- Sau đó xóa thẳng, **không qua thùng rác** (thùng rác vẫn chỉ có các mục từ 24/10).
- Trước khi xóa đã chạy thử:
  - 163/163 mục của kế hoạch ban đầu hợp lệ;
  - 61/61 mục còn lại của nhóm A hợp lệ, sau khi sửa script.

  4 thư mục NSIS bổ sung vào kế hoạch sau lần chạy thử đầu. Chúng đi qua cùng các kiểm tra lúc chạy thật: còn tồn tại, nằm
  trong vùng cho phép, đổi tên được.

### 2. Sự cố trong lúc chạy (đã xử lý)

Lần chạy nhóm A đầu tiên xóa xong 43 mục, rồi dừng ở `r7\a`, `r7\d`, `r7\L\Programs`.

- **Nguyên nhân:** đổi tên để kiểm tra "đang dùng" thêm 16 ký tự. Đường dẫn sâu nhất (253 ký tự) vượt giới hạn 260 ký tự của
  .NET trong PowerShell 5.1. Ba thư mục bị xóa dở dưới tên tạm.
- **Đã sửa script:**
  - tên tạm ngắn;
  - xóa bằng `rd /s /q` với tiền tố `\\?\`, hỗ trợ đường dẫn dài và vẫn dừng nếu có file đang mở;
  - đo bằng `robocopy`;
  - hoàn tất mục dở dang.
- Chạy thử, rồi chạy lại: **3 mục dở dang và 58 mục còn lại xóa xong; không còn thư mục tên tạm nào.**
- Ba mục đó là bản build tái tạo được từ `dist`, nên không có dữ liệu nào bị ảnh hưởng.

### 3. Xác nhận không thay đổi production

`evidence\protected-before.csv` / `protected-after.csv`:

| Kiểm tra | Kết quả |
|---|---|
| SHA-256 `storage.json` (`8D79DBDD…`), `current.txt`, `link.json`, `runtime.json` | **Không đổi** |
| Database `data\runtime\db\app.db` | Không bị đụng: không xóa gì trên D:, script từ chối mọi đường dẫn D:. File thay đổi vì app tự ghi trong các job do người dùng chạy |
| Model (`data\runtime\models`) | **Không mất model nào.** Có thêm `MV-20261026-105345-C73F` (2 file, 10:53:45) do lần huấn luyện người dùng bấm chạy 10:18 lưu ra, trước lần xóa đầu tiên (10:54:10). *Nhãn "16 files" trong `protected-before.csv` ghi sai: lúc 10:48 có 18 file* |
| Backup (68 file) / `dist` (62 file) | **Không đổi** (danh sách tên + kích thước) |
| Mã nguồn / Git | `git status` và HEAD `e682cf3` **không đổi**. Không commit, không push |
| App | 1.2.13, PID 11964, chạy suốt phiên (`/api/health` trước và sau mỗi nhóm) |
| Rollback | `rollback-version.ps1 -To 1.2.11 -CheckOnly`: runtime 1.2.11 chạy được, báo cần khôi phục backup trước migration v9 (schema 10 > 9). Trạng thái này **giống trước khi dọn** |
| Tiến trình, dịch vụ, Registry, page file, cấu hình ứng dụng | Không kill / dừng tiến trình; không đổi Registry, page file, dịch vụ hay cấu hình. Không cài / gỡ phần mềm, không deploy, không dùng quyền quản trị |
| `Green Christmas Tree` | Không đụng tới |

**Job của người dùng trong phiên:**
- D-1 chạy tay 09:58-10:01;
- huấn luyện chạy tay 10:18-10:53, kết quả `PROMOTION_REVIEW_REQUIRED`, không promote.

Việc xóa chỉ bắt đầu sau khi hai job này kết thúc.

### 4. Giới hạn và việc còn tồn tại

- **Chưa có backup chính thức nào kể từ 23/10 00:10.** Lần nạp lại toàn bộ (23/10 07:35) và 3 ngày D-1 sau đó chưa nằm trong
  backup nào. Đó là lý do giữ `bt`. Phát hiện này nằm ngoài phạm vi dọn dẹp; chưa làm gì.
- **`deploy-upgrade.ps1` vẫn không xóa thư mục giải nén**, nên mỗi lần deploy thêm khoảng 0,25 GB vào TEMP. Không sửa script
  theo yêu cầu.
- Không đọc nội dung file cá nhân. Vì vậy `Rar$EXa672.19942` (2,07 GiB, 07/2026) và 4,0 GiB ảnh `.jpg` rời trong TEMP không
  xác định được nguồn.
- Không gặp lỗi quyền. Mọi mục nằm trong hồ sơ người dùng, không cần quyền quản trị.

### 5. Quyết định cần chủ hệ thống

1. **Tạo backup chính thức mới.** Ví dụ `Backup.bat` của app; bước này ghi một file backup, nên cần bạn cho phép. Sau đó có thể
   xóa thêm `bt` (2,47 GiB).
2. **Xem `Rar$EXa672.19942`** (2,07 GiB). Nếu còn file nén gốc, có thể xóa.
3. **Các build không có gói** (1.0.0-1.1.5: 1,93 GiB; 1.1.7, 1.1.6 cũ và 3 build bị thay thế: 1,25 GiB): giữ hay bỏ.
4. **File rời trong TEMP** (5,6 GiB: `.tmp`, `.log`, `.jpg`): dọn bằng Storage Sense sau khi đóng ứng dụng, nếu muốn.
5. **Sửa `deploy-upgrade.ps1`** để tự xóa thư mục giải nén sau khi cài xong: một thay đổi mã riêng, cần duyệt.

### Tệp trong thư mục này

- `CLEANUP_MANIFEST.csv`: 167 mục đã xóa, gồm đường dẫn, dung lượng, phân loại, lý do, kết quả và nguồn khôi phục.
- `SKIPPED_FILES.csv`: 30 mục giữ lại và lý do.
- `BEFORE_AFTER.md`: dung lượng trước, sau và theo từng nhóm.
- `ROLLBACK_NOTES.md`: cách khôi phục.
- `evidence\`:
  - script: `script-verify-builds.ps1`, `script-build-plan.ps1`, `script-run-cleanup.ps1`;
  - kết quả đối chiếu build: `verify-builds.csv`, `rehearsal-builds.csv`;
  - độ phủ backup của bản sao DB: `dbcopy-coverage.csv`;
  - kế hoạch, kết quả chạy thử và chạy thật;
  - trạng thái được bảo vệ, trước và sau.

## 4. Khôi phục sau khi dọn (26/10/2026)

Nguồn: `reports\windows-disk-cleanup-20261026-095823\ROLLBACK_NOTES.md` (worktree MAIN).

**Các mục đã xóa vĩnh viễn**, không qua thùng rác. Đó là cố ý: chuyển vào thùng rác sẽ không giải phóng chỗ.

Tuy vậy, **mọi mục đã xóa đều có nguồn khôi phục hoặc không cần khôi phục.** Không có dữ liệu nào chỉ tồn tại ở nơi đã xóa:
- những bản sao duy nhất (`bt`, các build không còn gói, bản tạm WinRAR) đã được **giữ lại**;
- nguồn khôi phục của từng mục nằm ở cột `restore_from` trong `CLEANUP_MANIFEST.csv`.

Không cần khôi phục gì để app chạy:
- production 1.2.13 không bị đụng tới;
- bản rollback 1.2.11 còn nguyên, `rollback-version.ps1 -To 1.2.11 -CheckOnly` chạy được.

### Nhóm B: thư mục giải nén gói của `deploy-upgrade.ps1`

- **Không cần khôi phục.** Mỗi lần deploy, `install.ps1` đã chép nội dung sang
  `%LOCALAPPDATA%\Programs\DemandForecast\<phiên bản>` (`scripts\install.ps1:115-118`). Rollback chỉ dùng thư mục đó
  (`scripts\rollback-version.ps1:12-14`).
- **Nếu vẫn muốn tạo lại** (nội dung giống từng byte; gói đã được kiểm SHA-256):

  ```powershell
  $v = "1.2.13"
  Expand-Archive -LiteralPath "D:\Buymed\Lightgbm AI\dist\DemandForecast-$v-win64-portable.zip" -DestinationPath "$env:TEMP\DemandForecast-deploy-restore-$v"
  ```

### Nhóm D: 12 bản app cũ đã cài

Các bản đã xóa: 1.1.6, 1.1.8, 1.1.9, 1.2.0, 1.2.1, 1.2.2, 1.2.3, 1.2.4, 1.2.5, 1.2.6, 1.2.8, 1.2.10. Mỗi bản giống hệt
gói trong `dist`: cùng commit và fingerprint, hoặc cùng SHA-256 của từng file đối với 1.1.6 và 1.1.8.

**Khôi phục một bản mà không đổi phiên bản đang chạy.** **Không** chạy `install.ps1`, vì script đó đặt phiên bản này làm hiện
hành và chạy migration:

```powershell
$v = "1.2.10"
$zip = "D:\Buymed\Lightgbm AI\dist\DemandForecast-$v-win64-portable.zip"
(Get-FileHash $zip -Algorithm SHA256).Hash -eq ((Get-Content "$zip.sha256" -Raw).Trim() -split '\s+')[0].ToUpper()   # phải True
$tmp = Join-Path $env:TEMP "df-restore-$v"
Expand-Archive -LiteralPath $zip -DestinationPath $tmp
Copy-Item -Recurse (Join-Path $tmp "DemandForecast-$v") "$env:LOCALAPPDATA\Programs\DemandForecast\$v"
Remove-Item -LiteralPath $tmp -Recurse
```

**Rollback thật của production** vẫn theo quy trình cũ: `scripts\rollback-version.ps1 -To 1.2.11`, kèm khôi phục backup
`backup-20261023-001008-pre-migration-v9.zip` như `docs\03_van_hanh\VAN-HANH.md` mô tả. Lý do là database đang ở schema 10, còn 1.2.11 chỉ
hỗ trợ tới 9. Việc dọn dẹp không làm thay đổi điều này.

### Nhóm A: thư mục tạm Claude

**Bản sao database** (22 thư mục `db` / `backups` và 21 file `app.db*`):
- Đây là bản sao production tạo ra cho thử nghiệm và diễn tập.
- Với mỗi bản sao có một backup chính thức trong `D:\Buymed\Lightgbm AI\backups` mang **cùng trạng thái dữ liệu nhu cầu**:
  giữa lúc sao chép và lúc backup không có lần D-1 hay backfill thành công nào. Tên backup ở cột `restore_from` của
  `CLEANUP_MANIFEST.csv`.
- Cần trạng thái cũ thì giải nén backup đó vào **một thư mục cách ly** (LOCALAPPDATA riêng, `DF_DISABLE_SCHEDULER=1`). Không
  bao giờ ghi đè lên production.
- `models\` và file nhỏ (`copy.json`, script, log) của các bản sao **được giữ nguyên**, gồm cả các model chỉ có trong
  scratchpad: 8EB8, B675, 9170.

**Bản cài diễn tập** `r7`-`r14` (`a`, `d`, `L\Programs`): giống hệt gói `dist` của cùng phiên bản. Khôi phục bằng
`Expand-Archive` như nhóm B.

**Profile trình duyệt thử nghiệm** (37 thư mục): không cần khôi phục; lần chạy thử sau tự tạo lại. Ảnh chụp và
`e2e_results.json` nằm cạnh profile **được giữ**.

### Nhóm C: file cài đặt tạm

| Mục | Khôi phục |
|---|---|
| `ns*.tmp` ×4, `3K*` ×3 (AI Audio Studio) | Chạy lại bộ cài AI Audio Studio. App đã cài vẫn còn trong `%LOCALAPPDATA%\Programs\AI Audio Studio` |
| `odis_download_dest\…` ×4, `odis_installer_dest`, `Synthetic-Bundle-*` ×3, `{1E7D4EF7-…}` (Autodesk) | Autodesk Access tự tải lại khi cần cài hoặc cập nhật. Bản tải mới nhất (22/10) **được giữ** |
| `WinGet` | `winget` tự tải lại khi cài |
| `Claude-2598170254.msix` | Tải lại từ trang Claude Desktop hoặc Microsoft Store; Claude Desktop vẫn đang được cài |

### Không khôi phục được (nên đã giữ lại, không xóa)

- `bt`: bản sao database sau lần nạp lại toàn bộ 23/10. Không backup chính thức nào chứa trạng thái này.
- `DemandForecast-deploy-20261015-163950` (bản build 1.1.6 cũ, 24 file khác gói hiện có) và `…-20261015-231617` (1.1.7,
  không có gói).
- 3 thư mục build bị thay thế (1.2.4, 1.2.6 ×2).
- 1.0.0-1.1.5 (không có gói).
- `Rar$EXa672.19942`.

## 5. Demand Forecasting / LightGBM: phân tích bộ nhớ (25/10/2026)

Nguồn: `reports\windows-memory-audit-20261025-223332\DEMANDFORECAST_MEMORY_AUDIT.md` (worktree MAIN).

**Phạm vi:** chỉ đọc.
- Số liệu lấy từ bộ đo tài nguyên có sẵn trong app (`result_json.resources` của mỗi job, bản 1.2.13), từ log
  `logs\runtime\app.log`, từ hai bộ lấy mẫu bên ngoài trong lúc audit và từ đọc mã nguồn.
- Không chạy huấn luyện, backtest hay benchmark nào.
- Lần huấn luyện có trong báo cáo do **người dùng tự bấm chạy** lúc 22:22, trước khi audit bắt đầu. Audit chỉ quan sát.

Đơn vị: MB = 1.048.576 byte, GB = 1.024 MB. "Private" là bộ nhớ riêng đã commit; "resident" là phần đang nằm trong RAM.

### 1. Kết luận

1. **App không phải nguồn tiêu thụ nền chính.**
   - Lúc rảnh, tiến trình server giữ khoảng **550 MB private**, chỉ khoảng 50-200 MB resident. Đó là khoảng 2 % bộ nhớ đã
     commit của máy (27,3 GB).
   - Không có tiến trình worker con: LightGBM chạy bằng luồng bên trong tiến trình server.
2. **App là tác nhân đẩy máy vào thiếu RAM khi chạy job nặng:**
   - huấn luyện cần thêm **+1,9 đến +2,3 GB** private (đo 3 lần: +1.968 / +2.402 / +2.384 MB) trong 28-34 phút, dùng
     khoảng 6 lõi CPU. Lần 25/10 làm RAM trống của máy xuống **16,9 MB**;
   - lần nạp lại toàn bộ D-1 (23/10, khi bật Customer ID) cần thêm **+5,1 GB**;
   - D-1 thường cần +190 đến +315 MB, nhưng đọc **13,2-13,5 GB** từ database cho mỗi lần chạy.
3. **Thông báo "không đủ bộ nhớ" là bộ bảo vệ của app (1.2.13) chặn đúng như thiết kế, không phải lỗi `MemoryError`.**
   - Log không có `MemoryError`, `Unable to allocate`, `bad_alloc` hay lỗi 1455 (page file quá nhỏ).
   - Windows không ghi sự kiện cạn bộ nhớ ảo nào (Resource-Exhaustion-Detector 2004) kể từ 14/08.
   - Bộ bảo vệ chặn vì phần commit còn trống của máy (RAM + page file) nhỏ hơn mức đã đo × 1,25. Phần commit đó bị các
     ứng dụng khác chiếm.
4. **Không có bằng chứng rò rỉ bộ nhớ trong app.** Sau mỗi job, bộ nhớ quay về gần mức ban đầu (mục 7).

### 2. Phiên bản và tiến trình (22:35)

| Mục | Giá trị |
|---|---|
| Phiên bản | 1.2.13 (`current.txt` = 1.2.13, `/api/health` = 1.2.13) |
| Tiến trình | `python.exe` PID 11964, `%LOCALAPPDATA%\Programs\DemandForecast\1.2.13\python\python.exe`, chạy từ 24/10 23:36:47, nghe 127.0.0.1:8765 |
| Tiến trình con | chỉ `conhost.exe` (1,6 MB). Không có worker Python, không có job chạy ngoài tiến trình |
| Bộ nhớ lúc chụp (đang huấn luyện) | 2.515 MB private, 2.138 MB private resident, working set 2.150 MB |
| Database | `data\runtime\db\app.db` 2.633,6 MB (22/10: 848 MB; tăng chủ yếu do lần nạp lại toàn bộ 23/10 và nhật ký thay đổi) |
| Model | 16 file, 33,9 MB tổng (8 model × khoảng 5 MB). Không đáng kể |
| Job đang chạy lúc audit | `JOB-20261025152216-0D3D2E` TRAIN_PUBLISH (MANUAL) |

Tiến trình link công khai (supervisor + proxy) **không chạy** lúc audit. Xem `FINAL_REPORT.md`, mục "Phát hiện ngoài phạm
vi".

### 3. Bộ nhớ theo loại job, production thật (bộ đo của app, lấy mẫu 2 giây)

Giờ Việt Nam. "Tăng" = private đỉnh − private lúc bắt đầu. "RAM trống tối thiểu" và "commit trống tối thiểu" là của
**cả máy** trong lúc job chạy.

| Job | Thời điểm | Thời gian | Private đầu → đỉnh → cuối (MB) | Tăng | CPU (kernel) | Page fault | RAM trống tối thiểu | Commit trống tối thiểu |
|---|---|---|---|---|---|---|---|---|
| Huấn luyện + backtest | 23/10 12:56 | 1.665 s | 934 → 2.902 → 895 | **+1.968** | 9.714 s (2.954 s) | 17,3 triệu | **128 MB** | 2.777 MB |
| Huấn luyện + backtest | 24/10 16:04 | 1.957 s | 553 → 2.955 → 612 | **+2.402** | 10.666 s (2.592 s) | 18,4 triệu | 1.544 MB | 3.302 MB |
| Huấn luyện + backtest (audit quan sát) | 25/10 22:23 | 2.037 s | 594 → 2.978 → 626 | **+2.384** | 11.131 s (2.601 s) | 19,4 triệu | **16,9 MB** | 1.845 MB |
| D-1 nạp lại toàn bộ (Customer ID) | 23/10 07:09 | 1.542 s | 494 → 5.751 → 1.402 | **+5.258** | 1.117 s (396 s) | 3,6 triệu | **163 MB** | 2.399 MB |
| D-1 thường | 24/10 11:34 | 196 s | 497 → 812 → 567 | +315 | 125 s | 135 nghìn | 3.322 MB | 13.668 MB |
| D-1 thường (chạy tay) | 25/10 22:13 | 154 s | 584 → 771 → 593 | +188 | 117 s | 87 nghìn | 1.000 MB | 2.682 MB |
| D-1 thường (chạy tay) | 25/10 22:15 | 193 s | 550 → 780 → 585 | +229 | 138 s | 116 nghìn | 924 MB | 2.168 MB |
| D-0 (6 lần/ngày) | 23-25/10 | 3-17 s | không đổi | 0 đến +35 | ≤ 11 s | | 564-3.784 MB | 1.588-16.861 MB |
| Snapshot cuối ngày | 23/10, 24/10 | 6-8 s | | +5 | ≤ 6 s | | **517 MB** (23/10) | |
| Chốt actual | 23/10, 24/10 | 2-3 s | | 0 | | | | |

**Nhận xét:**
- **Phần kernel chiếm 23-30 % CPU của huấn luyện, với 17-19 triệu page fault.** Máy phải phân trang liên tục, nên mất
  thời gian cho việc chuyển trang thay vì tính toán.
- D-1 đọc 13.223-13.541 MB I/O mỗi lần, khoảng 5 lần kích thước database. Lượng đọc này thay toàn bộ cache file của
  Windows, nên các ứng dụng khác bị chậm theo.
  Báo cáo 22/10 đã ghi vấn đề này ("12,6 GB ReadFile, khoảng 15 lượt đọc DB") nhưng chưa xử lý.
- Private của server tăng lên **1.461 MB** sau khi khởi động lại và promote model lúc 24/10 23:37. Đến 08:57 sáng 25/10
  nó trở về **549 MB**: cache giải thích được trả lại sau 30 phút không dùng, đúng như thiết kế 1.2.13.

### 4. Lần huấn luyện 25/10 22:22 (quan sát trực tiếp)

Bộ lấy mẫu ngoài đọc mỗi 10-20 giây, có tiến trình 11964 và bộ đếm bộ nhớ của Windows.
Dữ liệu ở `evidence\ts-*.csv` và `evidence\ts2-*.csv`.

1. **22:22:16: bị hoãn với `INSUFFICIENT_MEMORY`.**
   - Commit còn trống **2.917 MB**, nhỏ hơn mức cần 2.402 MB × 1,25 = 3.002,5 MB.
   - RAM trống 1.212 MB.
   - App tự hẹn thử lại sau 60 giây (log `job deferred: not enough memory`).
2. **22:23:40: lần thử thứ 2 được chạy, kèm cảnh báo `PAGING_EXPECTED`.**
   - Commit còn trống 3.124 MB (vừa đủ ngưỡng), RAM trống 1.783 MB, nhỏ hơn 2.402 MB.
   - App biết trước là sẽ phải phân trang.
3. **Trong khi chạy (đường cong từ 22:34):**
   - private dao động **1,8-2,7 GB** theo từng fold: mỗi fold dựng ma trận rồi trả lại;
   - trung bình **6,3 lõi** (khoảng 49 % CPU của máy);
   - RAM trống của máy 1,5-2,8 GB, page file ghi ra có lúc 41.644 trang/giây (khoảng 163 MB/giây).
4. **Kết quả cuối (bộ đo của app):** SUCCEEDED lúc 22:57:37, sau 2.037 s (33,9 phút).
   - Private 594 → **2.978** → 626 MB (**+2.384 MB**, trung bình 2.305 MB); working set đỉnh 2.598 MB.
   - CPU 11.131 s (kernel 2.601 s = 23 %), trung bình 45,5 % của 12 luồng; **19,4 triệu page fault**; đọc 8,7 GB, ghi
     0,5 GB.
   - **RAM trống của cả máy xuống thấp nhất 16,9 MB**; commit trống thấp nhất 1.845 MB.
   - Page file tự nới trong lúc chạy (giới hạn commit 33.829 → 34.192 MB), rồi tự thu lại: 16.900 MB page file, giới hạn
     32.965 MB lúc 22:58. Giới hạn commit vì vậy thay đổi ngay trong một phiên làm việc, không chỉ khi khởi động lại.
   - Sau job, server về **629 MB private / 246 MB working set**, gần như bằng lúc bắt đầu (+32 MB).
   - Không có sự kiện Resource-Exhaustion nào trong lúc chạy.
   - Kết quả nghiệp vụ: `PROMOTION_REVIEW_REQUIRED`. Ứng viên được lưu, **không** tự promote; ngoài phạm vi audit.

### 5. Vì sao máy báo "không đủ bộ nhớ" dù RAM là 16 GB

Bộ bảo vệ (`backend/app/jobs/runner.py:126-157`) so **commit còn trống** (RAM + page file chưa cam kết) với mức tăng lớn
nhất đo được ở 10 lần chạy gần nhất × 1,25.

**Mức commit của máy:**
- giới hạn commit **33,0 GB**: RAM 15,7 GB + page file 17,3 GB;
- đã dùng **27,3 GB**: các tiến trình 23,7 GB, phần còn lại là kernel và vùng nhớ dùng chung.

Phần lớn commit này **không nằm trong RAM**. Ví dụ:
- trình duyệt: 6.015 MB commit nhưng 2.027 MB resident;
- WebView2: 2.664 MB nhưng 453 MB;
- QZ Tray (Java): 827 MB nhưng 105 MB;
- Power BI gateway: 424 MB nhưng 6 MB.

Vùng nhớ đã commit vẫn chiếm chỗ trong giới hạn commit, dù không dùng RAM.

**Page file do Windows tự quản lý** (`AutomaticManagedPagefile = True`). Nó chỉ lớn lên khi commit sắp chạm giới hạn, và
**trở về kích thước ban đầu sau mỗi lần khởi động lại**:
- trước lần khởi động 24/10 20:39, page file đã lớn tới mức commit còn trống **6-17 GB** (24/10 11:09-18:00; 22/10:
  giới hạn 52,6 GB);
- sau khi khởi động lại, commit còn trống chỉ **1,6-3,2 GB** trong cả ngày 25/10. Đó là các lần đo lúc 08:57, 10:00,
  12:00, 14:00, 16:00 và 22:13-22:18;
- vì vậy bộ bảo vệ sẽ hoãn huấn luyện ở **phần lớn các thời điểm trong ngày 25/10**, không riêng lúc 22:22.

**Bộ bảo vệ không tính phần page file Windows còn có thể nới thêm.** Ổ C: còn 30 GB trống. Vì vậy:
- nó **thận trọng hơn mức cần** để tránh lỗi hết bộ nhớ;
- nhưng nó **đúng về hiệu năng**: chạy khi RAM trống dưới 2 GB thì huấn luyện bị phân trang nặng (mục 3).

### 6. Cấu hình LightGBM, luồng và chạy đồng thời

Đọc từ `GET /api/settings` và mã nguồn. Không thay đổi gì.

| Mục | Giá trị | Ảnh hưởng bộ nhớ |
|---|---|---|
| `forecast_strategy` | DIRECT, `direct_origins` 12, bước 7 ngày, chân trời 30 ngày | Ma trận huấn luyện khoảng 5,2 triệu dòng × 36 cột float32, khoảng 0,7-0,75 GB mỗi lần fit |
| `num_boost_round` / `num_leaves` / `learning_rate` | 300 / 31 / 0,05; `force_row_wise`, `deterministic` | Bin hàng khoảng 0,2 GB; histogram nhỏ |
| `num_threads` | 0 = mọi luồng logic (12; i5-1335U có 2 lõi P và 8 lõi E) | Gần như **không** ảnh hưởng RAM (bộ đệm histogram mỗi luồng cỡ MB). Ảnh hưởng **CPU**: đo được khoảng 6 lõi bận suốt 30 phút, cạnh tranh với ứng dụng của người dùng |
| Backtest | 12 fold × (ứng viên + model đang dùng) + 1 fit cuối = 25 lần fit **tuần tự** | Đỉnh là của một fold, không cộng dồn; thời gian gấp đôi |
| `max_train_days` | 730 (cửa sổ thật từ 01/01/2026, khoảng 298 ngày) | Không giới hạn thêm |
| `feature_customer` | bật (36 feature, trước đây 34) | Ma trận lớn hơn khoảng 6 % |
| Chạy đồng thời | Không bao giờ hai job nặng cùng lúc; job quá giờ giữ khóa đến khi thật sự dừng (`runner.py:104-123`, `160-176`, `237-244`) | Không thể có hai lần huấn luyện cùng lúc. D-0, snapshot, chốt actual là job nhẹ, có thể chạy song song |
| Lịch | D-1 08:00 (fallback 08:10), **huấn luyện 08:20**, D-0 08:00-18:00 mỗi 2 giờ, snapshot 23:55, chốt 23:59 | Huấn luyện rơi vào **giờ làm việc**, khi trình duyệt, Excel, Teams đang mở |
| Thời gian chờ tối đa | 3.600 s | Huấn luyện hiện mất 1.665-2.037 s. Nếu phân trang nặng hơn, vẫn còn dư |

### 7. Vòng đời dữ liệu trong mã (đã đọc, không sửa)

| Bước | Vị trí | Hiện trạng | Còn có thể giảm? |
|---|---|---|---|
| Nạp dữ liệu | `backend/app/data/demand.py:156-174` | `pd.read_sql_query` từ SQLite: khoảng 1,36 triệu dòng × 13 cột, khung khoảng 296 MB, nhưng **đỉnh +1,13 GB** khi nạp (đo 22/10 trên bản sao). pandas tạo đối tượng Python cho từng dòng trước khi thành mảng | **Có:** nạp theo khối hoặc đọc thẳng vào mảng có kiểu. Cần chứng minh panel giống từng byte |
| Panel | `ml/features.py` | Khoảng 17 nghìn chuỗi × khoảng 298 ngày, khoảng 0,2 GB (số chuỗi đo 22/10: 17.134). NaN = ngày không biết (không đổi thành 0, đúng quy tắc) | Không nên đổi kiểu dữ liệu: NaN và float là ngữ nghĩa nghiệp vụ |
| Bỏ khung đã nạp | `ml/pipeline.py:467` (`del demand`) | Đã có từ 1.2.13 | - |
| Ma trận huấn luyện | `ml/features.py:356-371` | Ghi vào **một** mảng float32 cấp phát sẵn (không `np.vstack`), từ 1.2.13 | Chỉ giảm được nếu dựng `lgb.Dataset` theo khối (`lgb.Sequence`). Rủi ro: model khác đi do mẫu lấy để chia bin, phải kiểm chứng |
| Dataset LightGBM | `ml/model.py:72-76` | `free_raw_data=True` + `del X, y, w`: ma trận thô được trả sau khi chia bin | - |
| Backtest | `ml/model.py:318-391` | Mỗi fold dựng panel cắt và ma trận riêng rồi bỏ. Bảng điểm chi tiết chỉ giữ khi `collect=True` (production không dùng) | - |
| Cache giải thích / SHAP | `ml/explain.py`, `ml/shap_audit.py` | Panel cũ bị bỏ khi đổi phiên bản dữ liệu, trả lại sau 30 phút không dùng | Đã thấy hiệu quả: 1.461 → 549 MB |
| Xuất Excel | `data/excel_io.py` | Thu rác vòng ngay sau khi xuất | - |

### 8. Rò rỉ bộ nhớ: không có bằng chứng

- **Private lúc bắt đầu các job D-0** (mức nền của server) qua các ngày:
  - 23/10: 934-1.023 MB, sau lần nạp lại toàn bộ;
  - 24/10: 460-610 MB;
  - 25/10: 549-555 MB.

  Mức nền **không tăng dần**. Hai lần nó cao hơn đều có nguyên nhân đã biết: nạp lại toàn bộ (23/10) và khởi động lại +
  promote + mở giải thích (24/10 23:37). Cả hai lần đều tự trở về.
- **Chênh lệch private cuối − đầu của huấn luyện:** −39 MB (23/10), +59 MB (24/10).
- **Báo cáo 22/10** lặp ba lần trên bản sao: đối tượng Python còn sống 0,2 MB.
- **Giới hạn:** chỉ có 3 ngày số liệu job (bộ đo có từ 1.2.13). Không đủ để loại trừ rò rỉ rất chậm trong nhiều tuần.

### 9. Việc có thể làm cho Demand Forecasting

Chưa làm gì; tất cả cần phê duyệt. Chi tiết ở `REMEDIATION_PLAN.md`. Thứ tự đề xuất:

1. **Không sửa mã:**
   - chọn giờ huấn luyện khi máy ít ứng dụng mở (B-5);
   - đóng bớt ứng dụng nặng trước khi bấm huấn luyện (B-1).
2. **Page file cố định đủ lớn** (B-4), để bộ bảo vệ không hoãn job chỉ vì page file vừa bị thu nhỏ sau khi khởi động lại.
3. **Đo, chưa sửa** (A-1, trên bản sao DB): tách đỉnh bộ nhớ theo từng bước của huấn luyện, xem bước nào tạo đỉnh +2,4
   GB. Sau đó mới chọn sửa bước nạp dữ liệu (B-8) hay bước dựng Dataset (B-9).
4. **D-1 đọc 13,5 GB mỗi lần:** đo truy vấn trên bản sao trước (A-2). Sửa chỉ khi có số đo và được duyệt.
5. **`num_threads` 8-10** (B-7): giảm cạnh tranh CPU, không giảm RAM. Cần đo WAPE / bias / thời gian trên bản sao.

Không đề xuất:
- giảm `direct_origins`, `num_leaves` hay số fold để tiết kiệm RAM khi chưa đo độ chính xác;
- xóa model, database hay backup;
- đổi model production.

## 6. Bằng chứng audit bộ nhớ (25/10/2026)

Nguồn: `reports\windows-memory-audit-20261025-223332\EVIDENCE.md` (worktree MAIN).

### 1. Thời điểm và điều kiện

| Mục | Giá trị |
|---|---|
| Bắt đầu / kết thúc | 25/10/2026 22:33:32 / 23:25:30, lần đo cuối (UTC+7). Báo cáo viết xong ngay sau đó |
| Máy | LENOVO 21JLS0X200, Windows 11 Pro build 26200, khởi động 24/10 20:39:02 |
| Tài khoản | `log-pc\giau vo`, **không** phải Administrator, không tự nâng quyền |
| Hoạt động song song | Huấn luyện production `JOB-20261025152216-0D3D2E` (người dùng bấm 22:22); VS Code, Chrome, Brave, Excel, Teams, Zalo đang mở |
| Loại bằng chứng | Bộ đếm Windows và WMI (thật, chỉ đọc); số liệu job do app tự ghi (thật, production); đọc mã nguồn; API `GET` của app trên 127.0.0.1 (chỉ đọc) |

### 2. Lệnh đã chạy (tất cả chỉ đọc)

Script nằm trong `evidence\script-*.ps1`. Output trung gian được ghi vào thư mục scratchpad của phiên:
`C:\Users\Giau Vo\AppData\Local\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-ddf0-41a6-b294-d1210c881018\scratchpad\memaudit`.

| # | Lệnh / nguồn | Mục đích |
|---|---|---|
| 1 | `Get-CimInstance Win32_OperatingSystem / Win32_ComputerSystem / Win32_Processor / Win32_PhysicalMemory / Win32_PhysicalMemoryArray`, `whoami` | Phần cứng, RAM, quyền |
| 2 | `Get-Counter '\Memory\*'` (19 bộ đếm), `Win32_PageFileUsage`, `Win32_PageFileSetting`, `Get-MMAgent`, `Get-Process 'Memory Compression'`, `Win32_LogicalDisk`, `powercfg /getactivescheme`, `Get-PhysicalDisk`, `Get-Partition` | Tổng quan bộ nhớ, page file, ổ đĩa |
| 3 | `script-sampler.ps1`: `Get-Counter` + `Get-Process` mỗi 20 s × 31 lần (22:34:25-22:45:00) và mỗi 10 s × 240 lần (22:40:23-23:24:54); tổng 271 mẫu không trùng thời điểm | Chuỗi thời gian: tăng trưởng, CPU, đường cong của huấn luyện |
| 4 | `script-snapshot.ps1`: `Win32_Process` (chỉ ProcessId, ParentProcessId, Name, ExecutablePath, CreationDate, SessionId; **không đọc command line**), `Win32_PerfRawData_PerfProc_Process` (WorkingSetPrivate, PrivateBytes), `Get-Process`, `FileVersionInfo`, `Get-AuthenticodeSignature` (80 tiến trình lớn nhất) | Bảng tiến trình |
| 5 | `Get-NetTCPConnection -State Listen` cổng 8765-8767; `current.txt` | Tiến trình app và link |
| 6 | `Get-ScheduledTask`, `Get-ScheduledTaskInfo` (DemandForecastLink); đọc `link-status.json`, `link-supervisor.log`, `link-task.log`; `tailscale funnel status` | Trạng thái link (phát hiện ngoài phạm vi) |
| 7 | `Get-WinEvent`: System và Application 25/10 09:40-10:10; Resource-Exhaustion-Detector (toàn bộ log từ 14/08); Application Error / Hang từ 01/10; TaskScheduler Operational | Sự kiện thiếu bộ nhớ, crash |
| 8 | `GET http://127.0.0.1:8765/api/health`, `/api/system/paths`, `/api/jobs?limit=200`, `/api/jobs/{id}`, `/api/settings` | Phiên bản, đường dẫn, số liệu tài nguyên job, cấu hình model / lịch |
| 9 | Đọc `logs\runtime\app.log` (mở chia sẻ đọc / ghi, không khóa file): tìm `MemoryError`, `Unable to allocate`, `bad_alloc`, `1455`, `INSUFFICIENT_MEMORY`, `job resources` | Lỗi bộ nhớ trong app |
| 10 | `script-startup.ps1`: Run keys HKCU / HKLM / WOW6432Node + StartupApproved, thư mục Startup, `Win32_Service` (chỉ lấy file exe từ PathName), `Get-ScheduledTask` ngoài `\Microsoft\` (chỉ lấy Execute, không lấy tham số) | Khởi động, dịch vụ, tác vụ |
| 11 | Đọc registry `HKCU\Console\%%Startup`, `Get-AppxPackage Microsoft.WindowsTerminal` | Giả thuyết đóng cửa sổ console của link |
| 12 | Liệt kê metadata `data\runtime\models`, `data\runtime\db` | Kích thước model / database |
| 13 | `script-disk.ps1`: `robocopy <thư mục> <đích không tồn tại> /L /S /XJ /BYTES` (/L = chỉ liệt kê, không chép; /XJ = không đi theo junction). Đã kiểm tra trước trên thư mục nhỏ: đích không bị tạo, tổng byte khớp `Get-ChildItem` (199.265 byte) | Dung lượng ổ đĩa (chạy sau khi huấn luyện xong) |
| 14 | `Get-FileHash` 5 file cấu hình, giá trị StartupApproved\Run, trạng thái task / dịch vụ, `git status --porcelain`: trước và sau | Xác nhận không thay đổi |
| 15 | Đọc mã: `backend/app/jobs/runner.py`, `ml/model.py`, `ml/features.py`, `ml/pipeline.py`, `data/demand.py`, `settings_service.py`; báo cáo `reports/resource-audit-20261022/FINAL_REPORT.md` | Phân tích Demand Forecasting |

**Không chạy:**
- huấn luyện, backtest, benchmark, `data-check`, hay bất kỳ lệnh `POST` nào;
- không kill / restart / stop tiến trình, dịch vụ hay task;
- không xóa file, không sửa registry, page file hay cài đặt ứng dụng;
- không cài phần mềm, không dùng subagent.

### 3. Giới hạn quyền và dữ liệu

| Khu vực | Kết quả |
|---|---|
| `Get-MMAgent` (nén bộ nhớ, prefetch) | **Access is denied** (cần quyền quản trị). Chỉ thấy tiến trình *Memory Compression*: 83-121 MB working set |
| Command line của tiến trình | Không đọc, theo chủ ý: có thể chứa token. Vai trò suy ra từ đường dẫn exe, tiến trình cha và cổng |
| Đường dẫn / chữ ký của tiến trình hệ thống được bảo vệ | Một số không đọc được (cột `path` trống trong `PROCESS_INVENTORY.csv`) |
| `C:\Windows\Temp` | 0 file đọc được (cần quyền quản trị) |
| `C:\ProgramData\Microsoft\Windows\WER` | 455 thư mục bị từ chối; đọc được 50 file (2 MB) |
| Đường dẫn exe | 181/393 tiến trình không trả đường dẫn cho tài khoản thường (phần lớn là dịch vụ ở session 0) |
| Log Security | Không đọc (cần quyền quản trị, không cần cho audit này) |
| Bộ nhớ theo tab trình duyệt | Không có từ bên ngoài. Cần Task Manager của chính trình duyệt (Shift+Esc) |
| Nội dung workbook Excel / file cá nhân | Không mở, theo yêu cầu |
| Lịch sử bộ nhớ dài hạn | Chỉ có khoảng 50 phút lấy mẫu ngoài + số liệu job của app 22-25/10. Windows không lưu lịch sử bộ nhớ theo tiến trình |

### 4. Bằng chứng chính

| Kết luận | Bằng chứng |
|---|---|
| Commit 27,3 / 33,0 GB, RAM khả dụng 1.496 MB | Bộ đếm 22:34; `evidence\ts-system-*.csv` |
| Huấn luyện bị hoãn 22:22 | `app.log` 2026-10-25T15:22:16Z: `job deferred: not enough memory`, `commit_avail_mb 2917.1`, `need_mb 2402.0`, `margin 1.25`, `phys_avail_mb 1211.9`. Chạy 15:23:40Z với `PAGING_EXPECTED` (`commit_avail_mb 3123.8`) |
| Commit trống 1,6-3,2 GB cả ngày 25/10; 6-17 GB trước khi khởi động lại | `evidence\job-resources-22-25oct.csv`, cột `commit_min` |
| RAM trống 128 MB / 163 MB khi huấn luyện / nạp lại toàn bộ (23/10) | Như trên, cột `phys_min` |
| Kernel chiếm 24-30 % CPU khi huấn luyện; 17-18 triệu page fault | Như trên, cột `kern_s`, `cpu_s`, `faults` |
| Nhóm tiêu thụ | `PROCESS_INVENTORY.csv` (cột `group`), `evidence\proc-snapshot-223504.csv` |
| Không có tiến trình tăng bất thường | `evidence\ts-proc-*.csv`, `evidence\ts2-proc-*.csv`: so sánh đầu / cuối từng PID |
| Không cạn bộ nhớ ảo | 0 sự kiện Resource-Exhaustion-Detector trong log System (lưu từ 14/08/2026) |
| Không có lỗi cấp phát trong app | `app.log`: 0 dòng `MemoryError` / `Unable to allocate` / `bad_alloc` / `1455` |
| Link dừng 09:57 | `link-status.json` sửa lần cuối 09:57:38; log supervisor dừng 08:58:37; `LastTaskResult 3221225786` (0xC000013A); không có listener 8766; Funnel vẫn trỏ 8766 |

### 5. Tệp bằng chứng (`evidence\`)

| Tệp | Nội dung |
|---|---|
| `ts-system-223425-224500.csv`, `ts-proc-223425-224500.csv` | Bộ lấy mẫu 1: bộ đếm máy và từng tiến trình mỗi 20 s |
| `ts2-system-224015-232454.csv`, `ts2-proc-224015-232454.csv` | Bộ lấy mẫu 2: mỗi 10 s, gồm cả lúc huấn luyện và sau huấn luyện |
| `proc-snapshot-223504.csv`, `signatures-top80.csv` | Ảnh chụp tiến trình (không có command line), chữ ký số |
| `job-resources-22-25oct.csv` | Số liệu tài nguyên của 32 job do app ghi (23-25/10) |
| `startup-services-tasks-raw.csv`, `startup-services-tasks-raw-after.csv` | Khởi động / dịch vụ / tác vụ, trước và sau |
| `hashes-before.csv`, `hashes-after.csv`, `after-checks.txt` | Xác nhận không thay đổi |
| `bits-starttype-events-20261025.txt` | Sự kiện 7040: SYSTEM đổi kiểu khởi động của BITS |
| `disk-level1-raw.csv`, `disk-level2-raw.csv` | Kích thước thư mục (chưa phân loại) |
| `script-*.ps1` | Mọi script đã chạy (chỉ đọc) |

**Lần huấn luyện quan sát được** (`JOB-20261025152216-0D3D2E`, số liệu của app):
- 2.037 s; private 594 → 2.978 → 626 MB; CPU user 8.529 s, kernel 2.601 s; 19.443.842 page fault;
- RAM trống thấp nhất 16,9 MB, commit trống thấp nhất 1.845,2 MB; giới hạn commit 34.192 MB lúc chạy;
- kết quả `SUCCEEDED` / `PROMOTION_REVIEW_REQUIRED` lúc 22:57:37.

## 7. Audit bộ nhớ Windows: toàn máy + Demand Forecasting (25/10/2026)

Nguồn: `reports\windows-memory-audit-20261025-223332\FINAL_REPORT.md` (worktree MAIN).

### Kết quả nhanh

| Mục | Kết quả |
|---|---|
| **Trạng thái** | **PASS.** Giai đoạn audit chỉ đọc đạt đủ các điều kiện ở mục 8 của yêu cầu. Các giới hạn quyền nằm ở dòng cuối bảng. Chưa thực hiện biện pháp nào |
| RAM | 16 GB vật lý: 2 × 8 GB DDR4-3200, 2/2 khe đã dùng, máy hỗ trợ tối đa 64 GB. Windows dùng được 15,7 GB |
| RAM khả dụng lúc đo | **1.496 MB** lúc 22:34. Trong 22:34-23:25 (271 mẫu): **1.466-2.811 MB** khi huấn luyện chạy, 2.752-4.149 MB sau khi huấn luyện xong |
| Commit | **27,3 / 33,0 GB (82,6 %)**. Page file `C:\pagefile.sys` do Windows tự quản lý: 17,3 GB, đang dùng 3,1 GB |
| Áp lực bộ nhớ | **Cao.** Free + zero list chỉ 7,6 MB; phân trang ra có lúc 41.644 trang/giây (khoảng 163 MB/giây). Trong lần huấn luyện 22:23-22:57, RAM trống của máy xuống **16,9 MB**; 23 % CPU của job nằm ở kernel do 19,4 triệu page fault |
| Ba nhóm tiêu thụ lớn nhất (đã xác minh) | 1. **Trình duyệt + WebView2**: 8,5 GB commit, 2,4 GB trong RAM (Chrome 38 tiến trình, Brave 12, Edge 7, WebView2 của Teams / Outlook / TeamViewer / Widgets / Search 31). 2. **Công cụ lập trình** (VS Code 15 tiến trình, Claude Code, Copilot, terminal): 3,5 GB commit, 1,3 GB trong RAM. 3. **Excel** (1 tiến trình, mở 25,8 giờ): 2,4 GB commit, 1,2 GB trong RAM |
| Demand Forecasting có phải nguyên nhân chính? | **Không phải nguyên nhân nền, nhưng là tác nhân kích hoạt.** Lúc rảnh app chỉ giữ khoảng 550-630 MB commit (khoảng 2 %). Khi huấn luyện, app cần thêm +1,9 đến +2,3 GB (đỉnh khoảng 2,9 GB private, đo 3 lần) trong 28-34 phút, và lần nạp lại toàn bộ D-1 cần thêm +5,1 GB. Máy chỉ còn 1,6-3,2 GB commit trống vì các ứng dụng khác, nên bộ bảo vệ của app hoãn huấn luyện (`INSUFFICIENT_MEMORY` lúc 22:22 hôm nay). Khi chạy được thì phân trang nặng |
| Giải pháp giảm RAM nhiều nhất | (1) **Nâng RAM lên 32 GB**: lớn nhất, tốn chi phí. (2) **Đóng bớt Excel / tab trình duyệt / Teams trước giờ huấn luyện**, hoặc dời giờ huấn luyện khỏi 08:20: ước tính +3-6 GB commit, +1,5-3 GB RAM, không tốn gì. (3) **Page file cố định trên D:**: hết hoãn job do page file thu nhỏ sau khởi động lại, nhưng không thêm RAM. (4) **Memory Saver** cho Chrome/Brave, tắt Edge tự chạy |
| Chưa xác minh được | Trạng thái nén bộ nhớ (`Get-MMAgent`: Access denied, cần quyền quản trị). Rò rỉ chậm trong nhiều ngày (chỉ có 50 phút lấy mẫu và 3 ngày số liệu job). Bộ nhớ theo từng tab trình duyệt. Tiến trình nào chiếm commit đúng lúc 22:22 (chỉ có tổng của app). `C:\Windows\Temp` và WER của máy (455 thư mục) không đọc được. 181/393 tiến trình (phần lớn là dịch vụ hệ thống) không cho đọc đường dẫn |

Không có thay đổi nào trên máy (mục 7). Kế hoạch chi tiết: `REMEDIATION_PLAN.md`. Phân tích riêng app:
`DEMANDFORECAST_MEMORY_AUDIT.md`.

### 1. Bối cảnh lúc đo

- **Đo lúc 25/10 22:33-23:25** (giờ Việt Nam). Máy khởi động lúc 24/10 20:39 (đã chạy khoảng 26 giờ), tài khoản
  `log-pc\giau vo`, **không** có quyền quản trị. Không phiên Windows nào khác đang chạy tiến trình.
- **Một lần huấn luyện production đang chạy** (`JOB-20261025152216-0D3D2E`). Người dùng bấm chạy lúc 22:22, sau hai lần D-1
  chạy tay lúc 22:13 và 22:15.
  - Lần thử 1 bị hoãn vì thiếu bộ nhớ; lần thử 2 chạy từ 22:23:40.
  - Audit không can thiệp, chỉ quan sát. Phần quét ổ đĩa (đọc nhiều file) được dời tới khi huấn luyện xong, để không tranh
    I/O.
- CPU: Intel Core i5-1335U, 10 lõi (2 P + 8 E), 12 luồng. Power plan Balanced.
- Ổ đĩa: một SSD NVMe 512 GB, chia C: 375 GB (còn 30,1 GB) và D: 100 GB (còn 71,1 GB).

### 2. Tổng quan bộ nhớ

| Chỉ số (22:34, bộ đếm Windows) | Giá trị | Ý nghĩa |
|---|---|---|
| Available | 1.496 MB | RAM Windows có thể cấp ngay: standby + free |
| Standby (normal / reserve / core) | 1.469 / 2 / 91 MB | Cache file, tái sử dụng được. **Không** phải RAM bị chiếm |
| Free + zero | 7,6 MB | Gần như không còn trang trống |
| Modified | 970 MB | Trang chờ ghi ra page file |
| Committed / Commit limit | 27,3 / 33,0 GB | Bộ nhớ đã cam kết, **không** đồng nghĩa với RAM đang dùng |
| Page file | 17.764 MB cấp phát, 3.154 MB đang dùng, đỉnh 4.605 MB từ lúc khởi động | Tự quản lý; nhỏ lại sau mỗi lần khởi động |
| Pool paged / nonpaged | 644 / 636 MB | Kernel |
| Pages/sec, page reads/sec | 385 / 46 lúc chụp; trung bình 1.829 / 19 trong 10 phút | Phân trang chủ yếu là ghi ra (pages output) khi huấn luyện cấp phát |
| CPU tổng | trung bình 72 %, tối đa 88 % (22:34-22:45) | Huấn luyện dùng khoảng 49 % máy |

**Cách đọc bộ nhớ theo tiến trình** (`PROCESS_INVENTORY.csv`, 393 tiến trình lúc 22:35):
- **private bytes**: bộ nhớ riêng đã commit, tổng 23,7 GB;
- **private working set**: phần riêng đang nằm trong RAM, tổng 8,6 GB;
- **working set**: gồm cả trang dùng chung, tổng 14,2 GB, **đếm trùng**.

Ba con số này **không cộng với nhau**.

#### Tiêu thụ theo nhóm (22:35)

| Nhóm | Tiến trình | Commit (private bytes) | Trong RAM (private WS) | CPU 22:34-22:45 |
|---|---|---|---|---|
| Trình duyệt: Chrome 38, Brave 12, Edge 7 | 57 | **6.015 MB** | 2.027 MB | 0,3 % |
| Công cụ lập trình: VS Code, Claude Code, Copilot, terminal | 37 | 3.563 MB | 1.310 MB | 3,4 % |
| WebView2: Teams 1.159, Outlook mới 659, TeamViewer 317, Widgets 287, Search 242 | 31 | 2.664 MB | 453 MB | 0,5 % |
| **Demand Forecasting** (đang huấn luyện) | 1 | 2.515 MB | **2.138 MB** | **49 %** |
| Office: Excel 2.423, Outlook 18 | 2 | 2.440 MB | 1.212 MB | 0 % |
| Windows / hệ thống (svchost 95 tiến trình, explorer, dwm, …) | 152 | 2.258 MB | 570 MB | 0 % |
| Liên lạc: Zalo 7, Teams 2 | 9 | 1.205 MB | 379 MB | 0,4 % |
| Ứng dụng nền: BlueStacks, Autodesk, Adobe, OneDrive, … | 22 | 910 MB | 121 MB | 0,5 % |
| In ấn: QZ Tray, Java | 1 | 827 MB | 105 MB | 0,1 % |
| Defender | 5 | 484 MB | 216 MB | 0 % |
| Power BI gateway | 1 | 424 MB | 6 MB | 0 % |
| Tailscale / hỗ trợ từ xa / PostgreSQL | 12 | 327 MB | 37 MB | 0 % |
| Khác | 62 | 589 MB | 61 MB | 0,2 % |

**Mười tiến trình đơn lẻ lớn nhất theo commit:**
1. python 11964 (Demand Forecasting): 2.515 MB;
2. Excel: 2.423 MB;
3. WebView2 của Teams: 869 MB;
4. QZ Tray: 827 MB;
5. Brave: 621 MB;
6. Claude Code: 545 MB;
7. VS Code: 492 MB;
8. Chrome: 491 MB;
9. Chrome: 467 MB;
10. Defender: 447 MB.

### 3. Nguyên nhân thiếu RAM, theo mức ưu tiên

#### Đã xác minh (có số đo)

1. **Ứng dụng người dùng chiếm phần lớn bộ nhớ trước khi app chạy job.** Trình duyệt + WebView2 + Excel + công cụ lập trình
   + Zalo / Teams chiếm khoảng **15,5 GB commit / 5,3 GB RAM**. Máy còn 1,5-2,8 GB RAM trống và 1,6-3,2 GB commit trống trong cả
   ngày 25/10 (số đo của app lúc 08:57-22:18).
2. **Huấn luyện của Demand Forecasting cần thêm +1,9 đến +2,3 GB trong 28-34 phút** (3 lần đo: +1.968 / +2.402 / +2.384
   MB), và D-1 nạp lại toàn bộ cần thêm +5,1 GB.
   - Khi máy đã đầy, Windows phải đẩy trang của chính job và của ứng dụng khác ra page file: 17-19 triệu page fault, 23-30 %
     CPU nằm ở kernel.
   - RAM trống thấp nhất đo được:
     - **16,9 MB**: huấn luyện 25/10, quan sát trong audit;
     - **128 MB**: huấn luyện 23/10;
     - **163 MB**: nạp lại toàn bộ 23/10;
     - **517 MB**: snapshot 23/10.
3. **Giới hạn commit co lại sau mỗi lần khởi động lại** vì page file do Windows tự quản lý.
   - Trước lần khởi động 24/10 20:39: commit trống **6-17 GB**.
   - Sau khi khởi động: commit trống **1,6-3,2 GB**.
   - Page file còn tự co giãn ngay trong phiên: 17.764 MB lúc 22:34, lớn hơn trong lúc huấn luyện, còn 16.900 MB lúc
     22:58.
   - Bộ bảo vệ của app (cần 3.002,5 MB) vì vậy hoãn huấn luyện ở phần lớn các thời điểm trong ngày 25/10. Lần 22:22 là một
     ví dụ (2.917 MB < 3.002,5 MB).
4. **Huấn luyện chạy lúc 08:20, giữa giờ làm việc**, cùng lúc trình duyệt và Excel mở. Huấn luyện dùng khoảng 6 trong 12
   luồng CPU suốt gần 30 phút.

#### Giả thuyết (chưa đủ bằng chứng)

- **Excel**, mở 25,8 giờ, giữ 2,4 GB commit. Có thể do workbook lớn (nội dung không được mở xem) hoặc tích tụ theo thời gian.
  Chỉ có số đo 50 phút, trong đó không tăng.
- **WebView2 của Teams** (869 MB, CPU 3.000 s). Cũng không tăng trong lúc đo.
- **D-1 đọc 13,2-13,5 GB mỗi lần** từ database 2,6 GB. Có thể đẩy cache của ứng dụng khác ra khỏi RAM và làm máy chậm sau
  mỗi lần D-1. Chưa đo tác động lên ứng dụng khác.
- **Không có tiến trình nào tăng bộ nhớ bất thường trong thời gian lấy mẫu.**
  - Trong 50 phút (271 mẫu, 22:34-23:25) chỉ 1 tiến trình tăng ≥ 20 MB private: VS Code PID 7796, +80 MB.
  - Sau huấn luyện, server Demand Forecasting về 627-629 MB và giữ nguyên.
  - Như yêu cầu, không kết luận rò rỉ khi chỉ dựa vào một thời điểm.

#### Đã loại trừ

| Giả thuyết | Kết quả |
|---|---|
| Hết bộ nhớ ảo, lỗi page file 1455 | Không có sự kiện Resource-Exhaustion 2004 từ 14/08. Log app không có `MemoryError` / 1455 |
| Hai job nặng chạy chồng nhau | 1.2.13 chặn trong mã, và log không ghi trường hợp nào |
| Dịch vụ Windows ăn RAM | 95 svchost tổng 219 MB trong RAM |
| PostgreSQL, WSL, máy ảo | PostgreSQL 22 MB; không có `vmmem` (không máy ảo nào chạy) |
| Tiến trình python 4,19 GB của tài khoản khác (ghi nhận 22/10) | Không còn sau khi khởi động lại 24/10 |
| Model / artifacts chiếm RAM | 8 model × 5 MB, chỉ nạp khi dùng |

### 4. Demand Forecasting (tóm tắt)

Chi tiết: `DEMANDFORECAST_MEMORY_AUDIT.md`.

- **Tiến trình và phiên bản:** 1.2.13, PID 11964, một tiến trình, không có worker con. Mức nền khoảng 550 MB commit.
- **Tối ưu đã có (1.2.13):**
  - không chạy hai job nặng cùng lúc;
  - bộ bảo vệ bộ nhớ đo trước khi chạy;
  - bỏ khung dữ liệu sớm, ma trận cấp phát sẵn, `free_raw_data`;
  - cache giải thích tự trả sau 30 phút.
- **Còn lại:**
  - đỉnh khi nạp dữ liệu (+1,13 GB cho khung 296 MB, do `pd.read_sql_query`);
  - D-1 đọc 13,5 GB mỗi lần;
  - huấn luyện chạy trong tiến trình web;
  - giờ huấn luyện 08:20;
  - `num_threads` = 12 luồng (ảnh hưởng CPU, không ảnh hưởng RAM).
- **Lần huấn luyện quan sát được hôm nay** (`JOB-20261025152216-0D3D2E`):
  - 22:22:16 bị hoãn `INSUFFICIENT_MEMORY`; chạy từ 22:23:40 với cảnh báo `PAGING_EXPECTED`;
  - SUCCEEDED lúc 22:57:37, sau 2.037 s;
  - private 594 → 2.978 → 626 MB; 6 lõi CPU; 19,4 triệu page fault; RAM trống của máy thấp nhất 16,9 MB;
  - sau job server về 629 MB private;
  - kết quả `PROMOTION_REVIEW_REQUIRED`: ứng viên được lưu, không promote.

### 5. Ổ đĩa (tách riêng, không phải RAM)

Đo bằng `robocopy /L` (chỉ liệt kê, không đọc nội dung, không chép), sau khi huấn luyện xong. Chi tiết: `DISK_USAGE.csv`
(160 dòng có phân loại).

**C: còn 30,1 / 375 GB. D: còn 71,1 / 100 GB.**

| Nhóm | Dung lượng | Ghi chú |
|---|---|---|
| TEMP người dùng | **63,0 GB** | Gồm scratchpad Claude của dự án 34,6 GB; `DemandForecast-deploy-*` 9,5 GB (38 thư mục, script deploy không dọn); file cài / tải tạm khoảng 10,5 GB; ảnh `.jpg` rời 4,0 GB |
| Dữ liệu Zalo | 25,0 GB | Cá nhân, giữ |
| `LocalAppData\Microsoft` | 24,3 GB | Outlook .ost 8,7; Edge 3,9; Outlook mới 3,1; Power BI Desktop 2,2; Office 2,0; OneDrive 1,6; gateway 1,5 |
| Page file / hiberfil | 16,5 / 6,3 GB | Hệ thống |
| Chương trình cài cho người dùng | 12,5 GB | 23 bản Demand Forecasting **5,8 GB**; FreeCAD 2,1; Zalo 1,75 |
| Hồ sơ + cache trình duyệt | Chrome 8,5 / Brave 4,0 / Edge 3,9 GB | Chỉ dọn cache từ trong trình duyệt |
| Cache khác | CapCut 4,5; huggingface 4,25; uv 2,3; npm 1,2; playwright 0,7; pip 0,4 GB | Tái tạo được |
| Dự án (D:) | backups 3,29 GB (68 file); database 2,57 GB; dist 1,77 GB; checkpoints 0,45; reports 0,44; .venv 0,42 GB | Dữ liệu và bản phát hành: không dọn ngoài quy trình |
| Model | 33,9 MB (16 file) | Không đáng kể |

**Ứng viên dọn** (nhóm B, chưa xóa gì): tổng khoảng **65 GB trên C:**. Lớn nhất:
- scratchpad Claude 34,6 GB;
- thư mục deploy 9,5 GB;
- TEMP của trình cài khoảng 10,5 GB;
- 21 bản app cũ khoảng 5,5 GB;
- cache gói 4,6 GB.

Xem `REMEDIATION_PLAN.md` mục 3. Ổ C: trống nhiều hơn còn giúp page file tự quản lý có chỗ nới.

### 6. Phát hiện ngoài phạm vi (chỉ ghi nhận, không xử lý)

**Link công khai Demand Forecasting đang KHÔNG hoạt động từ khoảng 09:57 sáng 25/10.**
- Task `DemandForecastLink` ở trạng thái *Ready* với kết quả cuối `0xC000013A`: cửa sổ console bị đóng hoặc nhận Ctrl+C.
  Supervisor và proxy cùng dừng. Task Scheduler không tự chạy lại.
- Tailscale Funnel vẫn bật và trỏ tới `127.0.0.1:8766`, nơi không còn gì lắng nghe. Người xem nhận trang lỗi; **không lộ dữ
  liệu**.
- **Giả thuyết (chưa xác minh):** máy dùng Windows Terminal làm console mặc định (không có cấu hình delegation, Windows
  Terminal đã cài). PowerShell "ẩn" do Task Scheduler mở có thể hiện thành cửa sổ, và cửa sổ đó đã bị đóng.
- **Audit này không khởi động lại** (yêu cầu cấm restart tiến trình và đổi cấu hình Tailscale). Cách bật lại: Start Menu
  → *Demand Forecasting Link* → *Link xem tu xa - bat lai*, hoặc phê duyệt để tôi chạy `remote-access.ps1 start`. Sửa tận gốc (chạy
  wrapper không có cửa sổ console, thêm trigger định kỳ) là một thay đổi riêng, cần duyệt.

Mục khởi động **Green Christmas Tree** hiện đang **disabled** trong StartupApproved, khác với ngày 24/10. Audit này không
thay đổi gì ở mục đó (giá trị được ghi lại trước và sau, mục 7).

### 7. Xác nhận không thay đổi hệ thống

So sánh trước / sau (`evidence\after-checks.txt`, `hashes-*.csv`):

| Kiểm tra | Kết quả |
|---|---|
| SHA-256 của `storage.json` (`8D79DBDD…`), `current.txt`, `link.json`, `security-ack.json`, `runtime.json` | **Không đổi** |
| `StartupApproved\Run` (10 giá trị, gồm Green Christmas Tree) | **Không đổi** |
| 351 mục khởi động / dịch vụ / tác vụ | Audit không thay đổi gì. **Một khác biệt:** dịch vụ BITS đổi Auto ↔ Manual. Thay đổi này do **NT AUTHORITY\SYSTEM** (Windows Update) làm nhiều lần trong ngày: sự kiện 7040 lúc 15:01, 16:02, 16:54, 21:23, 22:14, 22:35, 22:55, 22:58, 23:00 (`evidence\bits-starttype-events-20261025.txt`). Tài khoản audit không có quyền đổi dịch vụ. Ngoài ra 5 dịch vụ tự bật / tắt theo trigger, kiểu khởi động không đổi |
| Task `DemandForecastLink` | Không đổi: Ready, `0xC000013A`, lần chạy cuối 01:33:45 |
| Tiến trình | 376/393 tiến trình của ảnh chụp 22:35 vẫn sống. 17 tiến trình đã kết thúc đều sống dưới 0,2 giờ: PowerShell / cmd / conhost của chính audit, WMI, Search, svchost tạm. Không có lệnh kill / restart / stop nào |
| Git | `git status` giống lúc bắt đầu (9 sửa + 4 mới từ việc trước, chưa commit). `reports\` nằm ngoài Git |
| File | Chỉ tạo thư mục báo cáo này và thư mục tạm `scratchpad\memaudit`. Không xóa file nào. Đích "list-only" của robocopy không được tạo |
| Database / model / lịch / cấu hình app | Không đọc trực tiếp database (chỉ API `GET` và metadata file). Không gọi `POST`. Database chỉ thay đổi do job huấn luyện mà người dùng tự chạy |

### 8. Quyết định cần phê duyệt

Chưa làm gì cho tới khi có phê duyệt. Mã ở cột 1 khớp `REMEDIATION_PLAN.md`.

| # | Quyết định | Ai làm |
|---|---|---|
| 1 | **Link công khai đang tắt:** bật lại ngay (Start Menu → *Demand Forecasting Link* → *Link xem tu xa - bat lai*, hoặc cho phép tôi chạy `remote-access.ps1 start`)? Có sửa để wrapper không phụ thuộc cửa sổ console không? | Chủ hệ thống / tôi khi được phép |
| 2 | **B-1 / B-5:** đóng ứng dụng nặng trước khi huấn luyện, và / hoặc đổi giờ huấn luyện khỏi 08:20 (chọn giờ) | Chủ hệ thống |
| 3 | **B-4:** thêm page file cố định trên D: (16 GB ban đầu / 32 GB tối đa) | IT hoặc tài khoản quản trị (Giau Vo không có quyền) |
| 4 | **B-11:** nâng RAM lên 32 GB (2 × 16 GB DDR4-3200 SO-DIMM) | Chủ hệ thống (mua) + kỹ thuật |
| 5 | **B-2 / B-3:** bật Memory Saver; tắt Edge tự chạy; chọn ứng dụng khởi động được tắt (BlueStacks, Autodesk, Adobe CCX, Logitech; Power BI gateway và QZ Tray chỉ khi không dùng) | Chủ hệ thống |
| 6 | **A-1 / A-2:** cho phép đo trên bản sao DB vào giờ máy rảnh: một lần huấn luyện khoảng 35 phút, khoảng 3 GB, và đo truy vấn D-1 | Tôi, khi được phép |
| 7 | **Sửa mã sau khi có số đo** (B-8, B-9, B-10, B-6) và **dọn thư mục tạm của `deploy-upgrade.ps1`**. Mỗi mục cần phát hành; triển khai là quyết định riêng (nhóm C) | Chủ hệ thống duyệt |
| 8 | **B-7 (tùy chọn):** thử `num_threads` 8-10, đo WAPE / bias / thời gian | Chủ hệ thống duyệt |
| 9 | **Dọn ổ đĩa D-1 … D-7:** chọn mục. D-1 (34,6 GB scratchpad) cần chủ hệ thống tự chạy script dọn đã xác minh | Chủ hệ thống |

**Ngoài phạm vi:** ứng viên của lần huấn luyện 22:23 (`PROMOTION_REVIEW_REQUIRED`) chờ xem xét promote như thường lệ.
Audit không đánh giá chất lượng của nó.

## 8. Kế hoạch tối ưu bộ nhớ (đề xuất, CHƯA thực hiện gì)

Nguồn: `reports\windows-memory-audit-20261025-223332\REMEDIATION_PLAN.md` (worktree MAIN).

**Nhóm:** A = an toàn, ít rủi ro; B = cần phê duyệt; C = rủi ro cao, không tự thực hiện.

Số liệu "đo được" lấy từ audit 25/10 22:33-23:xx (xem `EVIDENCE.md`). "Ước tính" là suy ra từ số đo, chưa thử.

**Hai giới hạn khác nhau cần tách bạch:**
- **RAM vật lý** (16 GB, còn 1,5-2,8 GB): thiếu thì Windows phân trang, máy và job chậm.
- **Commit** (RAM + page file = 33,0 GB, đã dùng 27,3 GB): thiếu thì app hoãn job nặng (`INSUFFICIENT_MEMORY`). Khi
  vượt hẳn giới hạn, chương trình bị lỗi cấp phát.

Đóng ứng dụng giúp cả hai. Page file chỉ giúp phần commit. Thêm RAM giúp cả hai.

### 1. Bảng xếp hạng

Thứ tự theo hiệu quả / rủi ro / công sức.

| # | Mã | Biện pháp | Nhóm | Lợi ích dự kiến | Rủi ro | Công sức | Rollback |
|---|---|---|---|---|---|---|---|
| 1 | B-1 | Trước khi huấn luyện (hoặc trong khung giờ huấn luyện): **lưu và đóng** workbook Excel không dùng, tab Chrome/Brave không cần, Teams / Outlook mới / Zalo nếu không dùng lúc đó | B | Đo được (commit / RAM resident): Excel 2,4 GB / 1,2 GB; Chrome + Brave 5,6 GB / 1,9 GB; Teams + Outlook WebView2 1,8 GB / 0,38 GB; Zalo 1,0 GB / 0,36 GB. **Ước tính +3-6 GB commit, +1,5-3 GB RAM trống** | Không ảnh hưởng dữ liệu. Phải lưu công việc trước khi đóng (người dùng tự làm) | Không | Mở lại ứng dụng |
| 2 | B-4 | **Thêm page file cố định trên D:** (ví dụ ban đầu 16 GB, tối đa 32 GB). Giữ nguyên page file tự quản lý trên C: | B (quản trị, khởi động lại) | Giới hạn commit sau mỗi lần khởi động từ 33 GB lên khoảng 49 GB, nên bộ bảo vệ hết hoãn job vì page file vừa bị thu nhỏ. **Không** thêm RAM: phân trang vẫn như cũ | Thấp. C: và D: cùng một SSD NVMe; D: còn 71 GB | Nhỏ: System Properties → Advanced → Performance → Virtual memory; cần quyền quản trị (tài khoản Giau Vo không có) | Bỏ page file D:, khởi động lại |
| 3 | B-2 | Bật **Memory Saver** của Chrome và Brave (Settings → Performance). Tắt **Startup boost** và chạy nền của Edge. Tắt mục khởi động `MicrosoftEdgeAutoLaunch` (Edge không phải trình duyệt chính) | B | Tab không dùng được giải phóng. Ước tính 0,5-1,5 GB RAM. Edge: 7 tiến trình, 264 MB commit | Thấp: tab được tải lại khi mở | Nhỏ | Bật lại trong cài đặt |
| 4 | B-5 | **Đổi giờ huấn luyện** khỏi 08:20, giờ làm việc lúc máy đang mở nhiều ứng dụng. Ví dụ giờ nghỉ trưa hoặc cuối buổi chiều. Phải sau khi D-1 xong | B (lịch, chủ hệ thống quyết) | Huấn luyện gặp lúc máy ít tải hơn: ít phân trang, ít bị hoãn. Lợi ích phụ thuộc thói quen dùng máy | Thấp. Máy ngủ khi rảnh (Modern Standby), nên tránh giờ máy ngủ | Đổi trong giao diện app | Đặt lại 08:20 |
| 5 | B-11 | **Nâng RAM lên 32 GB** (2 × 16 GB DDR4-3200 SO-DIMM). Máy có 2 khe (đang 8 + 8 GB, hai hãng khác nhau), hỗ trợ tối đa 64 GB | B (mua phần cứng) | +16 GB RAM và +16 GB commit. Giải quyết cả phân trang lẫn hoãn job. **Hiệu quả lớn nhất** | Thấp nếu mua đúng chuẩn (cặp cùng loại) | Mua + kỹ thuật lắp | Lắp lại thanh cũ |
| 6 | B-3 | Rà **ứng dụng khởi động** (Task Manager → Startup apps, chỉ *Disable*, không gỡ). Ứng viên: BlueStacks Services (150 MB commit); Autodesk Access, Genuine Service (khoảng 0,3 GB) nếu không dùng Autodesk hằng ngày; Adobe CCX; Logitech Download Assistant; Power BI personal gateway (424 MB commit) nếu không làm mới Power BI từ máy này. **QZ Tray** (827 MB commit) và Seagull: chỉ khi chắc không in nhãn | B | Ước tính 0,5-1,8 GB commit, 0,1-0,3 GB RAM | Thấp: tính năng đó không tự chạy cho tới khi mở tay | Nhỏ | Enable lại trong Task Manager |
| 7 | A-1 | **Đo đỉnh bộ nhớ từng bước của huấn luyện** trên bản sao DB (LOCALAPPDATA cách ly, scheduler tắt): nạp dữ liệu, panel, ma trận, Dataset, từng fold | A (không đổi production). Là tác vụ nặng (khoảng 30-45 phút, khoảng 3 GB), nên **xin phép giờ chạy** | Biết chính xác bước nào tạo đỉnh +2,4 GB trước khi sửa mã | Thấp. Chiếm RAM trong lúc đo, nên chạy khi máy rảnh | Trung bình | Không cần |
| 8 | B-8 | Nạp dữ liệu theo khối hoặc thẳng vào mảng có kiểu thay cho `pd.read_sql_query` (đỉnh +1,13 GB cho khung 296 MB) | B (mã, cần phát hành) | Ước tính −0,5 đến −0,8 GB ở bước nạp. Chỉ giảm đỉnh huấn luyện nếu A-1 cho thấy bước nạp là đỉnh | Trung bình. Phải chứng minh panel và model giống từng byte | Trung bình | Bản cũ |
| 9 | B-9 | Chạy huấn luyện / backtest trong **tiến trình con**, không chạy trong server | B (mã, cần phát hành) | Server trở về mức nền ngay sau job; lỗi của job không làm sập web. Không giảm đỉnh | Trung bình (hủy job, tiến độ, log) | Lớn | Bản cũ |
| 10 | A-2 → B-10 | **D-1 đọc 13,2-13,5 GB mỗi lần** (database 2,6 GB). Trước hết đo truy vấn trên bản sao (A-2); sửa chỉ khi có số đo (B-10, có thể cần index / migration theo quy tắc AGENTS.md) | A rồi B | Bớt đẩy cache file của Windows; D-1 nhanh hơn | Thấp (đo); trung bình (sửa) | Trung bình | Bản cũ |
| 11 | B-6 | Bộ bảo vệ bộ nhớ: tính thêm phần page file Windows có thể nới (giới hạn theo dung lượng trống), hoặc thêm nút "vẫn chạy" có cảnh báo | B (mã, cần phát hành) | Ít hoãn job không cần thiết | Trung bình: có thể cho job chạy vào lúc thật sự hết bộ nhớ | Nhỏ-trung bình | Bản cũ |
| 12 | B-7 | `num_threads` 8-10 thay vì 0 (12 luồng) | B (thay cấu hình LightGBM, đo trước) | **Không giảm RAM đáng kể.** Giảm cạnh tranh CPU (đo được 6 lõi bận suốt 30 phút) | Model có thể khác chút do thứ tự cộng số thực. Phải đo WAPE / bias / thời gian trên bản sao | Nhỏ + 1-2 giờ đo | Đặt lại 0 |
| 13 | B-12 | Khởi động lại định kỳ các ứng dụng mở lâu (Excel 25,8 giờ; Teams WebView2 869 MB) | B | Chưa chứng minh được rò rỉ. Lợi ích không chắc | Thấp | Không | - |
| 14 | B-13 | Dọn ổ đĩa (mục 3) | B | Dung lượng ổ, **không** giúp RAM | Xem mục 3 | Nhỏ | Theo từng mục |

**Nếu mã thay đổi (B-6, B-8, B-9, B-10):** phải phát hành phiên bản mới. Bước **triển khai** là nhóm C theo yêu cầu,
cần phê duyệt riêng.

### 2. Không làm (nhóm C)

| Mã | Biện pháp | Lý do |
|---|---|---|
| C-1 | Tắt dịch vụ Windows (SysMain, Search, …), tắt nén bộ nhớ, chỉnh Registry | Tổng svchost chỉ 219 MB resident. Tác động khó lường |
| C-2 | Tự động kill tiến trình theo ngưỡng RAM | Mất dữ liệu đang làm (Excel, trình duyệt) |
| C-3 | Xóa database, lịch sử, model, backup; đổi model production; giảm `direct_origins` / `num_leaves` / số fold để tiết kiệm RAM khi chưa đo độ chính xác | Mất dữ liệu hoặc giảm chất lượng dự báo |
| C-4 | Gỡ phần mềm (BlueStacks, Autodesk, CocCoc, UltraViewer, …) | Gỡ cài đặt là nhóm C. B-3 đạt phần lớn lợi ích mà không gỡ |
| C-5 | Đụng tới `Green Christmas Tree` | Chương trình chủ máy tự cài. Mục khởi động hiện đang *disabled* (không do audit này đổi) |
| C-6 | Triển khai bản mới chứa thay đổi mã | Cần phê duyệt riêng, theo `scripts\deploy-upgrade.ps1` |

### 3. Ổ đĩa (không liên quan RAM)

**Hiện trạng:** C: còn **30,1 GB / 375 GB**; D: còn 71,1 GB / 100 GB. Chi tiết ở `DISK_USAGE.csv`.

**Liên quan tới RAM:** chỉ gián tiếp. Page file do Windows tự quản lý chỉ nới được khi C: còn chỗ. Ổ C: càng trống thì giới
hạn commit càng nới được, khi B-4 chưa làm.

**Ứng viên dọn** (tất cả là B: chưa xóa gì, mỗi mục cần duyệt riêng, kiểm tra lại ngay trước khi xóa):

| Mã | Mục | Dung lượng | Tái tạo được? | Điều kiện trước khi xóa | Rollback |
|---|---|---|---|---|---|
| D-1 | Scratchpad Claude của dự án này (`%LOCALAPPDATA%\Temp\claude\d--Buymed-Lightgbm-AI\672ca914-…\scratchpad`): bản sao DB `p20`-`p32`, cài cách ly `r7`-`r14`, backtest `bt` | **34,6 GB** | Có (là bản sao / diễn tập) | Kiểm tra lại từng thư mục như kế hoạch 22/10 (15,4 GB đã xác minh): không tiến trình nào dùng, trạng thái DB có backup chính thức, bằng chứng đã nằm trong `reports\`. Lần trước lệnh xóa bị bộ phân loại quyền chặn, nên chủ hệ thống tự chạy script | Không (bản sao). Bằng chứng giữ trong `reports\` |
| D-2 | `%TEMP%\DemandForecast-deploy-*`: 38 thư mục giải nén gói, 15/10-23/10 | **9,5 GB** | Có (gói trong `dist`) | Không có deploy nào đang chạy. **Kèm sửa `scripts\deploy-upgrade.ps1:133-136`** để xóa thư mục tạm sau khi cài xong (mã, B) | Giải nén lại từ gói |
| D-3 | 21 bản Demand Forecasting cũ đã cài (giữ 1.2.13 đang chạy và 1.2.11) | **khoảng 5,5 GB** | Có (gói `dist`) | Các bản cũ không mở được database schema 10. Gỡ theo quy trình, không xóa thư mục đang chạy | Cài lại từ gói |
| D-4 | TEMP: bộ tải Autodesk `odis_download_dest` 3,8 GB; bộ cài tạm `ns*.tmp` / `3K*` 3,0 GB; `Rar$EXa…` (07/2026) 2,1 GB; `.tmp` / `.log` rời 1,6 GB | **khoảng 10,5 GB** | Có | Đóng trình cài / WinRAR. Dùng Storage Sense hoặc Disk Cleanup → *Temporary files* | Không cần |
| D-5 | Cache gói: `uv` 2,3 GB, `npm-cache` 1,2 GB, `ms-playwright` 0,7 GB, `pip` 0,4 GB | **khoảng 4,6 GB** | Có (tải lại) | Dùng lệnh dọn của từng công cụ | Tự tải lại khi cần |
| D-6 | `%USERPROFILE%\.cache\huggingface` (model AI, 19/09) | 4,25 GB | Có (tải lại) | Chỉ khi dự án dùng nó không còn cần | Tải lại |
| D-7 | 679 file `.jpg` (4,0 GB) ở gốc TEMP | 4,0 GB | Chưa rõ | Người dùng xem nguồn gốc. Audit không mở file cá nhân | - |

**Không đề xuất xóa:**
- `ZaloData` 25 GB: tin nhắn và tệp cá nhân; dọn trong Zalo nếu muốn;
- hộp thư Outlook 8,7 GB;
- database 2,57 GB, model, `backups` 3,3 GB (theo `prune-artifacts.ps1` nếu cần), `dist` 1,8 GB, `checkpoints`;
- `hiberfil.sys` 6,3 GB: chỉ tắt ngủ đông nếu thật sự thiếu ổ.

Nếu làm D-1 đến D-5, C: có thể trống thêm **khoảng 65 GB**.

### 4. Cách đo sau mỗi thay đổi

Mọi biện pháp đã duyệt được đo trước và sau, cùng cách đo:
- Máy: `\Memory\Available MBytes`, `Committed Bytes`, `Commit Limit`, `Pages Output/sec` (script `evidence\script-sampler.ps1`).
- App: `resources` của job, gồm `private_peak_mb`, `phys_avail_min_mb`, `commit_avail_min_mb`, `page_faults`, `wall_s`.
  Ghi lại quyết định của bộ bảo vệ (`OK` / `PAGING_EXPECTED` / `INSUFFICIENT_MEMORY`).
- Thay đổi về mã hoặc LightGBM: đo thêm WAPE / bias trên cùng các fold, kèm hash model. Rollback khi WAPE hoặc bias xấu
  đi, hoặc model khác mà không có lý do đã duyệt.
- Không ảnh hưởng dữ liệu: hash `storage.json`, `data-check` trước và sau, không chạy trên database thật.

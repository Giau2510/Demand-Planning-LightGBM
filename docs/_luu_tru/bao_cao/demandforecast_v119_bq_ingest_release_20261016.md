# BigQuery ingest + phát hành local — 16/10/2026 15:00–15:30 (giờ Việt Nam)

**Kết luận: `READY_FOR_EXTERNAL_SETUP`.**
- Nguồn BigQuery nay đạt mọi kiểm tra: không còn dòng trùng hoàn toàn và ngày 15/10 đã có dữ liệu.
- QA đạt.
- Phát hành **bị chặn ở bước commit**: `scripts\release.ps1` không đóng gói từ cây làm việc chưa commit, và người dùng chưa
  cho phép commit. Vì vậy chưa có gói 1.1.9, chưa nâng cấp local và **chưa ghi dữ liệu BigQuery vào DB thật**.

Không commit, không push, không triển khai VPS. Không đổi lịch chạy, nguồn dữ liệu, chế độ sản xuất hay model.

## 1. Git và file thay đổi

- Nhánh `main`, HEAD `d87c315` (không đổi), không stash. 37 mục trong `git status`: 26 file sửa, 11 mục mới.
  Toàn bộ là thay đổi của đợt audit, đợt BigQuery ingest và đợt storage/release, cộng với các file của đợt này bên dưới.
- Sửa trong đợt này:
  - `backend/app/__init__.py` và `frontend/package.json`: phiên bản **1.1.9**, để bản phát hành không trùng 1.1.8;
  - `CHANGELOG.md`: tiêu đề "Unreleased" đổi thành "1.1.9";
  - `docs/BIGQUERY.md` mục 13: kết quả kiểm tra thật lúc 15:03 và lưu ý về D-0 khi đổi nguồn;
  - `docs/CHECKPOINT.md`: thêm mục của đợt này.

## 2. Test đã chạy trong đợt này

| Loại | Kết quả |
|---|---|
| Backend toàn bộ (unit / integration với BigQuery giả lập) | **300 đạt, 2 bỏ qua**, exit 0. Gồm 19 test ingest: trùng chặn trước tổng hợp, báo cáo xlsx/CSV, chạy lại không nhân đôi, lỗi giữa lúc ghi → rollback toàn bộ |
| BigQuery thật, dữ liệu nội tuyến (`DF_REAL_BQ=1`, 0 byte) | **2/2 đạt** |
| Frontend vitest / typecheck / build | **61/61** / đạt / đạt |
| Log | `logs\development\tests_20261016_150156.log` |
| Lint | chưa cấu hình |

## 3–5. BigQuery (truy vấn thật, chỉ đọc, trên bản sao DB cô lập)

Bản sao DB mới tạo lúc 15:02 bằng SQLite backup API, nguồn mở chỉ đọc. Dùng ADC của tài khoản Windows này, vùng
`asia-southeast1`. Mọi truy vấn đều dry-run trước và có giới hạn byte; tổng quét khoảng 12 GB. Ánh xạ là ánh xạ gợi ý,
đã kiểm với schema thật và chỉ lưu trên bản sao.

| Hạng mục | Kết quả |
|---|---|
| Xác thực, kết nối | đạt (bảng `TABLE` không phân vùng, 8.893.414 dòng) |
| Phạm vi dữ liệu nguồn | 01/01/2026 → **15/10/2026** |
| Ngày 15/10 | **18.992 dòng**, demand 93.031; TB 7 ngày trước 18.772 dòng. Kiểm tra ngày đủ dữ liệu: `PASSED` |
| Ánh xạ | `PASSED`; so sánh 15 cột; không so `seller_class`, `refresh_time` |
| **Chốt trùng hoàn toàn** (chính sách production `BLOCK`), 01/01–15/10 | **0 nhóm / 0 dòng / 0 dòng dư** trên 8.893.414 dòng → `PASSED` (không có báo cáo vì không có dòng trùng) |
| Tổng hợp ngày × SKU × FC | **1.347.346 dòng**, tổng demand **41.722.635** = tổng nguồn; 0 dòng bị loại; 7.211 dòng lặp khóa đơn được cộng (`SUM_ALL`) |
| Kiểm tra sau tổng hợp | đạt (một dòng mỗi khóa) |
| Kết quả dry-run | **`READY`**, không ghi gì |
| Kiểm tra toàn kỳ | đạt; cảnh báo không chặn: `KEY_NOT_UNIQUE`, `MISSING_DAYS`, `TARGET_OUTLIER` |
| Ghi thử vào **bản sao**, lần 1 (nạp lại toàn kỳ) | 1.347.346 dòng, 41.722.635 |
| Ghi thử vào bản sao, lần 2 (chạy lại 12/10–15/10) | 13.345 dòng **không đổi**, tổng giữ nguyên |
| Sau khi ghi thử | 0 khóa lặp; 9.661 SKU, 2 FC; dữ liệu DEMO trên bản sao không đổi |

So với lần kiểm tra lúc 13:23, nguồn đã được làm mới: hết dòng trùng, thêm ngày 15/10, và tổng 01/01–14/10 cũng đổi.
Đây là số liệu của nguồn tại 15:03; nguồn được làm mới hằng ngày nên lần nạp thật có thể khác.

## 6–8. Phát hành và nâng cấp local

| Bước | Trạng thái |
|---|---|
| `scripts\release.ps1` | **BLOCKED**: `Uncommitted changes: commit (and review) first.` Không chạy QA của script, không tạo gói |
| Gói 1.1.9 | chưa có |
| `dist\` | giữ nguyên: 1.1.8 `0DFDEC86…5EE0` và 1.1.6 `A2E0345C…9561`, SHA-256 khớp file `.sha256` |
| Nâng cấp local | **chưa chạy** |
| App đang chạy | **1.1.8** (pid 18608): `/api/health` ok, UI HTTP 200 |
| Rollback | `rollback-version.ps1 -To 1.1.6 -CheckOnly`: OK, không cần khôi phục DB (schema 3) |

## 9. DB thật trước/sau

Ảnh chụp chỉ đọc lúc bắt đầu và lúc kết thúc là **giống hệt nhau**:
- DB: 21 bảng (số dòng), schema 3, `quick_check` ok, tổng demand 1.014.720;
- 4 settings, 4 model;
- `storage.json` `8D79DBDD…`;
- 25 backup, 9 checkpoint, 10 thư mục bản cài, `current.txt` 1.1.8;
- Git HEAD.

Lịch chạy không đổi: nguồn DEMO, D-1 OFF, D-0 ON, huấn luyện ON 07:00. Với app thật tôi chỉ gửi GET.

## 10. Ingest production

**Chưa thực hiện.** Không ghi dữ liệu BigQuery vào DB thật, vì các điều kiện sau chưa có:
- gói 1.1.9 chứa chốt trùng (bản 1.1.8 đang chạy không có code này);
- ánh xạ đã lưu trong app thật;
- chế độ sản xuất;
- nguồn được người dùng chuyển sang BIGQUERY.

## 11. Việc người dùng cần làm

1. **Xem lại thay đổi và cho phép commit.** Push là tùy chọn. Commit sẽ dùng đường dẫn tường minh và quét secret trước
   (`docs/GITHUB_WORKFLOW.md`).
2. Sau đó, tôi (hoặc người vận hành) chạy:
   - `scripts\release.ps1` để tạo gói 1.1.9;
   - `scripts\deploy-upgrade.ps1 -Package <zip> -ExpectedSha256 <sha> -CheckOnly`;
   - nâng cấp thật với xác nhận `UPGRADE-1.1.9`, ngoài khung D-0 (08:00–18:00 mỗi 2 giờ) và huấn luyện 07:00, khi không có
     job đang chạy.
3. Trên app 1.1.9:
   - **Ánh xạ trường**: *Gợi ý*, rồi *Kiểm tra & lưu ánh xạ*;
   - **BigQuery**: các nút kiểm tra, sau đó *Kiểm tra trùng & thử tổng hợp (không ghi)*. Kết quả mong đợi là `READY`.
4. **Tắt D-0 trước khi đổi nguồn.** Công tắc D-0 hiện đang bật cho DEMO và không tự tắt khi đổi nguồn; nếu để bật, D-0
   BigQuery (chưa kiểm chứng) sẽ chạy theo lịch sau khi bật chế độ sản xuất.
5. Xác nhận rõ ràng việc bật chế độ sản xuất và chuyển nguồn sang **BIGQUERY**, rồi vào **Lịch chạy dữ liệu → D-1 →
   Chạy ngay** (lần đầu nạp lại toàn kỳ). Đối soát với số ở mục 3–5.
6. Không tự bật lịch D-1 hay huấn luyện trên dữ liệu BigQuery; đó là quyết định riêng.

## 12. VPS

Chỉ kiểm tra:
- `bash -n` đạt cho `deploy.sh`, `install-server.sh`, `rollback.sh`;
- `scripts\vps\*` chỉ dùng LF; mọi `scripts\*.ps1` là ASCII.

Bộ triển khai Linux **chưa từng chạy trên Linux**. Không triển khai, vì còn thiếu thông tin VPS (`docs/TRIEN-KHAI-VPS.md`
mục 9). Ứng dụng không có đăng nhập, nên trên VPS bắt buộc đặt sau reverse proxy có TLS và xác thực.

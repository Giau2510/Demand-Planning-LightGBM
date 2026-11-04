# Tài liệu Demand Forecasting – danh mục

Cấu trúc theo bảng 1.3 (chủ dự án duyệt 02/11/2026, áp dụng 03/11/2026). Quy tắc chung cho người và agent:
[../AGENTS.md](../AGENTS.md); riêng Claude Code: [../CLAUDE.md](../CLAUDE.md). Lịch sử phiên bản:
[../CHANGELOG.md](../CHANGELOG.md).

## Cấu trúc thư mục

| Thư mục / file | Nội dung |
|---|---|
| `01_quy_tac\` | Quy tắc: dữ liệu, agent, Git, QA / phát hành |
| `02_kien_truc_du_lieu\` | Kiến trúc, mô hình dữ liệu, từ điển dữ liệu, BigQuery, lưu trữ, lịch sử forecast, giao diện |
| `03_van_hanh\` | Vận hành, lịch chạy, hướng dẫn sử dụng, link từ xa, checkpoint; `su_co\` = sự cố đã xử lý |
| `04_mo_hinh_ket_qua\` | Mô hình và chỉ số, cấu hình đang dùng, điều tra, kết quả; `da_thu\` = phương án đã thử |
| `05_nhat_ky_quyet_dinh.md` | Nhật ký quyết định của chủ dự án |
| `_luu_tru\` | Lưu trữ nguyên văn (không sửa): báo cáo cũ, kế hoạch cũ, thử nghiệm 1.2, bản đăng ký trước |
| `mau\` | File mẫu Excel (cấu hình nguồn dự báo) |
| `THIRD-PARTY-NOTICES.md` | Giấy phép thư viện giao diện, đi kèm gói |

Dữ liệu của các báo cáo (parquet, csv, xlsx, zip, json, code chạy thử) ở lại `reports\` của máy làm việc, ngoài Git. File
.md của báo cáo nằm trong `docs\` (gộp theo chủ đề hoặc lưu trữ nguyên văn); ở đường dẫn cũ trong `reports\` chỉ còn
một dòng "Đã chuyển tới …". Mỗi file gộp có bảng "Nguồn" (đường dẫn gốc, ngày, SHA-256).

Các file một dòng `BIGQUERY.md`, `LICH-SU-FORECAST.md`, `MO-HINH-VA-CHI-SO.md`, `ke_hoach_lgbm_chot.md` ở gốc `docs\`
chỉ để chuyển hướng: migration đã áp dụng và chú thích trong code còn trích đường dẫn cũ.

## 01_quy_tac

| File | Mục đích |
|---|---|
| [quy_tac_du_lieu.md](01_quy_tac/quy_tac_du_lieu.md) | Quy tắc dữ liệu bắt buộc: phân tích theo từng khách và từng dòng đơn (CLAUDE.md import) |
| [GOVERNANCE.md](01_quy_tac/GOVERNANCE.md) | Điều phối agent, task contract, ngân sách, checkpoint |
| [GITHUB_WORKFLOW.md](01_quy_tac/GITHUB_WORKFLOW.md) | Git / GitHub: cái gì được version, commit, push, đồng bộ |
| [PHAT-TRIEN-QA-PHAT-HANH.md](01_quy_tac/PHAT-TRIEN-QA-PHAT-HANH.md) | Phát triển, QA, phát hành, giữ artifact và sao lưu |

## 02_kien_truc_du_lieu

| File | Mục đích |
|---|---|
| [KIEN-TRUC.md](02_kien_truc_du_lieu/KIEN-TRUC.md) | Kiến trúc, module, luồng dữ liệu; tóm tắt bản đồ pipeline 26/10 |
| [DATA-MODEL.md](02_kien_truc_du_lieu/DATA-MODEL.md) | Bảng DB, vòng đời, bất biến, múi giờ |
| [DATA-DICTIONARY.md](02_kien_truc_du_lieu/DATA-DICTIONARY.md) | Từ điển dữ liệu (cột của từng bảng) |
| [BIGQUERY.md](02_kien_truc_du_lieu/BIGQUERY.md) | Nguồn BigQuery, OAuth, SQL editor, D-1 / D0 |
| [LUU-TRU.md](02_kien_truc_du_lieu/LUU-TRU.md) | Đường dẫn lưu trữ, storage.json, di chuyển, rollback |
| [LICH-SU-FORECAST.md](02_kien_truc_du_lieu/LICH-SU-FORECAST.md) | Lưu forecast D+1, thực tế, chốt thực tế, KPI |
| [UI-DESIGN-SYSTEM.md](02_kien_truc_du_lieu/UI-DESIGN-SYSTEM.md) | Thiết kế giao diện (token, icon, component) |

## 03_van_hanh

| File | Mục đích |
|---|---|
| [VAN-HANH.md](03_van_hanh/VAN-HANH.md) | Sao lưu, khôi phục, nâng cấp, rollback, khắc phục sự cố |
| [SCHEDULER.md](03_van_hanh/SCHEDULER.md) | Lịch chạy trong backend (D-1, D0, học lại, SEL2) |
| [HUONG-DAN-SU-DUNG.md](03_van_hanh/HUONG-DAN-SU-DUNG.md) | Hướng dẫn sử dụng giao diện |
| [HUONG-DAN-NGUON-DU-BAO.md](03_van_hanh/HUONG-DAN-NGUON-DU-BAO.md) | Nguồn dự báo theo SKU × FC và file Excel dự báo (1.4.0) |
| [IMPORT-EXCEL.md](03_van_hanh/IMPORT-EXCEL.md) | Import lịch sử bằng Excel |
| [link_tu_xa.md](03_van_hanh/link_tu_xa.md) | Link xem từ xa chỉ đọc; phụ lục Tailscale và sự cố link |
| [TRIEN-KHAI-VPS.md](03_van_hanh/TRIEN-KHAI-VPS.md) | Chuẩn bị triển khai VPS (chưa triển khai) |
| [CHECKPOINT.md](03_van_hanh/CHECKPOINT.md) | Trạng thái để tiếp tục batch hiện tại |
| [su_co/bo_nho_o_dia.md](03_van_hanh/su_co/bo_nho_o_dia.md) | Sự cố RAM / ổ đĩa, audit tài nguyên, dọn ổ đĩa |
| [su_co/d1_lich_su.md](03_van_hanh/su_co/d1_lich_su.md) | Sự cố D-1, lịch sử, backfill, chốt thực tế |
| [su_co/d1_2025.md](03_van_hanh/su_co/d1_2025.md) | Kiểm tra D-1 khi nguồn thêm dữ liệu 2025 |
| [su_co/gio_mo_ban.md](03_van_hanh/su_co/gio_mo_ban.md) | Giờ mở bán, thứ trong tuần, MULTI_ITEM |
| [su_co/luu_tru.md](03_van_hanh/su_co/luu_tru.md) | storage.json, di chuyển dữ liệu, dọn lưu trữ |

## 04_mo_hinh_ket_qua

| File | Mục đích |
|---|---|
| [MO-HINH-VA-CHI-SO.md](04_mo_hinh_ket_qua/MO-HINH-VA-CHI-SO.md) | Mô hình dự báo, chỉ số chất lượng, SEL2 |
| [cau_hinh_dang_dung.md](04_mo_hinh_ket_qua/cau_hinh_dang_dung.md) | Cấu hình PHƯƠNG ÁN CHỐT 1.3.1; 1.4.0 thêm SEL2 |
| [ket_qua_sel2_20261031.md](04_mo_hinh_ket_qua/ket_qua_sel2_20261031.md) | Kết quả kiểm chứng cấu hình 1.4.0 (31/10) |
| [dieu_tra_mo_hinh.md](04_mo_hinh_ket_qua/dieu_tra_mo_hinh.md) | Điều tra chất lượng mô hình (23–26/10) |
| [da_thu/](04_mo_hinh_ket_qua/da_thu/) | Mỗi phương án đã thử một file: README + đăng ký trước + kiểm tra dữ liệu + rò rỉ |

## _luu_tru (nguyên văn, không sửa)

| Thư mục / file | Nội dung |
|---|---|
| `bao_cao\` | Báo cáo phát hành / audit 14–26/10/2026 |
| `dang_ky_truoc\` | Bản PREREGISTRATION giữ nguyên từng byte (SHA-256 ghi trong file gộp tương ứng ở `da_thu\`) |
| `thu_nghiem_1.2\` | Thử nghiệm 16–17/10 (bản 1.2.0) |
| `ke_hoach_130_shadow.md`, `bao_cao_130_shadow.md`, `thanh_phan_tai_su_dung_130.md` | 1.3.0 chạy song song (đóng băng 28/10) |
| `ke_hoach_131_lgbm_chot.md`, `kiem_tra_hien_trang_131.md` | Kế hoạch và kiểm tra hiện trạng 1.3.1 |
| `project_map.md` | Bản đồ pipeline 26/10 (bản 1.2.14), nguyên văn |
| `TRIEN-KHAI-1.1.6.md` … `1.1.8.md` | Ghi chú triển khai cũ (đã thay bằng VAN-HANH.md) |

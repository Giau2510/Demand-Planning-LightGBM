# Backtest đăng ký trước – F1, F2, F3 xong; F4 đã hủy (27/10/2026)

Phương án đã thử: README, đăng ký trước, kiểm tra dữ liệu và kiểm tra rò rỉ gộp một file.

Tài liệu gộp ngày 03/11/2026 theo bảng 1.3 (cấu trúc lại tài liệu). Nội dung từng nguồn được chép nguyên văn, chỉ hạ một cấp tiêu đề và sửa đường dẫn liên kết; số liệu và trạng thái là của thời điểm từng báo cáo, quy tắc hiện hành nằm trong các tài liệu chính (xem [README](../../README.md)). Dữ liệu đi kèm (parquet, csv, xlsx, zip, json) vẫn ở thư mục `reports\` gốc, ngoài Git.

## Nguồn

| # | File gốc (worktree) | Ngày sửa | Byte | SHA-256 |
|---|---|---|---:|---|
| 1 | `reports\backtest-prereg-fast-20261028\README.md` (MAIN) | 27/10/2026 | 17190 | `FFAFE17AC44265910A01B9D9521488265EAC6BFEF58F1A5A0AEA143F2F0C10A9` |
| 2 | `reports\backtest-prereg-fast-20261028\PREREGISTRATION.md` (MAIN) | 27/10/2026 | 4657 | `41CC3A6C1B9EF09F76BD39D30330911D3FC72DEB4F0794F22736D41E72974267` |
| 3 | `reports\backtest-prereg-fast-20261028\data_checks.md` (MAIN) | 27/10/2026 | 6286 | `C1F87E670F158E51285B7CD18292C1B81043F7A39B113D771233F0AEDE966A35` |
| 4 | `reports\backtest-prereg-fast-20261028\leakage_summary.md` (MAIN) | 27/10/2026 | 1509 | `03F47FCD8715E1DD7E72D83781D5A10BBD3FB88473ECA82FFA22E886C494D8EB` |
| 5 | `reports\backtest-prereg-fast-20261028\chan_doan_khach_hang.md` (MAIN) | 27/10/2026 | 3997 | `138BCE36268394E8FCCC613B34B376418BCD6884C51700375678A0D9528281E4` |

## 1. Backtest đăng ký trước – F1, F2, F3 xong; F4 đã hủy (27/10/2026)

Nguồn: `reports\backtest-prereg-fast-20261028\README.md` (worktree MAIN).

### Đăng ký trước

- `PREREGISTRATION.md`: chép nguyên văn khối đăng ký (UTF-8 không BOM, xuống dòng LF, 4.657 byte).
- **SHA-256 `41CC3A6C1B9EF09F76BD39D30330911D3FC72DEB4F0794F22736D41E72974267`**, ghi lúc **2026-10-27 11:23:49** (giờ VN).
  File được ghi trước mọi bước khác và đặt chỉ đọc ngay sau khi tính SHA.
- `THU_MUC_CSV_AVG` để trống, nên không có CSV `avg_demand_history` để so sánh. Bước kiểm chứng CSV bị bỏ qua.
- `DF_HASH_SALT`: có ở biến môi trường cấp người dùng Windows, nhưng không có trong tiến trình hiện tại. Lệnh chạy nạp
  giá trị đó vào biến môi trường của tiến trình con mà không in ra. Giá trị không xuất hiện trong bất kỳ file, log hay câu
  trả lời nào.

(Các phần dưới được bổ sung trong lúc chạy.)

### Lệnh chạy chính xác

Môi trường (PowerShell), giống vòng 1:

```
$bt = '<scratchpad>\bt'                                 # thư mục dữ liệu của bản sao DB vòng 1
$env:DF_DATA_DIR = $bt; $env:LOCALAPPDATA = "$bt\L"; $env:DF_DISABLE_SCHEDULER = '1'
$env:PYTHONPATH = 'D:\Buymed\Lightgbm AI\backend'        # code app: chỉ import
$env:DF_HASH_SALT = [Environment]::GetEnvironmentVariable('DF_HASH_SALT','User')   # chỉ cho bước 1.2, không in
```

Python: `D:\Buymed\Lightgbm AI\.venv\Scripts\python.exe` (Python 3.14.7, LightGBM 4.7.0).

```
python -X utf8 code\bq_orders.py --out .                                  # 1.2 truy vấn dòng đơn (dry run, trần 3 GB)
python -X utf8 -I code\avg_by_date.py . <bt>\db\app.db                    # 1.1 avg_by_date + kiểm chứng + rò rỉ Avg
python -X utf8 -I code\orders_check.py . <bt>\db\app.db <vòng 1>\openhours.parquet   # 1.2 đối soát + 1.3 chẩn đoán
python -X utf8 -I code\features_build.py . <bt>\db\app.db                 # 1.4 bảng biến theo khách + rò rỉ
python -X utf8 code\fast_runner.py --out . --mode smoke                   # 2.1 chạy thử
```

Lệnh thực tế đã chạy ở bước 2–3, sau hai lần điều chỉnh vận hành và quyết định hủy F4 (xem các mục bên dưới):

```
python -X utf8 code\fast_runner.py --out . --mode run --phases F1,F2      # F1 xong, dừng bằng PAUSE trước F2
python -X utf8 -I code\assemble.py . F1
python -X utf8 -I code\make_package.py . <bt>\db\app.db <tạm>\stage_tam1 package_tam1 F1
python -X utf8 code\fast_runner.py --out . --mode run --phases F3
python -X utf8 -I code\assemble.py . F1,F3
python -X utf8 -I code\make_package.py . <bt>\db\app.db <tạm>\stage_tam2 package_tam2 F1,F3
python -X utf8 code\fast_runner.py --out . --mode run --phases F2,F4      # F2 xong, dừng bằng PAUSE trước F4
python -X utf8 -I code\assemble.py . F1,F2,F3
python -X utf8 -I code\make_package.py . <bt>\db\app.db <tạm>\stage_tam3 package_tam3 F1,F2,F3
python -X utf8 -I code\make_package.py . <bt>\db\app.db <tạm>\stage_final package F1,F2,F3 variant_status.tsv   # gói cuối
```

**Sửa lỗi:** không bước nào phải sửa lỗi. Mỗi script chạy thành công ngay lần đầu.

### Kết quả bước 1 (chi tiết ở `data_checks.md`, `chan_doan_khach_hang.md`)

| Bước | Kết quả |
|---|---|
| 1.1 Avg | avg_history vòng 2 (SHA trùng). Hồi quy: hệ số **D = −0,0068 (p = 0,059, không ý nghĩa)**, hệ số **D-1 = +0,0598 (p = 3,5e-8, dương có ý nghĩa)**. **Đạt điều kiện → dùng biến Avg.** Không có CSV để so. |
| 1.2 Dòng đơn | 8.993.350 dòng (01/01–22/10/2026), 655 MB. Khớp `demand_daily` **99,34 % khóa**, nên không đánh dấu. |
| 1.3 Chẩn đoán (nhóm A, 01/06–31/08) | **13,2 %** lượng từ khách đều. Ngày đột biến: **9,5 %** từ khách đều, **2,5 %** từ khách đến hạn. Ngày thường: 15,4 % và 4,7 %. |
| 1.4 Bảng biến | 17 biến khách × 17.140 SKU × FC × 296 ngày; 7 biến mới tính trong runner. Rò rỉ mức biến 12 / 12 đạt (Avg 6, khách 6). |

### Bước 2.1: chạy thử (01–03/06, mốc 01/06)

**Tái lập đường chạy: ĐẠT.**
- F0 là chính code của F1–F4 nhưng không thêm cột. So với V1 vòng 1 (`parts\V1\batch_01_2026-06-01.csv.gz`): khớp 92.916 /
  92.916 dòng, cả h = 1 và h = 2.
- **Sai khác lớn nhất 0,0**, phương pháp trùng 100 %.

**Rò rỉ.**
- T1–T3 của runner cũ: đạt.
- Kiểm tra pipeline F3: **5 / 5 đạt**.
  - T1F: đổi demand, giờ mở bán, lần đặt và Avg sau mốc; model và dự báo giống hệt.
  - Đối chứng âm (đổi dữ liệu thì dự báo D phải đổi):

    | Kiểm tra | Dữ liệu bị đổi | Số chuỗi đổi dự báo |
    |---|---|---|
    | T2F | demand D-1 | 4.487 |
    | T5F | giờ mở bán D-1 | 4.505 |
    | T7F | Avg ngày D | 3.863 |
    | T8F | lần đặt D-1 | 3.600 |

**Nguồn biến:** Avg và cube biến khách trùng với tính trực tiếp.

**Tính tất định:** model F3 huấn luyện lại (biến tính trực tiếp) trùng từng byte với model chạy thử (biến từ cube).

**Ước tính:** từ lô 1; các lô sau nhiều dữ liệu hơn nên chậm hơn.

| Biến thể | Mục tiêu | Số biến | Huấn luyện lô 1 | RAM đỉnh | Ước tính 21 lô |
|---|---|---|---|---|---|
| F1 | Tweedie 1,2 | 43 | 121 s | 2,8 GB | khoảng 1,1 giờ |
| F2 | l1 | 43 | **782 s** | 2,8 GB | khoảng 5,5 giờ |
| F3 | Tweedie 1,2 | 60 | 122 s | 3,4 GB | khoảng 1,2 giờ |
| F4 | l1 | 60 | **785 s** | 3,4 GB | khoảng 5,6 giờ |

- Mục tiêu l1 huấn luyện chậm hơn khoảng 6,5 lần so với Tweedie.
- Tổng ước tính khoảng 13–14 giờ.

**Đổi sau chạy thử:**
- Bảng `PHASES` của runner được thêm các pha một biến thể ("F1", "F2", "F3", "F4"), để chạy đúng thứ tự "F1, rồi F2" rồi F3,
  F4. Logic tính toán không đổi.
- SHA runner dùng cho chạy đầy đủ được ghi trong `run_config.json` và trong mỗi checkpoint.

### Gói tạm (bước 2.3)

Đường dẫn: **`D:\Buymed\Lightgbm AI\reports\backtest-prereg-fast-20261028\package_tam\`**
(`goi1_hoso.zip`, `goi2_dulieu.zip` hoặc `goi2_dulieu_2026-MM.zip`, `MANIFEST.csv`).
- Gói được tạo ngay khi F1 và F2 xong, trước khi chạy F3, F4.
- `goi2` có cột F1, F2, m_F1, m_F2 (float64) và `avg_by_date_eval.parquet`.

### Điều chỉnh vận hành theo yêu cầu người dùng (27/10/2026 13:54 giờ VN)

`PREREGISTRATION.md` không đổi. Yêu cầu nhận lúc F1 đang chạy lô 05.

**Thứ tự mới:** F1 (không dừng) → **package_tam1** (cột F1) → F3 → **package_tam2** (cột F1, F3) → F2 → F4 → gói cuối.
Mục "Gói tạm" ở trên được thay bằng thứ tự này.

**Cách thực hiện (không dừng F1):**
1. Một tiến trình theo dõi tạo file `PAUSE` ngay khi F1 bắt đầu lô cuối (lô 21).
2. Runner chỉ kiểm tra `PAUSE` trước mỗi lô, nên F1 chạy hết lô 21, rồi tiến trình dừng trước lô 1 của F2 (mã thoát 5).
3. Xóa `PAUSE`, đóng gói package_tam1, rồi chạy F3 (`--phases F3`).
4. Sau F3: đóng gói package_tam2, rồi chạy `--phases F2,F4`.

Code và cấu hình không đổi.

**Diễn biến thực tế.**
- Lệnh chạy bắt đầu 13:32:36; lô 1 của F1 bắt đầu 13:34:36. F1 xong lô 21 lúc 14:59:37 (21/21 lô DONE, khoảng 1 giờ 25 phút).
- Runner dừng đúng trước lô 1 của F2 (mã thoát 5). Bước đóng gói trong chuỗi lệnh cũ không chạy, vì chuỗi chỉ đóng gói
  khi mã thoát là 0.
- `assemble.py . F1`: 4.758.772 dòng, đủ 144 ngày, mỗi ngày có cả 2 tầm, 0 NaN, 0 âm; rò rỉ 185 / 185 đạt.
- package_tam1 đóng lúc khoảng 15:02; đối soát khớp tuyệt đối.
- F3 (`--phases F3`): lệnh chạy bắt đầu 15:03:42; lô 1 bắt đầu 15:05:41; lô 21 xong 16:24:02 (21/21 DONE, khoảng 1 giờ
  18 phút); mã thoát 0.
- `assemble.py . F1,F3`: F3 có 4.758.772 dòng, đủ 144 ngày, cả 2 tầm, 0 NaN, 0 âm; rò rỉ 350 / 350 đạt (tính cả F1).
- package_tam2 đóng lúc khoảng 16:25; đối soát khớp tuyệt đối.
- F2, F4 (`--phases F2,F4`): lệnh chạy bắt đầu khoảng 16:26; lô 1 của F2 bắt đầu 16:28:44.

### Điều chỉnh vận hành lần 2 theo yêu cầu người dùng (27/10/2026 17:25 giờ VN)

`PREREGISTRATION.md` không đổi. Yêu cầu nhận lúc F2 đang chạy lô 05 (4 / 21 lô xong).

1. Khi F2 xong: **không tự bắt đầu F4**. F4 tạm dừng chờ quyết định của chủ dự án, chưa hủy.
2. Đóng gói **package_tam3** (cột F1, F2, F3 và m_*, float64; `avg_by_date_eval.parquet`; `MANIFEST.csv`; hồ sơ có
   `feature_gain_F2.csv`, `train_log.csv`, README cập nhật).

**Cách thực hiện.** Giống lần 1:
- Một tiến trình theo dõi tạo `PAUSE` khi F2 bắt đầu lô 21.
- Runner chạy hết lô 21 của F2, rồi dừng trước lô 1 của F4 (mã thoát 5).
- Sau đó chạy `assemble.py . F1,F2,F3` và `make_package.py … package_tam3 F1,F2,F3`.
- `PAUSE` được giữ nguyên cho tới khi chủ dự án quyết định về F4.

Code và cấu hình không đổi.

Đường dẫn: `D:\Buymed\Lightgbm AI\reports\backtest-prereg-fast-20261028\package_tam3\`

**Diễn biến thực tế.**
- F2: lô 1 bắt đầu 16:28:44; lô 21 xong 23:23:30 (21/21 DONE, khoảng 6 giờ 55 phút).
- `PAUSE` được tạo 23:14:20 (lúc lô 21 bắt đầu). Runner dừng trước lô 1 của F4 (mã thoát 5); **F4 chưa chạy lô nào**.
  `PAUSE` được giữ nguyên.
- **Lô 11 chậm bất thường: 10.535 s (2 giờ 56 phút)**, trong khi các lô khác mất 425–953 s.
  - Đo lúc 21:28: máy còn khoảng 1,4 GB RAM trống, bộ nhớ cam kết 31,3 / 35,4 GB, đọc trang từ đĩa 200–450 trang/giây.
    Runner chỉ còn 0,95 GB trong RAM (bộ nhớ riêng 2,19 GB) và dùng khoảng 2,4 / 12 lõi.
  - Nguyên nhân có khả năng nhất: máy thiếu RAM do các chương trình khác.
  - Chỉ tốc độ bị ảnh hưởng; code, dữ liệu và tham số không đổi. Không can thiệp gì trong lúc chạy.
- `assemble.py . F1,F2,F3`: F2 có 4.758.772 dòng, đủ 144 ngày, cả 2 tầm, 0 NaN, 0 âm. Rò rỉ 515 / 515 đạt (F1, F2, F3).

- package_tam3 đóng lúc khoảng 23:25; đối soát khớp tuyệt đối.

### Quyết định của chủ dự án: hủy F4 (27/10/2026 23:42 giờ VN)

`PREREGISTRATION.md` không đổi. **F4 bị hủy và không chạy.** Quyết định đưa ra khi F4 chưa chạy lô nào (runner đã dừng
bằng `PAUSE` trước lô 1 của F4).

Lý do (theo chủ dự án):
- (a) Chủ dự án không dùng biến khách hàng trong vận hành. Quyết định này có trước khi F4 bắt đầu.
- (b) F2 (cùng mục tiêu L1) không đạt điều kiện vận hành đã cam kết trước khi có kết quả: lệch giảm ≥ 1 điểm **và**
  thiếu hàng không nặng hơn V1.

**F4 không có kết quả nào được xem.** Không có checkpoint, model hay dự báo F4 nào; thư mục `parts\F4` không có file.
Việc chấm F2 theo điều kiện ở (b) do chủ dự án thực hiện; quy trình này không tính chỉ số so với thực tế hay Avg.

Thực hiện:
- Xóa `PAUSE` (23:42:57).
- Gói cuối = nội dung package_tam3 (cột F1, F2, F3) + README cuối + MANIFEST cuối.
- `MANIFEST.csv` ghi F4 = "đã hủy" kèm lý do ở mục `variant`; `feature_gain_F4.csv` được ghi là vắng vì F4 đã hủy.
- Lý do được truyền qua `variant_status.tsv`.
- `make_package.py` được thêm tham số tùy chọn thứ 6 để ghi trạng thái này. Phần đóng gói dữ liệu và đối soát không đổi.

**Đường dẫn gói:**
- Gói tạm 1: `D:\Buymed\Lightgbm AI\reports\backtest-prereg-fast-20261028\package_tam1\`
- Gói tạm 2: `D:\Buymed\Lightgbm AI\reports\backtest-prereg-fast-20261028\package_tam2\`
- Gói tạm 3: `D:\Buymed\Lightgbm AI\reports\backtest-prereg-fast-20261028\package_tam3\`
- **Gói cuối: `D:\Buymed\Lightgbm AI\reports\backtest-prereg-fast-20261028\package\`**

**Tổng kết.**
- Biến thể xong: **F1, F2, F3**, mỗi biến thể 21/21 lô, 4.758.772 dòng, 144 ngày (01/06–22/10), tầm 1 và 2, 0 NaN, 0 âm.
- F4: đã hủy.
- Rò rỉ: **515 / 515 đạt** (`leakage_summary.md`, `self_check.json`).
- Thời gian: bắt đầu 11:23:49 (ghi `PREREGISTRATION.md`), gói cuối khoảng 23:45 ngày 27/10/2026, **khoảng 12 giờ 21 phút**.
- Huấn luyện đầy đủ: F1 khoảng 1 giờ 25 phút, F3 khoảng 1 giờ 18 phút, F2 khoảng 6 giờ 55 phút (gồm lô 11 chậm 2 giờ 56
  phút).
- Bản sao DB sau khi chạy: SHA `C7A663BE…F073`, không đổi.

### SHA-256 (dữ liệu và code)

| File | SHA-256 |
|---|---|
| `PREREGISTRATION.md` | `41CC3A6C1B9EF09F76BD39D30330911D3FC72DEB4F0794F22736D41E72974267` |
| Bản sao DB (trước khi chạy) | `C7A663BEC575BEF7221A2C7B50B229294A7E54CD466FC2DEA476A2F35E13F073` |
| `avg_history.parquet` (vòng 2) | `F12A2A6E5C572C6B5758FA988FA0C135D60E9643043F23CD11C8589C23ABE887` |
| `avg_by_date.parquet` | `758B4A38270E52E271B59EC70DF19C9D1FA12733CBB5DED792B000E48AE7B2F6` |
| `order_lines.parquet` (không đóng gói) | `0E45D301E4D044B2D581C875A8CE3095DD0CCBA80FDC8FAED5A15EAFDF49A82A` |
| `placements.parquet` (không đóng gói) | `4691AFC7C821899C28E0048FF15DA71439AF837138FA06BCBC6BFC2DB7EED711` |
| `features_customer.parquet` | `578C6E247EC7F34D401AA49A8774C94FB9E3F108E18F3A9D83AC594B6B42CAEF` |
| `features_customer_cube.npy` | `8A274E049B6A69BE06466C0605DD6D01345153792C77DC6E6376E8CD8B30605E` |
| `code/fast_lib.py` | `327B4F1F48598862D750578DA767B3F290FF8F4B0F35BDE7BB6DE6403143D4B4` |
| `code/prereg_runner.py` (bản sao vòng 1, không sửa) | `14396CB161CA1983513EBF73997A4F3C6CB9BDC3320D51B9A859A263C41FEE4C` |
| `code/backtest_runner_original.py` (không sửa) | `D8DE6DAB1E8755F255E876D73FD4F949D7D6DFE3D5FBD762297E94BDAE2AAE60` |
| `code/fast_runner.py` (mọi lần chạy F1, F2, F3; `run_config.json`) | `1898D6D96E1A101D8B24502DB0AD1E295FBB9C1B5F0677732C5C4842F07E094F` |
| `code/assemble.py` | `AC5CAA1620059BB0D5BD75E544D943A1392C8EA0C93573C14531FC248DF5793D` |
| `code/make_package.py` (gói cuối, có tham số 6) | `8098EA7B42FBB246E4A2E659795DA0E0940AACD5D04F993A81A536FC86FAF33F` |
| `code/avg_by_date.py` | `30768648BABAADD6ED22AA60CDCFFFA694F05AC748DA63BBDE7452306A42C905` |
| `code/bq_orders.py` | `ABC2F03C0D433C8C2D973BAAD1F18AFA277B65F386C48237ACB8969C62D88C28` |
| `code/orders_check.py` | `270C2546709EB0FC96071B1D238EF85EE2BE9670F06449BC832168CAAE4E665C` |
| `code/features_build.py` | `89CC4E7663C53CAAC5820C3DE60AED91A74F51AE982D1470B41C405E03291A0B` |
| Bản sao DB (sau khi chạy) | `C7A663BEC575BEF7221A2C7B50B229294A7E54CD466FC2DEA476A2F35E13F073` |

### Điểm khác giả định

1. **Giờ chạy Avg.** `transformed_at` của Avg ngày D là 15:10 giờ VN ngày D, không phải 02:00. Nội dung đạt kiểm chứng (phản
   ứng với D-1, không với D). Nhưng nếu Avg chỉ có sau 15:10, backtest dùng Avg sớm hơn mức vận hành thực tế cho phép
   (giới hạn 4 của đăng ký).
2. **Hệ số D của Avg sát ngưỡng** (p = 0,059). Theo luật 5 % thì vẫn đạt.
3. **Dòng đơn chỉ có từ 01/01/2026**, không phải từ 01/12/2025.
   - Cửa sổ 180 ngày của biến khách chỉ đủ từ 30/06.
   - Mốc huấn luyện trước đó và chẩn đoán tháng 6 dùng cửa sổ ngắn hơn.
4. **Avg chỉ có từ 26/02/2026** (giống vòng 2). Đúng luật đăng ký, mốc trước đó để NaN.
   - Lô đầu (mốc 01/06) huấn luyện với các mốc từ 09/03, nên vẫn có Avg.
5. **8,7 % dòng Avg trong kỳ chấm có tuổi > 7 ngày**, do cặp rời khỏi lần chạy hằng ngày. Luật "bản ghi gần nhất trước D"
   không giới hạn tuổi.
6. **Nhóm A.** "Như vòng 1" được hiểu là hạng nhu cầu của app (`volume_tier`, 80 % lượng) trên dữ liệu 01/06–31/08, vì các
   tài liệu của vòng 1 trong repo không ghi định nghĩa riêng.
7. **Chênh dòng đơn và `demand_daily`:** −0,52 % lượng; 0,66 % khóa lệch, chi tiết ở `BAT_THUONG_DONG_DON.xlsx`.
8. **Thứ tự chạy và đóng gói khác kế hoạch**, theo hai lần điều chỉnh vận hành của người dùng (13:54 và 17:25): F1 → F3 →
   F2, với 3 gói tạm thay cho 1.
9. **F2 lô 11 chậm bất thường** (10.535 s), do máy thiếu RAM. Chỉ thời gian bị ảnh hưởng.
10. **F4 đã hủy** theo quyết định của chủ dự án (23:42), trước khi chạy. Gói cuối chỉ có F1, F2, F3; không có
    `feature_gain_F4.csv`.
11. **`make_package.py` được thêm tham số tùy chọn** để ghi trạng thái F4 vào MANIFEST. Không phải sửa lỗi; logic đóng
    gói và đối soát không đổi.

## 2. PREREGISTRATION.md

Nguồn: `reports\backtest-prereg-fast-20261028\PREREGISTRATION.md` (worktree MAIN). Bản đăng ký trước giữ nguyên từng byte: [PREREGISTRATION.md](../../_luu_tru/dang_ky_truoc/backtest-prereg-fast-20261028/PREREGISTRATION.md), SHA-256 `41CC3A6C1B9EF09F76BD39D30330911D3FC72DEB4F0794F22736D41E72974267` (4657 byte, của bản gốc).

MỤC ĐÍCH: xác nhận, có đăng ký trước, phương án dự báo ngày D tốt nhất cho từng nhóm SKU (trả lời có/không); kiểm chứng chu kỳ đặt lại của khách có giúp dự báo không.

NỀN: bản sao DB vòng 1 (SHA C7A663BE…F073); lô 7 ngày từ 01/06/2026, ngày dự báo cuối 22/10/2026; seed 7; 12 mốc; 300 vòng; siêu tham số production; trọng số mẫu 3.0 cho horizon <= 7 (như V1); h = 1 chính, h = 2 phụ.

AVG VẬN HÀNH: Avg của ngày D = bản ghi fact_avg_demand_sku_historical có DATE(transformed_at, 'Asia/Ho_Chi_Minh') = D theo SKU x FC (tính 02:00 ngày D bằng dữ liệu đến D-1); không có bản ghi ngày D thì dùng bản ghi gần nhất trước D. Điều kiện dùng: hệ số phản ứng với demand ngày D không có ý nghĩa và hệ số D-1 dương có ý nghĩa; nếu có CSV thì trùng avg_demand_history >= 99% số dòng cùng khóa. Không đạt: mọi biến thể chạy KHÔNG có biến Avg và ghi rõ.

BIẾN MỚI (F1-F4): avg_d (Avg vận hành của mốc dự báo, dùng cho mọi horizon từ mốc), avg_ratio = avg_d / roll_mean_14, avg_age; ratio_7_28 = roll_mean_7 / roll_mean_28; ratio_1_7 = lag_1 / roll_mean_7; ewm_3, ewm_7. Mốc trước 26/02/2026: biến Avg để NaN.

BIẾN THEO KHÁCH (F3, F4): từ dòng đơn đã băm có created_date < mốc dự báo, cửa sổ 180 ngày, theo SKU x FC; một "lần đặt" = tổng lượng của một khách trong một ngày. n_orders_7, n_orders_28, n_customers_7, n_customers_28, avg_order_qty_28, max_order_qty_28, top_customer_share_28, days_since_big_order (lần đặt >= phân vị 90 cỡ lần đặt của SKU x FC trong 180 ngày; 181 nếu không có). Khách đều = >= 3 lần đặt trong 180 ngày và hệ số biến thiên khoảng cách giữa các lần đặt <= 0.5. Với khách đều: r = (số ngày từ lần đặt cuối đến mốc) / (trung vị khoảng cách). n_regular; n_due (r trong [0.8, 1.5]); n_overdue (r trong (1.5, 3]); due_qty, overdue_qty (tổng trung vị cỡ lần đặt của nhóm tương ứng); big_due_qty (due_qty của khách thuộc 10% lớn nhất theo lượng 180 ngày); expected_rate (tổng trung vị cỡ lần đặt / trung vị khoảng cách); min_days_to_due (nhỏ nhất của trung vị khoảng cách - số ngày từ lần đặt cuối; 999 nếu không có); regular_share_90 (tỷ trọng lượng 90 ngày từ khách đều).

CHẨN ĐOÁN KHÁCH HÀNG (chỉ dữ liệu 01/06-31/08, nhóm A): ngày đột biến = thực bán > 2 lần trung vị thực bán ngày mở bán của SKU x FC trong 01/06-31/08. Báo cáo: % lượng hàng nhóm A từ khách đều; % lượng hàng ngày đột biến từ khách đều và từ khách đến hạn (r trong [0.8, 1.5] tính bằng dữ liệu trước ngày đó); cùng chỉ số ở ngày thường.

BIẾN THỂ: R0 = V1 vòng 1 (dùng lại). F1 = V1 + biến mới, Tweedie 1.2. F2 = F1 với objective = l1. F3 = F1 + biến theo khách. F4 = F2 + biến theo khách.
KẾT HỢP (Claude tính): R0, F1-F4 kết hợp với avg_demand_history: w*mô hình + (1-w)*Avg, w thuộc {0.25, 0.5, 0.75}.

CHẤM: như vòng 1 (ngày total_open_hours > 0, làm tròn nửa lên, lệch = tổng |dự báo - thực| / tổng thực, thừa/thiếu = tổng dự báo / tổng thực - 1, nhóm A/B/C theo dữ liệu 01/06-31/08). Chỉ số chính: lệch theo ngày. Phụ: thừa/thiếu, lệch theo tuần.
CHỌN (01/06-31/08, h = 1, từng nhóm): trong {Avg, R0, F1-F4, các bản kết hợp}, phương án có lệch theo ngày thấp nhất trong số phương án có |thừa/thiếu| <= |thừa/thiếu của Avg|. Nếu F3, F4 chưa xong khi chấm lần đầu, chấm lần đầu trên các phương án đã có và chấm lại khi đủ.
XÁC NHẬN (01/09-22/10, h = 1, từng nhóm): phương án được chọn có lệch theo ngày cao hơn Avg và khoảng tin cậy 95% (bootstrap theo SKU x FC) không chứa 0 -> GIỮ Avg; ngược lại -> CHUYỂN.

GIỚI HẠN CÔNG BỐ TRƯỚC: (1) ý tưởng biến Avg, mục tiêu L1, biến theo khách, kết hợp và luật quyết định xuất phát từ phân tích sau khi xem kết quả 01/09-22/10 của vòng 1; (2) dữ liệu lịch sử là bản đã ổn định; (3) h = 1 giả định có tác vụ làm mới dự báo hằng ngày trước 06:00; (4) cần app lấy Avg mỗi ngày sau 02:00, và với F3, F4 cần app lưu dòng đơn đã băm. Quyết định cuối cùng cần chạy song song tối thiểu 2 tuần.

## 3. Kiểm tra dữ liệu (bước 1)

Nguồn: `reports\backtest-prereg-fast-20261028\data_checks.md` (worktree MAIN).

- **Số liệu máy đọc:** `avg_checks.json` (1.1), `orders_checks.json` (1.2, 1.3), `features_checks.json` (1.4).
- **Đọc bản sao DB:** chỉ đọc (`mode=ro&immutable=1`), phạm vi BIGQUERY.

### 1.1 Avg vận hành

**Nguồn.** `avg_history.parquet` chép từ vòng 2. SHA `F12A2A6E…E887`, trùng với bản gốc; không truy vấn lại và không dùng
`avg_for_day` của vòng 2.

**Chất lượng (sheet trong `BAT_THUONG_AVG.xlsx`).**
- 5.505.821 dòng, 26.531 cặp SKU × FC.
- **1 lần chạy mỗi ngày**: 233 ngày từ 26/02 đến 23/10/2026; 231 lần lúc **15:10 giờ VN**, 2 lần khác giờ (26/02 lúc 21:29,
  27/02 lúc 17:23).
- `DATE(transformed_at)` theo giờ VN trùng ngày UTC ở 100 % dòng.
- Không trùng khóa SKU × FC × ngày; mỗi cặp 1 product_id.
- 1.172 avg NULL, 0 âm.
- Thiếu 7 ngày chạy: 28/02, 01/03 → 06/03.
- 5 / 17.140 cặp có demand nhưng không có Avg.

**`avg_by_date.parquet` (luật đăng ký).**
- Luật: bản ghi có ngày VN = D; không có thì bản ghi gần nhất trước D.
- 6.043.252 dòng, ngày 26/02 → 23/10, 1.207 avg NULL (giữ NULL).
- `avg_age` = 0 ở 91,1 % dòng.
- Kỳ chấm 01/06–22/10: 3.717.344 dòng. `avg_age` = 0: 3.371.718 dòng; 1–7 ngày: 22.397; **> 7 ngày: 323.229 (8,7 %)**. Đây là
  các cặp rời khỏi lần chạy hằng ngày; luật không giới hạn tuổi.

**Kiểm chứng điều kiện dùng.**
- Mẫu: 1.354 cặp có trung bình ≥ 20 sp/ngày (trên khoảng hoạt động), 1.330 cặp vào hồi quy, 259.345 quan sát.
- Ngày D: 27/02–22/10, chỉ những ngày mà `avg_d(D)` và `avg_d(D-1)` là bản ghi của chính ngày D và D-1.
- Mô hình: Δavg_d(D) theo demand D, D-1, D-2. Mọi biến đã trừ trung bình theo chuỗi; sai số chuẩn cluster theo SKU × FC.

| Hệ số | Ước lượng | SE | t | p |
|---|---|---|---|---|
| demand **D** | −0,00682 | 0,00362 | −1,89 | **0,059** |
| demand **D-1** | **+0,05981** | 0,01085 | 5,52 | **3,5e-8** |
| demand D-2 | 0,00553 | 0,00455 | 1,22 | 0,22 |

- Hệ số D **không có ý nghĩa** ở mức 5 % (p = 0,059, sát ngưỡng).
- Hệ số D-1 **dương và có ý nghĩa**.
- Chưa so CSV: không có thư mục CSV.
- **→ ĐẠT, mọi biến thể dùng biến Avg.**

**Khác giả định.** Đăng ký ghi "tính 02:00 ngày D", nhưng `transformed_at` của bản ghi ngày D là **15:10 giờ VN ngày D**.
- Nội dung bản ghi phù hợp với "dữ liệu đến D-1": phản ứng với demand D-1, không phản ứng với D.
- Nếu Avg thật sự chỉ có sau 15:10 thì lúc 06:00 ngày D chưa có bản ghi ngày D để dùng. Khi đó backtest dùng Avg sớm hơn
  vận hành thực tế.
- Cần app hoặc nguồn xác nhận Avg có sẵn trước 06:00 (giới hạn 4 của đăng ký).

**Rò rỉ.**
- T6: bản ghi của các ngày > D bị đổi hoặc thêm mới, `avg_d(D)` không đổi.
- T7: đổi bản ghi ngày D thì `avg_d(D)` đổi.
- Thử trên 3 ngày (03/06, 15/08, 22/10): **6 / 6 đạt**.

### 1.2 Dòng đơn đã băm

**Truy vấn.**
- Đúng SQL đăng ký; `@salt` là tham số truy vấn lấy từ biến môi trường, giá trị không ghi ở đâu.
- Dry run 655.059.161 byte, dưới trần 3 GB. Chạy thật: tính phí 655.360.000 byte; job `d798d841-10cd-4fce-9c2a-ea32edc3fd1d`;
  891 s.
- **8.993.350 dòng** → `order_lines.parquet`. File chỉ nằm trong thư mục làm việc, không đóng gói.

**Nội dung.**
- Ngày **01/01 → 22/10/2026**. Truy vấn yêu cầu từ 01/12/2025, nhưng bảng không có dòng nào trước 01/01/2026.
- 35.111 khách, 977.826 đơn.
- 0 mã khách NULL; 18 so_code NULL, đều là đơn WAIT_TO_CONFIRM.
- 0 lượng NULL, âm hay bằng 0.
- Trạng thái: COMPLETED 8.775.265; DELIVERED 216.330; các trạng thái khác 1.755.

**Đối soát với `demand_daily`.** So tổng `demand_quantity` theo SKU × FC × ngày, mọi dòng, 01/01–22/10.

| Mục | Số |
|---|---|
| Khóa (hợp) | 1.368.287 |
| Khớp tuyệt đối | **1.359.259 (99,34 %)** |
| Có cả hai bên nhưng lệch số lượng | 515 |
| Chỉ có dòng đơn | 840 |
| Chỉ có `demand_daily` | 7.673 |
| Tổng lượng: dòng đơn / `demand_daily` | 42.075.843 / 42.294.439 (−0,52 %) |
| Lượng nằm trên khóa khớp | 99,13 % |

- **Khớp ≥ 99 %, nên không đánh dấu "dữ liệu đơn chưa khớp".**
- Các khóa lệch nằm trong `BAT_THUONG_DONG_DON.xlsx`, sheet `lech_theo_khoa` (không có cột mã băm).
- Nguyên nhân có thể của phần lệch (chưa kiểm chứng):
  - dữ liệu nguồn thay đổi giữa ngày bản sao DB được tải (23/10) và ngày truy vấn (27/10);
  - quy tắc giữ / loại dòng trùng của app.

**Lần đặt.** 8.740.623 lần đặt (khách × ngày × SKU × FC) → `placements.parquet`, chỉ trong thư mục làm việc.
- 8.733.803 lần đặt thuộc 17.140 chuỗi demand.
- 6.820 lần đặt thuộc cặp SKU × FC không có trong demand, nên không có biến.

### 1.3 Chẩn đoán khách hàng

Xem `chan_doan_khach_hang.md`.

### 1.4 Bảng biến

**Biến theo khách.** `features_customer.parquet`: 5.073.440 dòng = 17.140 SKU × FC × 296 ngày (01/01–23/10), 17 biến. Bảng
không chứa mã khách ở dạng nào.
- Thời gian tính 1.615 s.
- Runner đọc cùng giá trị từ `features_customer_cube.npy`. Chạy thử đã so khớp với tính trực tiếp ở 01/06 và 30/09.

**Biến mới (Avg, xu hướng).** Tính trong runner từ panel của app tại mỗi mốc (`code/fast_lib.py`). Danh sách và công thức ở
`feature_list.csv`.

**Rò rỉ mức biến**, thử trên 3 ngày (03/06, 15/08, 22/10):
- T8: lần đặt từ D trở đi bị đổi lượng, cộng 2.000 lần đặt giả, biến của D giống hệt.
- T9 (đối chứng âm): đổi lần đặt D-1 thì 3.128–5.070 chuỗi đổi biến.
- **6 / 6 đạt.**

**Giới hạn.** Vì dòng đơn bắt đầu 01/01/2026, cửa sổ 180 ngày chỉ đủ từ 30/06/2026. Mốc huấn luyện sớm nhất là 09/03, và các
mốc trước 30/06 dùng cửa sổ ngắn hơn.

## 4. Kiểm tra rò rỉ

Nguồn: `reports\backtest-prereg-fast-20261028\leakage_summary.md` (worktree MAIN).

### Theo lô và theo ngày (checkpoint của mỗi biến thể)

- Lô: dữ liệu, panel và nhãn huấn luyện đều kết thúc trước mốc lô.
- Ngày D: dữ liệu và panel kết thúc trước D; mốc của biến mới là D. Avg của chính ngày D được phép theo đăng ký.

| Biến thể | Đạt / tổng |
|---|---|
| F1 | 165 / 165 |
| F2 | 165 / 165 |
| F3 | 165 / 165 |

### Thực nghiệm (chạy thử, mốc 01/06, ngày 03/06)

- T1–T3 của runner cũ (cấu hình gốc): ĐẠT (3 kiểm tra).
- Kiểm tra pipeline F3 (biến Avg, xu hướng và khách; cùng model cho các đối chứng âm):
  - T1F: ĐẠT — {"demand_rows_changed": 583814, "placements_changed": 3437538, "avg_records_changed": 3323980, "same_model": true, "same_series": true, "same_forecast": true}
  - T2F_negative_demand_D-1: ĐẠT — {"series_forecast_changed": 4487}
  - T5F_negative_open_hours_D-1: ĐẠT — {"series_forecast_changed": 4505}
  - T7F_negative_avg_of_D: ĐẠT — {"series_forecast_changed": 3863}
  - T8F_negative_placements_D-1: ĐẠT — {"series_forecast_changed": 3600}

### Mức biến (3 ngày: 03/06, 15/08, 22/10)

- T6 / T7, Avg (bản ghi sau D không đổi `avg_d`; đổi bản ghi của D thì đổi): 6 / 6 đạt.
- T8 / T9, biến theo khách (lần đặt từ D trở đi không đổi biến; đổi lần đặt D-1 thì đổi): 6 / 6 đạt.

**Tổng: 515 / 515 kiểm tra đạt.**

## 5. Chẩn đoán khách hàng (bước 1.3, đúng định nghĩa đăng ký)

Nguồn: `reports\backtest-prereg-fast-20261028\chan_doan_khach_hang.md` (worktree MAIN).

- **Script:** `code/orders_check.py`. **Số liệu máy đọc:** `orders_checks.json` (mục `group_A`, `spike_days`, `diagnostic`).
- **Dữ liệu:** dòng đơn đã băm (`order_lines.parquet`, chỉ lưu trong thư mục làm việc), demand của bản sao DB, và bảng giờ mở
  bán đã đăng ký ở vòng 1 (`reports\backtest-prereg-v2-20261027\openhours.parquet`). Chỉ dùng dữ liệu 01/06–31/08/2026.

### Định nghĩa đã dùng

| Khái niệm | Định nghĩa |
|---|---|
| Lần đặt | tổng lượng của một khách trong một ngày cho một SKU × FC; 8.740.623 lần đặt từ 8.993.350 dòng (mọi dòng đều có mã khách) |
| Nhóm A | luật hạng nhu cầu của app (`demand_patterns.volume_tier`, ngưỡng 80 %) trên demand 01/06–31/08: các SKU × FC lớn nhất cho đến chuỗi làm tổng đạt 80 %. Kết quả: **1.170 / 15.131** chuỗi có demand, chiếm 80,01 % lượng. |
| Ngày mở bán | `hours > 0` trong bảng giờ mở bán đăng ký; ngày mở bán không có đơn thì thực bán = 0 |
| Ngày đột biến | thực bán > 2 × trung vị thực bán các ngày mở bán của SKU × FC trong 01/06–31/08. Có 15.762 trên 95.309 ngày có demand của nhóm A. |
| Khách đều tại ngày d | ≥ 3 lần đặt trong 180 ngày trước d (d-180 → d-1) và hệ số biến thiên khoảng cách (độ lệch chuẩn ddof 0 / trung bình) ≤ 0,5 |
| Khách đến hạn tại ngày d | khách đều có r = (d − lần đặt cuối) / trung vị khoảng cách trong [0,8; 1,5]; chỉ dùng dữ liệu trước d |
| Mẫu số | lượng của các lần đặt của nhóm A trong 01/06–31/08 (9.864.222 sp), xét trạng thái khách tại chính ngày đặt |

### Kết quả

| Phạm vi | Lượng hàng | Số lần đặt | % lượng từ khách đều | % lượng từ khách đến hạn |
|---|---|---|---|---|
| **Toàn bộ nhóm A** | 9.864.222 | 1.843.125 | **13,2 %** | 3,9 % |
| **Ngày đột biến** | 3.726.239 | 350.658 | **9,5 %** | **2,5 %** |
| Ngày thường | 6.137.983 | 1.492.467 | 15,4 % | 4,7 % |

**Đọc kết quả.**
- Khách đều chỉ đóng góp 13,2 % lượng hàng nhóm A.
- Ở ngày đột biến, tỷ trọng từ khách đều (9,5 %) và từ khách đến hạn (2,5 %) **thấp hơn** ngày thường (15,4 % và 4,7 %).
- Theo định nghĩa đã đăng ký, chu kỳ đặt lại của khách đều **không giải thích được phần lớn lượng hàng ngày đột biến**:
  khoảng 90 % lượng của ngày đột biến đến từ khách không đều.
- Đây là mô tả, không phải kiểm định. Biến thể F3, F4 kiểm chứng tác dụng thực tế lên dự báo.

### Giới hạn

- **Dòng đơn chỉ có từ 01/01/2026.** Truy vấn yêu cầu từ 01/12/2025, nhưng bảng không có dòng nào trước 01/01/2026. Vì vậy
  cửa sổ 180 ngày chỉ đủ từ khoảng 30/06/2026. Với các ngày 01/06–29/06, "khách đều" được xét trên ít hơn 180 ngày, nên tỷ
  trọng khách đều ở đầu kỳ có thể bị đánh giá thấp.
- **Mẫu số là lượng của lần đặt**, tức tổng `demand_quantity` của dòng đơn. Lượng này khớp với demand 99,34 % theo khóa
  (`data_checks.md`).

### CHU_KY_KHACH_HANG.xlsx

**Phạm vi:** 50 SKU × FC nhóm A có lượng lớn nhất trong 01/06–31/08. Với mỗi SKU × FC, liệt kê mọi khách đều tại 01/09/2026
(dữ liệu 05/03–31/08), tổng cộng **49.650 dòng**.

**Các cột của mỗi khách:**
- 8 ký tự đầu của mã băm;
- số lần đặt trong 180 ngày;
- trung vị khoảng cách;
- hệ số biến thiên;
- trung vị cỡ lần đặt;
- tỷ trọng lượng của khách trong SKU × FC (cùng 180 ngày).

File không chứa mã khách gốc hay mã băm đầy đủ.

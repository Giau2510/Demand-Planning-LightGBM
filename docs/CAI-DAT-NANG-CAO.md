# Cài đặt nâng cao và các nút ghi có chốt (bản 1.4.15)

Tài liệu cho người dùng ứng dụng Demand Forecasting. Bản 1.4.15 đang chuẩn bị, CHƯA cài. Tại thời điểm viết: phần máy chủ
đã viết xong và đã viết test (`backend/tests/test_v1415_*.py`), nhưng test CHƯA chạy; con số kết quả test sẽ được điều
phối bổ sung sau. Mục nào ghi "đã viết test" nghĩa là có test, chưa có nghĩa là đã kiểm đạt.

## 1. Chốt chung của mọi nút ghi

Mọi nút làm thay đổi cài đặt hoặc dữ liệu đều đi qua các bước giống nhau:

1. **Xem trước** (không ghi gì): cho biết giá trị cũ → mới, số dòng bị ảnh hưởng, việc gì sẽ xảy ra.
2. **Gõ chữ xác nhận của hôm nay** (ngày Việt Nam, dạng `...-YYYY-MM-DD`) và **lý do từ 10 đến 500 ký tự**. Chữ sai, thiếu
   hoặc của ngày hôm qua thì bị từ chối, không ghi gì.
3. **Kiểm lại lúc lưu**: nếu sau lúc xem trước có người / tiến trình khác đổi giá trị (hoặc dữ liệu), lệnh bị từ chối
   (`SETTINGS_CHANGED_ELSEWHERE` hoặc "mã kiểm tra không khớp"); hãy tải lại và xem trước lại.
4. **Chốt bận**: không ghi khi đang có việc chạy hoặc chờ chạy lại (D-1, làm mới dự báo, học, xuất Excel, đột biến...),
   và không ghi trong khung giờ vận hành **23:45–00:15** và **00:45–03:45** (giờ Việt Nam). Các nút sửa dữ liệu (nhả dòng
   bị giữ, đọc lại giờ mở bán, quay lại lần đồng bộ) còn chặn thêm: 60 phút trước mỗi khung trên, và khi một giờ lịch đã
   lưu (D-1, học, làm mới, xuất Excel, chốt cuối ngày, báo cáo) rơi trong 90 phút tới hoặc 15 phút vừa qua; lỗi ghi rõ
   giờ nào chặn.
5. **Nhật ký (kiểm toán)**: mỗi lần ghi để lại một dòng nhật ký có giá trị cũ / mới, lý do; dùng để hoàn tác.

Bảng chữ xác nhận (đúng như trong mã):

| Việc | Chữ xác nhận |
|---|---|
| Trường rủi ro CAO (HIGH) ở trang Cài đặt nâng cao | `DOI-CAI-DAT-AN-<ngày>` |
| Trường ảnh hưởng mua hàng (PURCHASE) | `DOI-CAI-DAT-ANH-HUONG-MUA-HANG-<ngày>` |
| Chính sách dữ liệu (trường rủi ro cao) | `DOI-CHINH-SACH-DU-LIEU-<ngày>` |
| Nhập cài đặt từ tệp | `NHAP-CAI-DAT-<ngày>` (cộng chữ PURCHASE / HIGH nếu tệp có khóa loại đó) |
| Tắt chế độ chạy thử (đường riêng, có từ trước) | `TAT-CHAY-THU-<ngày>` |
| Nhả dòng bị giữ | `NHA-DONG-GIU-<ngày>` |
| Đọc lại giờ mở bán | `DOC-LAI-GIO-MO-BAN-<ngày>` |
| Quay lại lần đồng bộ | `QUAY-LAI-DONG-BO-<ngày>` |
| Áp dụng bộ cấu hình lgbm-chot | `AP-DUNG-PRESET-LGBM-CHOT-<ngày>` |

## 2. Trang "Cài đặt nâng cao"

Trang này hiện MỌI trường cài đặt không có ô riêng ở các trang khác ("sổ trường"), kèm mô tả tiếng Việt / tiếng Anh và
hậu quả khi đổi. Mỗi trường có một mức rủi ro:

| Mức | Nghĩa | Cần gì để lưu |
|---|---|---|
| LOW | Thấp: không đổi số dự báo hay dữ liệu | Đánh dấu "Tôi hiểu" |
| HIGH | Cao: đổi cách hệ thống chạy | Chữ `DOI-CAI-DAT-AN-<ngày>` + lý do |
| PURCHASE | Ảnh hưởng mua hàng: đổi số dự báo / file mua hàng / dữ liệu học | Chữ `DOI-CAI-DAT-ANH-HUONG-MUA-HANG-<ngày>` + lý do |
| READONLY | Chỉ xem | Không sửa được ở đây |
| OWN_PATH | Có đường riêng | Sửa ở trang riêng của nó |

**Vì sao có trường chỉ đọc (READONLY)**: quy tắc cố định của chủ dự án (ví dụ ngưỡng làm tròn `forecast_used`),
trạng thái do hệ thống tự ghi (ví dụ dấu thời điểm, ảnh chụp cấu trúc bảng nguồn), hoặc bảng / cột nguồn phải đổi ở ô
có nút "Kiểm tra" (quy tắc 19). **OWN_PATH**: công tắc luồng lịch (trang Lịch chạy), chế độ chạy thử, tạm dừng D-0,
kết nối Google / BigQuery: hiện ra để xem, đổi ở nơi riêng có kiểm tra riêng.

Quy tắc thêm: số ngày lưu giữ (retention) chỉ được TĂNG (giảm sẽ xóa dữ liệu cũ, không lấy lại được). Làm sạch đơn đột
biến (`spike_cleaning`, `spike_e4_n`) sửa được ở mức PURCHASE (quyết định chủ dự án 23/11/2026).

**Hoàn tác**: mỗi lần lưu có một dòng trong lịch sử của trang; nút "Hoàn tác" trả lại đúng các khóa của lần đó, chỉ khi
giá trị hiện tại vẫn là giá trị lần đó đã ghi (nếu đã bị đổi tiếp thì từ chối và liệt kê). Hoàn tác cũng cần chữ xác
nhận và lý do như lúc lưu, và không bao giờ giảm số ngày lưu giữ.

Thẻ cài đặt cũ (sửa cả phần) không ghi đè được các trường trong sổ: nếu gửi giá trị khác hiện tại, máy chủ trả
`SETTINGS_FIELD_GUARDED` (đã viết test).

## 3. Năm trường chính sách dữ liệu được bảo vệ

Thẻ "Chính sách đồng bộ lịch sử" (trang Cấu hình) quản lý: `window_start_date` (ngày bắt đầu cửa sổ dữ liệu),
`history_change_policy` (giữ hay bỏ dòng đơn mà nguồn đã bỏ), `history_day_check` (kiểm hằng ngày lịch sử ngoài cửa sổ
D-1), `source_time_travel_hours` (số giờ BigQuery còn giữ phiên bản cũ), `training_start_rule` (quy tắc ngày bắt đầu
học). Nút "Lưu" và "Khôi phục mặc định" của thẻ cũ giữ nguyên các trường này. `history_change_policy` và
`training_start_rule` cần chữ `DOI-CHINH-SACH-DU-LIEU-<ngày>` + lý do; hai trường còn lại cần "Tôi hiểu".

**Vì sao `window_start_date` bị khóa**: giá trị này nằm trong mã cấu hình BigQuery. Đổi nó làm D-1 bị từ chối cho tới khi
"Kiểm tra dữ liệu toàn kỳ" lại, rồi D-1 nạp lại TOÀN BỘ và ghi đè dữ liệu từ ngày mới (có thể thay dữ liệu 2025). Ứng
dụng chưa có cách xem trước một lần nạp lại toàn bộ, nên trường này giữ khóa trong 1.4.15.

**Khi thật sự cần đổi** (nhờ phiên điều phối làm theo quy trình có kiểm soát, không làm bằng tay trên giao diện):

1. Sao lưu CSDL trước.
2. Làm ngoài khung đêm (23:45–00:15, 00:45–03:45) và không có việc nào đang chạy.
3. Đổi giá trị bằng script có kiểm soát.
4. Chạy "Kiểm tra dữ liệu toàn kỳ" (validate BigQuery, chỉ đọc).
5. Chạy D-1.
6. Kiểm số dòng, số khóa, `data-check` trước / sau.
7. Hoàn tác = đặt lại giá trị cũ rồi validate lại (mã cấu hình cũ trở lại).

## 4. Xuất / nhập cài đặt

Dùng để chép cài đặt sang máy mới (ví dụ máy của tech) hoặc giữ một bản để so.

* **Tệp gồm**: các phần cài đặt trong danh sách trắng (chính sách dữ liệu, mô hình, chất lượng, chân trời dự báo, nhập
  Excel, lịch chạy, dự báo hằng ngày, SEL2, một số khóa BigQuery không phải kết nối), mã SHA-256 để phát hiện tệp bị sửa.
  Làm sạch đột biến (`spike_cleaning`, `spike_e4_n`) đi theo tệp như một khóa PURCHASE; tệp cũ không có hai khóa này thì
  máy nhận giữ giá trị của nó.
* **Tệp KHÔNG gồm**: mật khẩu / token / khóa bí mật (không bao giờ nằm trong cài đặt), đăng nhập Google (OAuth), kết nối
  và ánh xạ BigQuery, đường dẫn thư mục, SQL nguồn, công tắc luồng lịch và thời điểm bật, tạm dừng D-0, chế độ chạy thử,
  trạng thái production BigQuery, ảnh chụp cấu trúc bảng, bảng đặc trưng.
* **Nhập**: bước 1 xem trước (không ghi; từ chối cả tệp nếu sai định dạng, sai SHA-256, có khóa lạ, sai kiểu, khóa chỉ
  đọc khác giá trị, `window_start_date` khác); bước 2 tích các phần muốn nhập, gõ `NHAP-CAI-DAT-<ngày>` + lý do (thêm chữ
  PURCHASE / HIGH nếu phần đó có khóa loại này): nhập TẤT CẢ phần đã chọn hoặc KHÔNG phần nào. Có nút "Hoàn tác lần nhập".
  Chạy bằng dòng lệnh: `app.cli settings-export` / `settings-import` (mặc định chỉ xem trước; `--apply` chỉ chủ dự án
  chạy).

## 5. Nút "Nhả dòng bị giữ"

Từ 1.2.13, khi nguồn bỏ một dòng đơn (đơn hủy, chưa xác nhận, đổi phạm vi) mà không chứng minh được là chuyển chỗ, ứng
dụng vẫn GIỮ dòng đó trong số bán đã lưu ("dòng bị giữ"). Nút này là quyết định của chủ dự án: thôi giữ một số dòng.

* **Xem trước**: số dòng, số đơn vị, từng SKU×kho×ngày trước / sau, mã kiểm tra (signature). Chọn theo SKU, khoảng ngày,
  nguyên nhân (chưa chọn theo kho được: hàm sẵn có nhả mọi kho của một SKU).
* **Giới hạn mỗi lần**: tối đa **450 dòng** và **6.000 đơn vị**; vượt thì bị từ chối kèm danh sách nhóm lớn nhất để chọn
  hẹp lại. **Mỗi ngày** (giờ Việt Nam): tối đa **3 lần nhả** và **1.350 dòng**; xem trước cho biết số còn lại.
* **Chữ**: `NHA-DONG-GIU-<ngày>` + lý do.
* **Sao lưu tự động** trước khi ghi. Chốt dung lượng: ổ chứa bản sao lưu phải trống ít nhất **1,5 × (CSDL + WAL + bản zip
  ước tính)** (zip ước tính = cỡ bản sao lưu mới nhất, chưa có thì 15 % CSDL), không dưới 1,5 × (CSDL + WAL); thiếu thì từ
  chối với số cần / có / thiếu. Bản sao lưu không bao giờ bị xóa ở đây; kết quả ghi đường dẫn bản sao lưu.
* **Chạy nền**: trả lời ngay, theo dõi trạng thái; mỗi lúc một lần, và không chạy cùng lúc với "Đọc lại giờ mở bán" hay
  "Quay lại lần đồng bộ" (ba nút này chạy lần lượt); nếu ứng dụng dừng giữa chừng thì lần đó hiện
  "bị ngắt" và không chặn lần sau. Mọi chốt (bận, khung giờ, khóa vận hành, tập dòng đã xem trước) được kiểm lại NGAY
  TRONG giao dịch ghi; sai thì không ghi gì.
* **Lưu ý ngày đã chốt thực tế**: nhả có thể đổi số bán đã lưu của ngày đã chốt thực tế (trong nhật ký chỉ gắn cờ; ảnh
  chụp KPI đã chốt không đổi).
* **Hoàn tác**: kết quả có mã lần đồng bộ (`sync_run_id`, dạng `HRL-...`); dùng nút "Quay lại lần đồng bộ" (mục 7).
  Hậu quả: hoàn tác trả lại số bán đã lưu, KHÔNG trả lại mô hình / số dự báo đã học trên dữ liệu đã đổi.
* Đã viết test (chưa chạy).

## 6. Nút "Đọc lại giờ mở bán"

* **Giải quyết**: các ngày trong cửa sổ dữ liệu CHƯA có dòng giờ mở bán nào; đọc lại số thật từ BigQuery (chỉ đọc, chạy
  thử trước, có trần byte) cho những ngày nguồn đã có số.
* **Không giải quyết**: ngày đã có MỘT PHẦN dữ liệu (không ghi đè, không bổ sung nửa chừng); ngày nguồn không có số (giữ
  MISSING, KHÔNG BAO GIỜ điền 0); không ghi đè giá trị đã lưu (kể cả khi nguồn đổi số); không bao giờ tự điền hay suy
  luận giá trị thay thế.
* **Lưu ý số dự báo**: SEL2 đọc giờ mở bán trực tiếp. Ngày cũ trước đây trống nay có số thật, nên lượt SEL2 kế tiếp có
  thể ra số dự báo khác (kéo theo `forecast_used`), và thực tế theo ngày / KPI của các ngày đó có thể đổi. Nên đo SEL2
  trước / sau trên bản sao CSDL trước khi bấm trên máy thật.
* Mỗi giao dịch ghi chứa trọn ngày; ngày nào có người ghi khác chen vào trong lúc chạy thì bỏ qua cả ngày.
* Tối đa **60 ngày** mỗi lần, trong cửa sổ dữ liệu, tới hôm qua. Chữ `DOC-LAI-GIO-MO-BAN-<ngày>` + lý do. Chạy nền, mỗi
  lúc một việc. Không cần sao lưu (chỉ thêm dòng của ngày còn thiếu). Không đụng mốc đọc của lượt làm mới hằng ngày.
* Hoàn tác: các dòng đã thêm có cùng thời điểm nạp (`loaded_at`) ghi trong kết quả và nhật ký; ứng dụng không có nút xóa
  (xóa dữ liệu luôn chờ chủ dự án duyệt).
* Đã viết test (chưa chạy).

## 7. Nút "Quay lại lần đồng bộ"

* Danh sách 50 lần đồng bộ gần nhất, mỗi lần có cờ "quay lại được": chỉ lần D-1 / nạp bù / nhả dòng đã ghi xong mà MỌI
  dòng của nó vẫn y như lần đó để lại (chưa có lần ghi sau đổi). Lần đã quay lại, lần quay lại, hoặc lần quá lớn (trên
  20.000 dòng thay đổi: khóa ghi bị giữ suốt giao dịch, chưa đo thời gian; sẽ xem lại sau khi đo trên bản sao) thì không.
* Xem trước: số dòng trả lại, đơn vị hiện tại → sau khi quay lại, khoảng ngày, số dòng bị giữ được trả lại.
* Chữ `QUAY-LAI-DONG-BO-<ngày>` + lý do; sao lưu tự động (cùng chốt dung lượng 1,5×); chạy nền; kiểm lại trong giao dịch
  ghi.
* **Hậu quả**: trả lại ĐÚNG số bán lịch sử mà lần đó đã ghi; KHÔNG trả lại mô hình hay số dự báo đã học / đã công bố trên
  dữ liệu đã đổi; học lại hay không do chủ dự án quyết.
* Đã viết test (chưa chạy).

## 8. Bộ cấu hình (preset) lgbm-chot

* Xem trước từng khóa cũ → mới và hai luồng lịch sẽ bật (làm mới dự báo, báo cáo độ chính xác) kèm tình trạng sẵn sàng;
  một luồng chưa sẵn sàng thì từ chối cả lần áp dụng.
* Chữ `AP-DUNG-PRESET-LGBM-CHOT-<ngày>` + lý do, và thêm `DOI-CAI-DAT-ANH-HUONG-MUA-HANG-<ngày>` khi có khóa ảnh hưởng
  mua hàng đổi giá trị. ẢNH HƯỞNG số dự báo / mua hàng.
* Bị từ chối khi bận, trong / gần khung đêm, gần một giờ lịch đã lưu, hoặc khi có khóa vận hành (như các nút ghi khác).
* Bộ cấu hình KHÔNG ghi `log_retention_days` và không bao giờ giảm số ngày lưu giữ (khóa đang cao hơn được giữ).
* Hoàn tác: các khóa sửa được trả lại bằng nút Hoàn tác của trang Cài đặt nâng cao; công tắc luồng tắt lại ở trang Lịch
  chạy; quy tắc cố định (làm tròn) không hoàn tác ở đây.
* Đã viết test (chưa chạy).

## 9. Ước lượng spike-lines

Chỉ ƯỚC LƯỢNG: chạy thử BigQuery cho lần đọc dòng đơn SO của một ngày (số byte ước tính, trần byte). Không đọc dòng,
không ghi gì, không tính tiền; chạy thử không đếm được số dòng. `initial` trên phạm vi đã có dấu đột biến cần `reflag`.
Chạy thật vẫn qua bộ chạy / dòng lệnh (`spike-lines --yes`).

## 10. Tạm dừng D-0

D-0 (số bán trong ngày) chỉ để theo dõi. Từ 1.4.13 có tạm dừng tối đa 6 giờ, tự bật lại (`/api/d0/pause`,
`/api/d0/resume`; hoặc `Tam-dung-D0.bat` / `Bat-lai-D0.bat`). Nút trên giao diện thuộc lô giao diện 1.4.15 (chưa kiểm khi
viết tài liệu này).

## 11. Việc HOÃN và lý do

| Việc | Lý do hoãn |
|---|---|
| #16 `sel2-bootstrap` từ giao diện | Học nhiều ngày + đọc BigQuery + chạy lâu; ứng dụng không giữ khóa việc nặng (HEAVY_LOCK) nên có thể chồng việc nặng. Chạy qua dòng lệnh / bộ chạy như hiện nay. |
| #21 `history-check` | Không chỉ đọc: ghi bảng kiểm ngày và chạy truy vấn BigQuery trên toàn lịch sử. |
| #21 `sel2-avg-read` | Ghi bảng Avg Demand khi chạy thật. |
| #21 `sel2-replay` | Ghi lượt học / ứng viên; chỉ chạy trên bản sao CSDL. |
| #21 `sel2-published-backfill` | Ghi tệp lịch sử của ngày đã xuất; không có hoàn tác / giới hạn. |
| #21 `attest-training-data` | Ghi dấu dữ liệu của lượt học cũ; không hoàn tác. |
| #21 `history-reconcile` | Ghi lần công bố còn thiếu vào lịch sử dự báo; không hoàn tác. |
| #21 `actual-finalize` | Chốt (đóng băng) thực tế của ngày đã xong; không mở lại được. |
| #21 `eod-retention` | Xóa dữ liệu; xóa luôn chờ chủ dự án duyệt. |
| #21 `product-names-refresh` | Đọc BigQuery và ghi đè tên sản phẩm; không hoàn tác. |
| #21 `spike-lines` chạy thật | Đọc BigQuery + ghi bộ nhớ đệm dòng SO và dấu đột biến; giữ qua bộ chạy (chỉ có nút ước lượng). |
| Mở khóa `window_start_date` | Chưa có xem trước cho lần nạp lại toàn bộ (mục 3). |
| Khóa vận hành trên máy không đặt biến `DF_OPS_LOCK` / `DF_HEAVY_LOCK` / `DF_RUN_DIR` và không có thư mục `run` cạnh thư mục dữ liệu (ví dụ server của tech) | Không biến nào được đặt thì ứng dụng dùng thư mục `run` suy ra từ thư mục dữ liệu (hai cấp trên + `run`) nếu có (`ops_lock_source: "derived"`); không có thì không kiểm được: xem trước báo `ops_lock_checked: false` để giao diện hiện dòng "khóa vận hành không được kiểm trên máy này". |
| Hoàn tác cho thẻ cài đặt cũ | Thẻ cũ không có nhật ký từng khóa; dùng trang Cài đặt nâng cao. |

## 12. Lưu ý bảo mật

* Ứng dụng KHÔNG có đăng nhập: ai mở được ứng dụng là bấm được các nút ghi. Chữ xác nhận và lý do chỉ chống bấm nhầm,
  không thay cho đăng nhập. Không chia sẻ đường dẫn có quyền ghi.
* Agent (Claude Code và các agent khác) KHÔNG gọi API ghi cài đặt / dữ liệu trên ứng dụng hoặc CSDL thật
  (`POST /api/settings-advanced/{apply,undo}`, `POST /api/settings-import/{apply,undo}` và `settings-import --apply`,
  `POST /api/held-lines/release`, `POST /api/open-hours-reread`, `POST /api/sync-rollback`,
  `POST /api/presets/{name}/apply`); chỉ chạy thử trên CSDL giả, tách biệt hồ sơ và cổng (CLAUDE.md, mục "Claude Code
  và quy trình").
* Tệp xuất cài đặt không chứa bí mật; báo cáo chỉ ghi mã, số đếm, mã băm.

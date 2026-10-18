"""Bilingual message catalogue for codes produced by the backend (validation, jobs, alerts, errors)."""
from __future__ import annotations

CATALOG: dict[str, tuple[str, str]] = {
    # --- row validation
    "MISSING_SKU": ("Thiếu mã SKU — dòng bị loại.", "SKU is missing — row excluded."),
    "MISSING_FC": ("Thiếu mã FC/kho — dòng bị loại.", "FC/warehouse is missing — row excluded."),
    "INVALID_DATETIME": ("Thời điểm tạo đơn không hợp lệ (dùng YYYY-MM-DD HH:MM hoặc DD/MM/YYYY HH:MM) — dòng bị loại.",
                         "Invalid order timestamp (use YYYY-MM-DD HH:MM or DD/MM/YYYY HH:MM) — row excluded."),
    "INVALID_DATE": ("Ngày đặt hàng không hợp lệ — dòng bị loại.", "Invalid order date — row excluded."),
    "MISSING_DATE": ("Thiếu cả created_at và order_date — dòng bị loại.", "Both created_at and order_date are missing — row excluded."),
    "ORDER_DATE_MISMATCH": ("order_date khác ngày của created_at (giờ VN); dùng order_date đã cung cấp.",
                            "order_date differs from created_at's Vietnam date; the provided order_date is used."),
    "FUTURE_DATE": ("Ngày đặt hàng ở tương lai — dòng bị loại (tránh rò rỉ dữ liệu).", "Order date is in the future — row excluded (prevents leakage)."),
    "OUT_OF_RANGE_DATE": ("Ngày nằm ngoài phạm vi thời gian được cấu hình — dòng bị loại.", "Date is before the configured minimum date — row excluded."),
    "MISSING_QTY": ("Thiếu số lượng đặt — dòng bị loại.", "Order quantity is missing — row excluded."),
    "INVALID_QTY": ("Số lượng không phải là số — dòng bị loại.", "Order quantity is not a number — row excluded."),
    "NEGATIVE_QTY": ("Số lượng âm — dòng bị loại.", "Negative order quantity — row excluded."),
    "ZERO_QTY": ("Số lượng bằng 0 (hợp lệ, được giữ lại).", "Quantity is zero (valid, kept)."),
    "INVALID_NUMBER_BLANKED": ("Giá trị số không hợp lệ — ô này được để trống, dòng vẫn được giữ.", "Invalid number — this cell was blanked, row kept."),
    "NEGATIVE_VALUE_BLANKED": ("Giá trị âm — ô này được để trống, dòng vẫn được giữ.", "Negative value — this cell was blanked, row kept."),
    "INVALID_FLAG_BLANKED": ("Cờ không hợp lệ (dùng 1/0, TRUE/FALSE, Y/N) — ô được để trống.", "Invalid flag (use 1/0, TRUE/FALSE, Y/N) — cell blanked."),
    "INVALID_DATETIME_BLANKED": ("Thời điểm cập nhật nguồn không hợp lệ — ô được để trống.", "Invalid source update time — cell blanked."),
    "UPDATED_BEFORE_CREATED": ("Thời điểm cập nhật sớm hơn thời điểm tạo đơn.", "Source update time is earlier than creation time."),
    "LATE_ARRIVING": ("Dữ liệu đến muộn (cập nhật > 2 ngày sau khi tạo đơn).", "Late-arriving data (updated > 2 days after creation)."),
    "DISCOUNT_GT_LINE_VALUE": ("Giảm giá lớn hơn giá trị dòng — cần kiểm tra.", "Discount exceeds the line value — please check."),
    "PRICE_OUTLIER": ("Giá bất thường so với trung vị của SKU.", "Price is unusual compared to the SKU median."),
    "EXACT_DUPLICATE": ("Dòng trùng hoàn toàn với dòng trước — chỉ tính một lần.", "Exact duplicate of an earlier row — counted once."),
    "GRAIN_CONFLICT": ("Cùng đơn × SKU × FC xuất hiện nhiều lần với giá trị khác nhau — các dòng này bị loại (chính sách ERROR).",
                       "Same order × SKU × FC appears several times with different values — rows excluded (ERROR policy)."),
    "GRAIN_MULTI_LINE_SUMMED": ("Cùng đơn × SKU × FC có nhiều dòng chi tiết — được cộng dồn (chính sách SUM).",
                                "Same order × SKU × FC has several detail lines — summed (SUM policy)."),
    # --- dataset quality
    "MISSING_CALENDAR_DAYS": ("Có ngày không có bất kỳ đơn hàng nào trong toàn bộ dữ liệu — có thể thiếu dữ liệu.",
                              "Some calendar days have no orders at all — data may be missing."),
    "SHORT_HISTORY": ("Lịch sử ngắn hơn 2 năm mục tiêu.", "History is shorter than the 2-year target."),
    "INSUFFICIENT_HISTORY": ("Lịch sử quá ngắn để huấn luyện LightGBM.", "History is too short to train LightGBM."),
    "NEW_SKUS": ("Có SKU mới (xuất hiện trong 14 ngày gần nhất).", "New SKUs (first seen in the last 14 days)."),
    "NEW_FCS": ("Có FC mới (xuất hiện trong 14 ngày gần nhất).", "New FCs (first seen in the last 14 days)."),
    "SHORT_SERIES": ("Có tổ hợp SKU × FC ít lịch sử — sẽ dùng phương pháp dự phòng.", "Some SKU × FC series have little history — fallback will be used."),
    "INTERMITTENT_SERIES": ("Có tổ hợp nhu cầu gián đoạn — sẽ dùng phương pháp dự phòng.", "Some series have intermittent demand — fallback will be used."),
    "INACTIVE_SERIES": ("Có tổ hợp không có đơn trong thời gian dài — dự báo 0.", "Some series had no orders for a long time — forecast 0."),
    "STALE_DATA": ("Dữ liệu cũ: ngày dữ liệu mới nhất quá xa so với hôm nay.", "Stale data: the latest data date is too far behind today."),
    "NO_DATA": ("Không có dữ liệu cho phạm vi đã chọn.", "No data for the selected scope."),
    "SCHEMA_DRIFT": ("Schema bảng nguồn đã thay đổi so với lần ánh xạ.", "The source table schema changed since mapping."),
    "ZERO_DEMAND_DAYS": ("Nhiều ngày nhu cầu bằng 0 (hợp lệ).", "Many zero-demand days (valid)."),
    # --- import
    "NOT_XLSX": ("Chỉ chấp nhận file Excel .xlsx (không hỗ trợ CSV, .xls, .xlsm).", "Only .xlsx Excel files are accepted (no CSV, .xls, .xlsm)."),
    "FILE_TOO_LARGE": ("File vượt quá dung lượng cho phép.", "File exceeds the size limit."),
    "CORRUPT_FILE": ("Không đọc được file Excel (file hỏng hoặc không phải .xlsx).", "Cannot read the Excel file (corrupt or not .xlsx)."),
    "MACRO_NOT_ALLOWED": ("File chứa macro — không được chấp nhận.", "File contains macros — not accepted."),
    "EMPTY_FILE": ("File/sheet không có dữ liệu.", "The file/sheet has no data."),
    "SHEET_NOT_FOUND": ("Không tìm thấy sheet dữ liệu. Hãy chọn sheet chứa dữ liệu (mẫu dùng sheet 'Data').",
                        "Data sheet not found. Select the sheet containing data (the template uses 'Data')."),
    "MISSING_REQUIRED_COLUMNS": ("Thiếu cột bắt buộc. Hãy ánh xạ cột cho các trường bắt buộc.", "Required columns missing. Map a column to every required field."),
    "TOO_MANY_ROWS": ("Số dòng vượt giới hạn cấu hình.", "Row count exceeds the configured limit."),
    "NO_VALID_ROWS": ("Không có dòng hợp lệ nào để lưu.", "There are no valid rows to save."),
    "ROW_ERRORS_NOT_ACKNOWLEDGED": ("Có dòng lỗi. Hãy xác nhận rằng các dòng lỗi sẽ bị loại trước khi lưu.",
                                    "Some rows have errors. Confirm that error rows will be excluded before saving."),
    "BATCH_NOT_PENDING": ("Lô không ở trạng thái chờ xác nhận.", "Batch is not pending review."),
    "BATCH_NOT_FOUND": ("Không tìm thấy lô import.", "Import batch not found."),
    "REPLACE_TARGET_INVALID": ("Lô cần thay thế không tồn tại hoặc không còn hoạt động.", "The batch to replace does not exist or is not active."),
    "CONFIRMATION_MISMATCH": ("Mã xác nhận không khớp.", "Confirmation text does not match."),
    "DUPLICATE_COLUMN_MAPPING": ("Một cột nguồn được ánh xạ cho nhiều trường.", "One source column is mapped to several fields."),
    # --- training / publish
    "TRAINING_ACCEPTED": ("Model đạt ngưỡng chất lượng và đã được chấp nhận.", "Model passed the quality gate and was accepted."),
    "QUALITY_GATE_FAILED": ("Model mới không đạt ngưỡng chất lượng và chính sách đang là CHẶN (BLOCK) — không publish; giữ forecast đã publish trước đó.",
                            "New model failed the quality gate and the policy is BLOCK — not published; the previous published forecast is kept."),
    "FORECAST_PUBLISHED_WITH_WARNING": ("Đã publish forecast mới KÈM CẢNH BÁO: chất lượng dưới ngưỡng đã cấu hình và/hoặc độ tin cậy đánh giá thấp. "
                                        "Theo chính sách đã duyệt, dữ liệu thật vẫn được dùng; xem chi tiết ở trang Hiệu năng model.",
                                        "New forecast published WITH A WARNING: quality below the configured thresholds and/or low evaluation "
                                        "confidence. Under the approved policy the real data is still used; see Model performance for details."),
    "NO_FORECAST_FOR_ACTIVE_SOURCE": ("Chưa có forecast nào từ nguồn dữ liệu đang dùng. Các lần forecast của nguồn khác (vd. DEMO) không được hiển thị như kết quả hiện tại.",
                                      "No forecast from the active data source yet. Runs of another source (e.g. DEMO) are never shown as the current result."),
    "TRAINING_FAILED": ("Huấn luyện thất bại — giữ model và forecast hợp lệ trước đó.", "Training failed — previous valid model and forecast kept."),
    "DATA_NOT_TRAINABLE": ("Dữ liệu không đủ điều kiện huấn luyện.", "Data is not eligible for training."),
    "STALE_DATA_BLOCKED": ("Dữ liệu cũ — không publish forecast mới.", "Data is stale — new forecast not published."),
    "NO_NEW_DATA": ("Dữ liệu không thay đổi kể từ lần huấn luyện được chấp nhận gần nhất — bỏ qua.", "Data unchanged since the last accepted training — skipped."),
    "PUBLISH_FAILED": ("Huấn luyện xong nhưng bước publish thất bại — không có forecast mới; forecast hợp lệ trước đó được giữ.",
                       "Training finished but publishing failed — no new forecast; the previous valid forecast is kept."),
    "FORECAST_EXTENDED": ("Đã tạo forecast bổ sung từ cùng mô hình đã chấp nhận (không huấn luyện lại).",
                          "Additional forecast created from the same accepted model (no retraining)."),
    "NOTHING_TO_EXTEND": ("Run này đã có đủ các khoảng dự báo đang cấu hình.", "This run already covers the configured periods."),
    "MODEL_ARTIFACT_MISSING": ("Không dùng lại được mô hình của run này (file mô hình thiếu/khác). Hãy chạy Huấn luyện & dự báo.",
                               "The model of this run cannot be reused (file missing/changed). Run Train & forecast."),
    "DATA_CHANGED_SINCE_TRAINING": ("Dữ liệu đã thay đổi sau khi mô hình này được huấn luyện — không thể tạo thêm từ mô hình cũ. Hãy chạy Huấn luyện & dự báo.",
                                    "The data changed after this model was trained — cannot extend from the old model. Run Train & forecast."),
    "REPRODUCTION_MISMATCH": ("Không tái tạo được đúng các giá trị đã publish — từ chối tạo forecast bổ sung.",
                              "Published values could not be reproduced exactly — extension refused."),
    "NOT_LIGHTGBM": ("Dòng này không dùng LightGBM (phương pháp dự phòng) nên không có SHAP.", "This row does not use LightGBM (fallback method), so it has no SHAP values."),
    "UNKNOWN_FEATURE": ("Mô hình không có feature này.", "The model has no such feature."),
    "TRACE_TOO_LARGE": ("Trace TreeSHAP vượt giới hạn kích thước an toàn.", "The TreeSHAP trace exceeds the safety size limit."),
    "TRACE_TIMEOUT": ("Tính trace TreeSHAP vượt giới hạn thời gian.", "Computing the TreeSHAP trace exceeded the time limit."),
    "UNSUPPORTED_MODEL": ("Định dạng mô hình không được bộ trace hỗ trợ.", "Model format not supported by the trace engine."),
    "FORECAST_PUBLISHED":("Đã publish forecast mới.", "New forecast published."),
    "FORECAST_HISTORY_CAPTURE_FAILED": ("Forecast đã publish nhưng chưa ghi được vào Lịch sử Forecast & Thực tế. Forecast không bị ảnh hưởng; "
                                        "lịch sử sẽ được ghi lại tự động ở lần publish sau, khi khởi động lại ứng dụng, hoặc bằng lệnh "
                                        "'python -m app.cli history-reconcile'.",
                                        "The forecast was published but could not be recorded in the Forecast & actual history yet. The "
                                        "forecast is not affected; the history is recorded automatically at the next publish, at the next app "
                                        "start, or with 'python -m app.cli history-reconcile'."),
    "HISTORY_EXPORT_TOO_LARGE": ("Bộ lọc hiện tại có quá nhiều dòng cho một file Excel (tối đa 1.000.000 dòng). Hãy thu hẹp khoảng ngày, "
                                 "FC hoặc SKU rồi xuất lại — file không bao giờ bị cắt bớt.",
                                 "The current filter has too many rows for one Excel file (at most 1,000,000). Narrow the dates, FC or "
                                 "SKU and export again — the file is never truncated."),
    # --- 1.2.6 end-of-day forecast backup and actual close
    "EOD_SNAPSHOT_INCOMPLETE": ("Snapshot forecast cuối ngày KHÔNG đầy đủ: phiên forecast hợp lệ mới nhất không bao phủ đủ 7 ngày "
                                "kế tiếp cho mọi SKU × FC. Không lưu giá trị nào và snapshot này không được dùng làm dự phòng.",
                                "The end-of-day forecast snapshot is NOT complete: the newest valid forecast session does not cover "
                                "the next 7 days for every SKU × FC. No value was stored and this snapshot is never used as backup."),
    "EOD_NO_VALID_FORECAST": ("Không có phiên forecast hợp lệ nào cho bộ dữ liệu đang dùng — không tạo snapshot forecast cuối ngày "
                              "(không dùng dữ liệu demo, không điền 0).",
                              "There is no valid forecast session for the active dataset — no end-of-day forecast snapshot was "
                              "made (no demo data, no zeros)."),
    "EOD_SNAPSHOT_VERIFY_FAILED": ("Bản sao snapshot cuối ngày không khớp forecast nguồn (số dòng hoặc tổng) — không lưu gì. Job "
                                   "dừng ở trạng thái FAILED, không tự thử lại; chạy lại bằng tay sau khi kiểm tra.",
                                   "The end-of-day snapshot copy does not match its source forecast (rows or total) — nothing was "
                                   "stored. The job ends FAILED and is not retried automatically; run it again by hand after "
                                   "checking."),
    "EOD_RETENTION_PLAN_CHANGED": ("Kế hoạch dọn snapshot đã thay đổi so với bản dry run được duyệt — không xóa gì. Chạy dry run lại "
                                   "và duyệt kế hoạch mới.",
                                   "The snapshot clean-up plan changed since the reviewed dry run — nothing was deleted. Run the "
                                   "dry run again and review the new plan."),
    "EOD_RETENTION_SCHEMA": ("Database chưa ở schema 6 (1.2.6) — chưa thể dọn snapshot cuối ngày.",
                             "The database is not at schema 6 (1.2.6) yet — end-of-day snapshots cannot be cleaned up."),
    "EOD_RETENTION_UNKNOWN_REFERENCE": ("Có bảng khác tham chiếu snapshot cuối ngày — không xóa gì cho tới khi quan hệ này được "
                                        "xem xét.",
                                        "Another table references the end-of-day snapshots — nothing is deleted until that "
                                        "reference is reviewed."),
    "EOD_RETENTION_FAILED": ("Dọn snapshot cuối ngày dừng giữa chừng: snapshot lỗi được hoàn tác, các snapshot đã xóa trước đó "
                             "được ghi nhận. Xem chi tiết lỗi và bản backup trước khi chạy lại.",
                             "The end-of-day snapshot clean-up stopped: the failing snapshot was rolled back, the ones deleted "
                             "before it are recorded. Check the error and the backup before running it again."),
    "ACTUAL_CLOSE_NO_DATA": ("Chốt thực tế cuối ngày: ngày này chưa có dữ liệu thực tế (không có D-1 và không có snapshot D0) — đã ghi "
                             "nhận 'không có dữ liệu', không coi là 0.",
                             "End-of-day actual close: this day has no actual data (no D-1 load and no D0 snapshot) — recorded as "
                             "'no data', never as 0."),
    "ACTUAL_CLOSE_TOO_EARLY": ("Chưa tới giờ chốt thực tế của ngày này (giờ Việt Nam).",
                               "The actual of this day cannot be closed before its close time (Vietnam time)."),
    "CLOSE_SOURCE_MANUAL_IMPORT": ("Nguồn MANUAL_IMPORT là lịch sử tĩnh từ file Excel — không có ngày đang diễn ra để chốt thực tế.",
                                   "MANUAL_IMPORT is static history from an Excel file — there is no running day to close."),
    "EOD_SCHEDULE_DISABLED": ("Lịch snapshot forecast cuối ngày đang TẮT — lần chạy theo lịch được ghi là bỏ qua.",
                              "The end-of-day forecast snapshot schedule is OFF — the scheduled run is recorded as skipped."),
    "CLOSE_SCHEDULE_DISABLED": ("Lịch chốt thực tế cuối ngày đang TẮT — lần chạy theo lịch được ghi là bỏ qua.",
                                "The end-of-day actual close schedule is OFF — the scheduled run is recorded as skipped."),
    "SCHEDULE_NOT_REGISTERED": ("Scheduler đang chạy không xác nhận đã nạp lịch này, nên lịch vẫn TẮT (không lưu trạng thái BẬT). "
                                "Kiểm tra trạng thái scheduler ở đầu trang rồi bật lại.",
                                "The running scheduler did not confirm this schedule, so it stays OFF (the ON state was not "
                                "kept). Check the scheduler state at the top of the page, then switch it on again."),
    "WAITING_FOR_FORECAST_JOB": ("Đang chờ job huấn luyện / forecast đang chạy kết thúc trước khi lấy snapshot cuối ngày.",
                                 "Waiting for the running training / forecast job to finish before the end-of-day snapshot."),
    "WAITING_FOR_D0_JOB": ("Đang chờ lần đọc D-0 đang chạy kết thúc trước khi chốt thực tế.",
                           "Waiting for the running D-0 read to finish before closing the actual."),
    "ALREADY_COMPLETE": ("Snapshot của ngày này đã hoàn chỉnh từ trước — giữ nguyên, không ghi lại.",
                         "The snapshot of this day was already complete — kept as is, nothing rewritten."),
    "ALREADY_CLOSED": ("Ngày này đã được chốt — bản chốt giữ nguyên; chỉ đối soát dữ liệu đến muộn.",
                       "This day was already closed — the close is kept; only late data is reconciled."),
    "PROMOTION_REVIEW_REQUIRED": ("Model mới dùng được nhưng KHÔNG tự thay model đang dùng (chưa có tiêu chí thay model được phê duyệt). Xem so sánh trên cùng các fold ở trang Hiệu năng model và bấm 'Dùng model này' nếu đồng ý.",
                                  "The new model is usable but does NOT replace the model in use automatically (no approved promotion rule). Review the same-fold comparison on the Model performance page and click 'Use this model' to accept it."),
    "CANDIDATE_READY_FOR_REVIEW": ("Có model mới chờ duyệt — forecast đang publish vẫn từ model đang dùng.",
                                   "A new model is waiting for review — the published forecast still comes from the model in use."),
    "MODEL_PROMOTED": ("Model đã được người dùng duyệt và đưa vào sử dụng; forecast mới đã publish. Model cũ và forecast cũ được giữ nguyên.",
                       "The model was approved by the user and put in use; a new forecast was published. The previous model and its forecasts are kept."),
    "TOO_FEW_EVALUATION_POINTS": ("Không đủ điểm đánh giá chung để so sánh hai model (dưới số điểm backtest tối thiểu).",
                                  "Not enough common evaluation points to compare the two models (below the minimum backtest points)."),
    "INCUMBENT_CONFIG_UNAVAILABLE": ("Không dựng lại được cấu hình của model đang dùng (bản cũ) — không có so sánh.",
                                     "The configuration of the model in use (old version) cannot be rebuilt — no comparison."),
    "PROMOTION_NOT_ALLOWED": ("Không thể dùng model này: không còn là model chờ duyệt, đã có model mới hơn được chấp nhận, chính sách đang là CHẶN (BLOCK) hoặc có lỗi kỹ thuật.",
                              "This model cannot be put in use: it is no longer a candidate, a newer model was accepted, the policy is BLOCK or a technical check failed."),
    "FORECAST_TOO_LARGE": ("Job dự báo vượt giới hạn an toàn (số dòng).", "Forecast job exceeds the safety limit (rows)."),
    "DIRECT_HORIZON_EXCEEDS_TRAINING": ("Model dự báo trực tiếp (DIRECT) chỉ được huấn luyện và kiểm định tới số ngày backtest; "
                                        "kỳ dự báo đang bật dài hơn — giảm kỳ dự báo hoặc tăng số ngày backtest rồi huấn luyện lại.",
                                        "A DIRECT model is trained and evaluated only up to the backtest horizon; the enabled "
                                        "horizon is longer — shorten it or raise the backtest horizon and retrain."),
    "QUALITY_GATE_EXCEPTION_ACTIVE": ("Model đang dùng được phát hành theo NGOẠI LỆ quality gate đã phê duyệt (chưa đạt ngưỡng "
                                      "chuẩn). Theo dõi sai số và xem lại trước ngày hẹn.",
                                      "The model in use was released under an approved quality-gate EXCEPTION (standard "
                                      "thresholds not met). Monitor the error and review it before the agreed date."),
    "RELEASED_WITH_GATE_EXCEPTION": ("Đã phát hành model theo ngoại lệ quality gate đã phê duyệt (chỉ cho lần huấn luyện này).",
                                     "Model released under an approved quality-gate exception (this training run only)."),
    "BQ_TABLE_ID_INVALID": ("Mã bảng phải có dạng project.dataset.table (ví dụ lakehouse-prod-394907.gold_buymed_vn2.ten_bang).",
                            "The table id must be project.dataset.table."),
    "BQ_TABLE_CHECK_FAILED": ("Bảng chưa đạt kiểm tra (không tồn tại, thiếu quyền, sai location hoặc thiếu cột đã ánh xạ) — chưa lưu, "
                              "nguồn đang dùng giữ nguyên.",
                              "The table did not pass the check (missing, no permission, wrong location or a mapped column is "
                              "missing) — not saved, the current source is unchanged."),
    "BQ_TABLE_CHANGE_NEEDS_PRODUCTION_OFF": ("Không đổi bảng D-1 khi chế độ sản xuất đang bật (sẽ đổi phạm vi dữ liệu dự báo). "
                                             "Tắt chế độ sản xuất trước, đổi bảng, rồi kiểm tra lại toàn kỳ.",
                                             "The D-1 table cannot change while production mode is on (it would switch the "
                                             "forecast data scope). Turn production off, change it, then re-validate."),
    "BQ_D0_TABLE_MISSING": ("Chưa cấu hình bảng D-0.", "The D-0 table is not configured."),
    "D0_TABLE_NOT_CHECKED": ("Bảng D-0 chưa được kiểm tra thành công (trang BigQuery → Bảng nguồn D-1 / D-0).",
                             "The D-0 table has not passed its check (BigQuery page → D-1 / D-0 source tables)."),
    "SCHEDULER_TICK_DEFERRED": ("Bộ lập lịch hoãn một lượt vì database đang bận ghi (sẽ thử lại ở lượt sau).",
                                "The scheduler deferred one tick because the database was busy writing (retried next tick)."),
    "FEATURE_GROUPS_EMPTY": ("Phải bật ít nhất một nhóm feature: nhu cầu lịch sử hoặc giá.",
                             "At least one feature group must be on: historical demand or price."),
    "NO_ACTIVE_DATASET": ("Chưa có bộ dữ liệu cho nguồn đang chọn. Hãy bấm 'Tạo dữ liệu Demo' (nguồn DEMO) hoặc import file Excel rồi chọn lô làm bộ dữ liệu (nguồn MANUAL_IMPORT).",
                          "No dataset for the selected source yet. Click 'Generate DEMO data' (DEMO source) or import an Excel file and select it as dataset (MANUAL_IMPORT)."),
    "ACTIVE_DATASET_INCONSISTENT": ("Cấu hình đang trỏ tới một lô không còn hoạt động. Hệ thống không tự chọn lô khác — vào 'Lịch sử lô import' và chọn lại bộ dữ liệu.",
                                    "Settings point at a batch that is no longer active. No other batch is chosen automatically — pick the dataset again in 'Import Batch History'."),
    "SOURCE_NOT_READY": ("Nguồn BigQuery chưa sẵn sàng: chế độ sản xuất (production) đang TẮT hoặc chưa qua đủ các bước kiểm tra "
                         "— thường do vừa lưu ánh xạ trường / SQL nguồn. Trang Kết nối BigQuery: chạy 'Kiểm tra dữ liệu toàn kỳ' "
                         "rồi bấm 'Kích hoạt chế độ sản xuất'. Chi tiết (từ lúc nào, do thay đổi nào) ở dòng bên dưới.",
                         "BigQuery source not ready: production mode is OFF or not every check has passed — usually right "
                         "after saving the field mapping / source SQL. BigQuery page: run 'Validate full period', then "
                         "'Enable production mode'. The detail below says since when and which change."),
    # --- jobs
    "NOT_APPLICABLE_FOR_SOURCE": ("Job không áp dụng cho nguồn dữ liệu đang hoạt động.", "Job does not apply to the active data source."),
    "MISSED_SLOT_NO_BACKFILL": ("Đã lỡ mốc giờ (máy tắt/ứng dụng không chạy). Không tạo snapshot giả cho mốc đã qua.",
                                "Slot missed (machine off/app not running). No fake snapshot is created for a past slot."),
    "CATCH_UP_RUN": ("Chạy bù sau khi khởi động lại; dữ liệu được ghi theo thời điểm chạy thực tế.",
                     "Catch-up run after restart; data is stamped with the actual run time."),
    "LOCKED": ("Một job tương đương đang chạy — không chạy chồng.", "An equivalent job is already running — not started twice."),
    "TIMEOUT": ("Job vượt thời gian cho phép.", "Job exceeded its timeout."),
    "RETRIES_EXHAUSTED": ("Đã hết số lần thử lại.", "Retries exhausted."),
    "SOURCE_INCOMPLETE": ("Nguồn chưa hoàn tất dữ liệu D-1.", "Source has not completed D-1 data."),
    "WAITING_FOR_SIGNAL": ("Đang chờ tín hiệu hoàn tất dữ liệu từ nguồn.", "Waiting for the source completion signal."),
    "D1_NOT_SYNCED": ("Dữ liệu D-1 chưa đồng bộ thành công hôm nay — hoãn huấn luyện.", "D-1 data not synced today — training deferred."),
    "ALREADY_SUCCEEDED": ("Job này đã chạy thành công — không chạy lại.", "This job already succeeded — not re-run."),
    "SCHEDULER_DISABLED": ("Scheduler đang tắt.", "Scheduler is disabled."),
    # --- bigquery
    "BQ_NOT_CONFIGURED": ("Chưa nhập đủ Project/Dataset/Table.", "Project/Dataset/Table not fully configured."),
    "BQ_AUTH_MISSING": ("Chưa đăng nhập Google cho tài khoản Windows đang chạy ứng dụng. Vào 'Xác thực Google': nhập OAuth client (hoặc file JSON của client) rồi bấm 'Đăng nhập Google'.",
                        "No Google sign-in for the Windows account running the app. Open 'Google authentication': enter the OAuth client (or its JSON file) and click 'Sign in with Google'."),
    "BQ_PERMISSION_DENIED": ("Đã đăng nhập nhưng tài khoản Google THIẾU QUYỀN: cần roles/bigquery.jobUser trên project (tạo query job) và roles/bigquery.dataViewer trên dataset (đọc bảng). Gửi email tài khoản cho quản trị Google Cloud.",
                             "Signed in but the Google account LACKS PERMISSION: it needs roles/bigquery.jobUser on the project (query jobs) and roles/bigquery.dataViewer on the dataset (read tables). Send the account e-mail to the Google Cloud administrator."),
    "BQ_NOT_FOUND": ("Không tìm thấy dataset hoặc bảng.", "Dataset or table not found."),
    "BQ_LOCATION_MISMATCH": ("Location cấu hình khác location thực của dataset.", "Configured location differs from the dataset location."),
    "BQ_QUERY_TOO_EXPENSIVE": ("Truy vấn vượt giới hạn bytes cho phép.", "Query exceeds the maximum bytes billed."),
    "BQ_LIBRARY_MISSING": ("Thiếu thư viện google-cloud-bigquery.", "google-cloud-bigquery library is missing."),
    "BQ_ERROR": ("Lỗi BigQuery.", "BigQuery error."),
    "BQ_AUTH_EXPIRED": ("Phiên đăng nhập Google đã hết hạn hoặc bị thu hồi (ví dụ đổi mật khẩu, gỡ quyền ứng dụng). Bấm 'Đăng nhập Google' lại — dữ liệu không bị ảnh hưởng.",
                        "The Google sign-in expired or was revoked (e.g. password change, app access removed). Click 'Sign in with Google' again — no data is affected."),
    "BQ_TIMEOUT": ("Truy vấn BigQuery vượt thời gian chờ đã cấu hình; không có dữ liệu nào bị thay đổi.",
                   "The BigQuery query exceeded the configured timeout; no data was changed."),
    "BQ_QUOTA": ("BigQuery từ chối vì vượt quota/giới hạn tần suất. Thử lại sau.", "BigQuery refused the request (quota/rate limit). Try again later."),
    "BQ_UNAVAILABLE": ("Dịch vụ BigQuery tạm thời không phản hồi (đã thử lại có giới hạn).",
                       "The BigQuery service is temporarily unavailable (bounded retries were made)."),
    "BQ_SCHEMA_CHANGED": ("Truy vấn tham chiếu cột không tồn tại hoặc sai kiểu (schema không khớp ánh xạ/SQL). Đọc lại schema và kiểm tra ánh xạ/SQL.",
                          "The query references a column that does not exist or has another type (schema does not match the mapping/SQL). Re-read the schema and check the mapping/SQL."),
    "BQ_QUERY_INVALID": ("BigQuery từ chối truy vấn kiểm tra.", "BigQuery rejected the check query."),
    "BQ_VALIDATION_REQUIRED": ("Chưa có kết quả kiểm tra dữ liệu BigQuery đạt cho ánh xạ hiện tại. Chạy 'Kiểm tra dữ liệu toàn kỳ' trước khi đồng bộ/huấn luyện.",
                               "No passing BigQuery data validation for the current mapping. Run 'Validate full period' before syncing/training."),
    "BQ_DATA_DUPLICATES": ("Nguồn có dòng trùng hoàn toàn (giống nhau ở MỌI cột đã ánh xạ) — đã chặn, KHÔNG ghi dữ liệu. Tải báo cáo dòng trùng (.xlsx) ở trang BigQuery, xử lý tại nguồn rồi chạy lại kiểm tra.",
                           "The source has fully duplicated rows (identical in EVERY mapped column) — blocked, nothing was written. Download the duplicate report (.xlsx) on the BigQuery page, fix the source, then run the check again."),
    "BQ_API_DISABLED": ("BigQuery API chưa được bật (hoặc chưa được dùng) trong project. Quản trị Google Cloud cần bật BigQuery API.",
                        "The BigQuery API is not enabled (or never used) in the project. The Google Cloud administrator must enable it."),
    "D0_SCHEDULE_DISABLED": ("Lịch D-0 đang TẮT (mặc định). Bật ở trang Lịch chạy dữ liệu khi luồng D-0 đã sẵn sàng.",
                             "The D-0 schedule is OFF (default). Turn it on on the Data schedules page once the D-0 flow is ready."),
    "D1_SCHEDULE_DISABLED": ("Lịch D-1 đang TẮT trên trang Lịch chạy dữ liệu — lần chạy theo lịch được ghi là bỏ qua, không thực thi.",
                             "The D-1 schedule is OFF on the Data schedules page — the scheduled run is recorded as skipped, nothing is executed."),
    "TRAIN_SCHEDULE_DISABLED": ("Lịch huấn luyện hằng ngày đang TẮT trên trang Lịch chạy dữ liệu — lần chạy theo lịch được ghi là bỏ qua.",
                                "The daily training schedule is OFF on the Data schedules page — the scheduled run is recorded as skipped."),
    "FLOW_NOT_READY": ("Luồng chưa sẵn sàng nên không thể bật hoặc chạy ngay. Xem các lý do bên dưới.",
                       "The flow is not ready, so it cannot be switched on or run now. See the reasons below."),
    "D1_SOURCE_NOT_BIGQUERY": ("D-1 chỉ đồng bộ ngày đã đóng từ BigQuery. Nguồn đang dùng không phải BIGQUERY: dữ liệu ngày đã đóng của DEMO/Excel đến từ lô dữ liệu, không cần lịch D-1.",
                               "D-1 only syncs closed days from BigQuery. The active source is not BIGQUERY: closed-day data of DEMO/Excel comes from its batch, no D-1 schedule is needed."),
    "D0_SOURCE_MANUAL_IMPORT": ("Nguồn MANUAL_IMPORT là lịch sử tĩnh từ file Excel, không có dữ liệu trong ngày — D-0 không áp dụng.",
                                "MANUAL_IMPORT is static history from an Excel file with no intraday data — D-0 does not apply."),
    "D0_DEMO_SYNTHETIC": ("Nguồn DEMO: snapshot D-0 là dữ liệu tổng hợp, gắn nhãn DEMO.", "DEMO source: D-0 snapshots are synthetic data labelled DEMO."),
    "TRAIN_WAITS_FOR_D1": ("Với BigQuery, huấn luyện hằng ngày chỉ chạy sau khi D-1 hôm nay thành công. Hôm nay chưa có lần D-1 "
                           "thành công và luồng D-1 đang tắt — bật luồng D-1 hoặc chạy D-1 thủ công (trang Lịch chạy dữ liệu).",
                           "With BigQuery the daily training runs only after today's D-1 succeeded. There is no successful D-1 "
                           "today and the D-1 flow is OFF — switch the D-1 flow on or run D-1 by hand (Data schedules page)."),
    "TRAIN_WAITING_FOR_TODAY_D1": ("Huấn luyện đang chờ D-1 hôm nay thành công (chưa có lần D-1 thành công nào hôm nay).",
                                   "The training waits for today's D-1 to succeed (no successful D-1 today yet)."),
    "D1_TODAY_SUCCEEDED": ("D-1 hôm nay đã thành công — huấn luyện theo lịch được phép chạy (vẫn qua quality gate).",
                           "Today's D-1 succeeded — the scheduled training may run (the quality gate still applies)."),
    "D0_MAPPING_INCOMPLETE": ("Ánh xạ D-0 thiếu trường thiết yếu để đối chiếu demand (SKU, FC, số lượng hoặc ngày). Mở trang "
                              "Nguồn SQL → D-0 → Ánh xạ D-0 và chọn cột cho các trường trong chi tiết.",
                              "The D-0 mapping lacks an essential field for the demand comparison (SKU, FC, quantity or day). "
                              "Open SQL sources → D-0 → D-0 mapping and choose a column for the fields in the detail."),
    "D0_REVALIDATE_REQUIRED": ("SQL/bảng D-0 đã được xác nhận cho một ánh xạ hoặc khóa D-0 khác (hoặc trước bản 1.2.1) — bấm "
                               "Xác nhận với BigQuery lại cho phiên bản cần dùng.",
                               "The D-0 SQL/table was validated for another D-0 mapping or key (or before 1.2.1) — validate "
                               "the version to use with BigQuery again."),
    "D0_MAPPING_TYPE_INCOMPATIBLE": ("Cột ánh xạ D-0 có kiểu dữ liệu không dùng được (xem chi tiết trường / cột / kiểu).",
                                     "A mapped D-0 column has an unusable type (see field / column / type in the detail)."),
    "D0_LAST_CHECK_DATA_ISSUES": ("Lần kiểm tra BigQuery gần nhất của D-0 thấy vấn đề dữ liệu có thể chặn snapshot.",
                                  "The last BigQuery check of D-0 found data issues that may block a snapshot."),
    "SCHEDULER_NOT_RUNNING": ("Đã lưu, nhưng scheduler không chạy trong tiến trình này (ví dụ chế độ kiểm thử) — lịch CHƯA có hiệu lực cho tới khi ứng dụng chạy với scheduler.",
                              "Saved, but the scheduler is not running in this process (e.g. test mode) — the schedule has NO effect until the app runs with its scheduler."),
    "SCHEDULE_SWITCH_VIA_FLOW_API": ("Công tắc bật/tắt từng luồng chỉ đổi được ở trang Lịch chạy dữ liệu (có kiểm tra sẵn sàng).",
                                     "Flow switches can only be changed on the Data schedules page (with a readiness check)."),
    "BQ_SQL_ERROR": ("BigQuery báo lỗi cú pháp SQL (xem chi tiết dòng/cột). SQL không được tự sửa.",
                     "BigQuery reports an SQL syntax error (see line/column in the detail). The SQL is not auto-corrected."),
    "BQ_KEY_NOT_UNIQUE": ("Khóa duy nhất ứng viên của dữ liệu chưa được chứng minh (có dòng trùng khóa) — không ghi dữ liệu. Kiểm tra khóa hoặc chọn rõ chính sách cộng dồn.",
                          "The candidate unique key is not proven (rows share a key) — nothing is written. Check the key or explicitly choose the sum policy."),
    "SQL_REJECTED": ("SQL bị từ chối: chỉ cho phép một câu truy vấn đọc (SELECT/WITH), không có lệnh ghi/xóa/DDL.",
                     "SQL rejected: only a single read query (SELECT/WITH) is allowed, no write/delete/DDL statement."),
    "SQL_NOT_A_QUERY": ("BigQuery xác định câu lệnh không phải truy vấn SELECT.", "BigQuery says the statement is not a SELECT query."),
    "SQL_OUTPUT_MISSING_COLUMNS": ("Kết quả SQL thiếu cột cần thiết theo ánh xạ hoặc khóa duy nhất.",
                                   "The SQL output lacks columns required by the mapping or the unique key."),
    "SQL_NOT_VALIDATED": ("Chưa có phiên bản SQL nào được BigQuery xác nhận cho nguồn này — job không chạy. Mở trang Nguồn SQL, "
                          "chọn phiên bản và bấm Xác nhận với BigQuery (chi tiết: trạng thái từng phiên bản).",
                          "No SQL version of this feed has been validated by BigQuery — the job does not run. Open SQL "
                          "sources, pick a version and validate it with BigQuery (detail: status of each version)."),
    "OAUTH_NOT_CONFIGURED": ("Chưa có OAuth client (loại Desktop app) do quản trị Google Cloud cấp. Nhập Client ID và Client secret trước khi đăng nhập.",
                             "No OAuth client (Desktop app) from the Google Cloud administrator yet. Enter the client ID and secret before signing in."),
    "OAUTH_IN_PROGRESS": ("Đang chờ đăng nhập Google trong trình duyệt.", "Waiting for the Google sign-in in the browser."),
    "OAUTH_CANCELLED": ("Đăng nhập đã bị hủy (trong trình duyệt hoặc trong ứng dụng). Bấm 'Đăng nhập Google' để thử lại.",
                        "The sign-in was cancelled (in the browser or in the app). Click 'Sign in with Google' to try again."),
    "OAUTH_BLOCKED": ("Google hoặc chính sách tổ chức chặn đăng nhập (client không hợp lệ, ứng dụng bị chặn, màn hình đồng ý chỉ cho nội bộ). Gửi mã lỗi chi tiết cho quản trị Google Cloud.",
                      "Google or the organisation policy blocked the sign-in (invalid client, app blocked, internal-only consent screen). Send the detailed error code to the Google Cloud administrator."),
    "OAUTH_ERROR": ("Đăng nhập Google không thành công. Thử lại; nếu lặp lại, gửi mã lỗi chi tiết cho quản trị.",
                    "Google sign-in failed. Try again; if it repeats, send the detailed error code to the administrator."),
    "OAUTH_TIMEOUT": ("Hết thời gian chờ đăng nhập trong trình duyệt. Nếu trang Google báo 'redirect_uri_mismatch', OAuth client không phải loại 'Desktop app'.",
                      "The browser sign-in timed out. If Google showed 'redirect_uri_mismatch', the OAuth client is not of type 'Desktop app'."),
    "OAUTH_NETWORK": ("Không kết nối được tới Google (mạng, proxy hoặc tường lửa). Kiểm tra mạng rồi thử lại.",
                      "Could not reach Google (network, proxy or firewall). Check the network and try again."),
    "OAUTH_STATE_MISMATCH": ("Phản hồi đăng nhập không khớp phiên hiện tại (có thể là tab cũ) — đã bỏ qua để an toàn. Đăng nhập lại.",
                             "The sign-in answer does not match the current session (perhaps an old tab) — ignored for safety. Sign in again."),
    "OAUTH_NO_REFRESH_TOKEN": ("Google không trả về refresh token. Gỡ quyền ứng dụng trong tài khoản Google (Bảo mật → Ứng dụng bên thứ ba) rồi đăng nhập lại.",
                               "Google returned no refresh token. Remove the app's access in the Google account (Security → Third-party apps) and sign in again."),
    "OAUTH_IDENTITY_UNVERIFIED": ("Không xác định được email đã xác minh của tài khoản Google — đăng nhập bị từ chối.",
                                  "The verified e-mail of the Google account could not be read — sign-in refused."),
    "OAUTH_SCOPE_NOT_GRANTED": ("Tài khoản Google chưa cấp quyền BigQuery cho ứng dụng. Đăng nhập lại và đánh dấu quyền 'BigQuery' trên trang đồng ý.",
                                "The Google account did not grant the BigQuery permission to the app. Sign in again and tick the 'BigQuery' permission on the consent page."),
    "OAUTH_CLIENT_INVALID": ("OAuth client không hợp lệ, đã bị xóa hoặc secret sai. Quản trị Google Cloud kiểm tra client (loại Desktop app), rồi nhập lại client và đăng nhập lại.",
                             "The OAuth client is invalid, deleted or its secret is wrong. The Google Cloud administrator checks the client (Desktop app type); then enter the client again and sign in again."),
    "OAUTH_CLIENT_CHANGED": ("OAuth client đã được thay đổi — phiên đăng nhập cũ thuộc client cũ đã được gỡ. Bấm 'Đăng nhập Google' lại.",
                             "The OAuth client was changed — the old sign-in belonged to the old client and was removed. Click 'Sign in with Google' again."),
    "OAUTH_CLIENT_WRONG_TYPE": ("File client là loại 'Web application'. Ứng dụng cần OAuth client loại 'Desktop app' (đăng nhập qua 127.0.0.1). Nhờ quản trị tạo client loại Desktop app.",
                                "The client file is a 'Web application' client. The app needs an OAuth client of type 'Desktop app' (loopback 127.0.0.1 sign-in). Ask the administrator for a Desktop app client."),
    "OAUTH_CLIENT_FILE_INVALID": ("File không phải file JSON OAuth client tải từ Google Cloud Console (thiếu client_id/client_secret).",
                                  "The file is not an OAuth client JSON downloaded from the Google Cloud Console (client_id/client_secret missing)."),
    "OAUTH_STORE_ERROR": ("Không đọc/ghi được Windows Credential Manager cho tài khoản này.", "Windows Credential Manager cannot be read/written for this account."),
    "BQ_SYNC_RECONCILIATION_FAILED": ("Tổng số lượng ghi vào ứng dụng không khớp tổng hợp lệ đọc từ BigQuery — không ghi dữ liệu.",
                                      "The quantity written does not match the valid total read from BigQuery — nothing was written."),
    # --- database / storage / internal
    "DATABASE_CONSTRAINT": ("Thao tác bị cơ sở dữ liệu từ chối để bảo vệ tính toàn vẹn; không có dữ liệu nào bị thay đổi. Đừng xóa database — hãy tạo báo cáo chẩn đoán (Hệ thống & sao lưu) và gửi cho bộ phận kỹ thuật.",
                            "The database refused the operation to protect integrity; nothing was changed. Do not delete the database — create a diagnostic report (System & Backup) and send it to support."),
    "DATABASE_LOCKED": ("Cơ sở dữ liệu đang bận (một tác vụ khác đang ghi). Hãy thử lại sau ít phút.", "The database is busy (another task is writing). Try again in a few minutes."),
    "DATABASE_ERROR": ("Lỗi cơ sở dữ liệu. Dữ liệu đã xác nhận trước đó vẫn được giữ. Hãy tạo báo cáo chẩn đoán.", "Database error. Previously confirmed data is kept. Please create a diagnostic report."),
    "DATA_CONSISTENCY": ("Thao tác bị hủy vì sẽ làm dữ liệu không nhất quán; dữ liệu trước đó vẫn được giữ nguyên.", "Operation cancelled because it would leave data inconsistent; previous data is unchanged."),
    "INTERNAL_ERROR": ("Lỗi hệ thống. Chi tiết đã được ghi vào log; hãy tạo báo cáo chẩn đoán.", "Internal error. Details are in the log; please create a diagnostic report."),
    "VALIDATION_ERROR": ("Dữ liệu gửi lên không hợp lệ.", "Invalid request data."),
    "CSRF_BLOCKED": ("Yêu cầu bị chặn (thiếu header bảo vệ).", "Request blocked (missing protection header)."),
    "FORBIDDEN_HOST": ("Host không được phép.", "Host not allowed."),
    "STORAGE_NOT_FOUND": ("Không tìm thấy thư mục/cơ sở dữ liệu đã cấu hình. Ứng dụng không tự tạo database trống ở nơi khác. Kiểm tra ổ đĩa hoặc chạy scripts\rollback-storage.ps1.",
                          "Configured data folder/database not found. The app does not create an empty database elsewhere. Check the drive or run scripts\rollback-storage.ps1."),
    "STORAGE_CONFIG_MISSING": ("Thiếu file cấu hình lưu trữ (storage.json) dù dữ liệu đã được chuyển sang thư mục khác. Ứng dụng không tạo database trống. Chạy scripts\\repair-storage.ps1 để khôi phục từ lịch sử di chuyển đã xác minh.",
                               "The storage configuration (storage.json) is missing although the data was moved elsewhere. No empty database is created. Run scripts\\repair-storage.ps1 to restore it from the verified migration history."),
    "STORAGE_NOT_WRITABLE": ("Không có quyền ghi vào thư mục dữ liệu đã cấu hình.", "The configured data folder is not writable."),
    "STORAGE_CONFIG_INVALID": ("File cấu hình đường dẫn (storage.json) không hợp lệ.", "The storage path configuration (storage.json) is invalid."),
    "BQ_MAPPING_INVALID": ("Ánh xạ trường không hợp lệ so với schema nguồn (thiếu trường bắt buộc, cột không còn tồn tại hoặc sai kiểu) — không đọc, không ghi dữ liệu. Xem danh sách trường trong chi tiết và sửa ánh xạ.",
                           "The field mapping does not match the source schema (required field missing, column gone or wrong type) — nothing is read or written. See the field list in the detail and fix the mapping."),
    "BQ_AGGREGATE_INVALID": ("Dữ liệu sau tổng hợp ngày × SKU × FC không hợp lệ (ngày sai, thiếu SKU/FC, trùng khóa đầu ra hoặc số lượng không hợp lệ) — không ghi dữ liệu.",
                             "The aggregated day × SKU × FC rows are invalid (bad date, missing SKU/FC, repeated output key or invalid quantity) — nothing was written."),
}


def msg(code: str) -> dict:
    vi, en = CATALOG.get(code, (code, code))
    return {"code": code, "vi": vi, "en": en}


def category(code: str) -> str:
    """Stable error category for the UI: INPUT | DATABASE | CONFIG | BIGQUERY | MODEL | STORAGE | INTERNAL."""
    if code.startswith(("BQ_", "SQL_", "OAUTH_")):
        return "BIGQUERY"
    if code.startswith("DATABASE_") or code in ("DATA_CONSISTENCY",):
        return "DATABASE"
    if code.startswith("STORAGE_"):
        return "STORAGE"
    if code in ("TRAINING_FAILED", "QUALITY_GATE_FAILED", "DATA_NOT_TRAINABLE", "FORECAST_TOO_LARGE", "PUBLISH_FAILED",
                "MODEL_ARTIFACT_MISSING", "DATA_CHANGED_SINCE_TRAINING", "REPRODUCTION_MISMATCH", "NOTHING_TO_EXTEND",
                "NOT_LIGHTGBM", "TRACE_TOO_LARGE", "TRACE_TIMEOUT", "UNSUPPORTED_MODEL", "PROMOTION_REVIEW_REQUIRED",
                "PROMOTION_NOT_ALLOWED", "DIRECT_HORIZON_EXCEEDS_TRAINING", "QUALITY_GATE_EXCEPTION_ACTIVE",
                "RELEASED_WITH_GATE_EXCEPTION", "FORECAST_PUBLISHED_WITH_WARNING", "NO_FORECAST_FOR_ACTIVE_SOURCE"):
        return "MODEL"
    if code in ("NO_ACTIVE_DATASET", "ACTIVE_DATASET_INCONSISTENT", "SOURCE_NOT_READY", "SCHEDULER_DISABLED",
                "FLOW_NOT_READY", "D0_SCHEDULE_DISABLED", "D1_SCHEDULE_DISABLED", "TRAIN_SCHEDULE_DISABLED",
                "SCHEDULE_SWITCH_VIA_FLOW_API", "SCHEDULER_NOT_RUNNING", "D0_MAPPING_INCOMPLETE", "D0_REVALIDATE_REQUIRED",
                "TRAIN_WAITS_FOR_D1", "EOD_SCHEDULE_DISABLED", "CLOSE_SCHEDULE_DISABLED", "CLOSE_SOURCE_MANUAL_IMPORT",
                "SCHEDULE_NOT_REGISTERED"):
        return "CONFIG"
    if code in ("INTERNAL_ERROR",):
        return "INTERNAL"
    return "INPUT"


class AppError(Exception):
    """Error with a catalogue code; rendered as {code, vi, en, detail} by the API."""

    def __init__(self, code: str, status: int = 400, detail: str | None = None, **params):
        super().__init__(f"{code}: {detail or ''}")
        self.code = code
        self.status = status
        self.detail = detail
        self.params = params

    def to_dict(self) -> dict:
        d = msg(self.code)
        d["category"] = category(self.code)
        d["detail"] = self.detail
        d["params"] = self.params
        return d

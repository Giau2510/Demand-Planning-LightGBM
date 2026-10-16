"""Internal (provisional) order-line schema shared by DEMO, MANUAL_IMPORT and BIGQUERY."""
from __future__ import annotations

import re
import unicodedata

# kind: datetime | date | text | number | flag
FIELDS: list[dict] = [
    {"name": "order_id", "kind": "text", "required": False,
     "vi": "Mã đơn hàng. Dùng để phát hiện dòng trùng và xác định grain (đơn × SKU × FC).",
     "en": "Order ID. Used to detect duplicates and define the grain (order × SKU × FC).",
     "example": "SO-000123"},
    {"name": "created_at", "kind": "datetime", "required": True,
     "vi": "Thời điểm tạo đơn. Định dạng YYYY-MM-DD HH:MM[:SS] hoặc DD/MM/YYYY HH:MM. Không có múi giờ = giờ Việt Nam.",
     "en": "Order creation time. Format YYYY-MM-DD HH:MM[:SS] or DD/MM/YYYY HH:MM. No offset = Vietnam time.",
     "example": "2026-03-15 09:42:00"},
    {"name": "order_date", "kind": "date", "required": False,
     "vi": "Ngày đặt hàng (tùy chọn). Nếu để trống sẽ lấy ngày của created_at theo giờ Việt Nam.",
     "en": "Order date (optional). If empty it is derived from created_at in Vietnam time.",
     "example": "2026-03-15"},
    {"name": "sku_id", "kind": "text", "required": True,
     "vi": "Mã SKU (văn bản, giữ nguyên số 0 ở đầu).", "en": "SKU code (text, leading zeros preserved).",
     "example": "SKU-0001"},
    {"name": "fc_id", "kind": "text", "required": True,
     "vi": "Mã FC/kho.", "en": "Fulfilment centre / warehouse code.", "example": "FC-HCM"},
    {"name": "order_qty", "kind": "number", "required": True,
     "vi": "Số lượng khách đặt tại thời điểm tạo đơn (không trừ hủy). Số ≥ 0.",
     "en": "Quantity ordered at order creation (cancellations NOT subtracted). Number ≥ 0.",
     "example": "12"},
    {"name": "unit_price", "kind": "number", "required": False,
     "vi": "Đơn giá tại thời điểm đặt.", "en": "Unit price at order time.", "example": "45000"},
    {"name": "discount_amount", "kind": "number", "required": False,
     "vi": "Tổng tiền giảm giá của dòng tại thời điểm đặt.", "en": "Line discount amount at order time.",
     "example": "5000"},
    {"name": "promotion_flag", "kind": "flag", "required": False,
     "vi": "Có khuyến mãi không: 1/0, TRUE/FALSE, Y/N, Có/Không.", "en": "Promotion applied: 1/0, TRUE/FALSE, Y/N.",
     "example": "1"},
    {"name": "promotion_id", "kind": "text", "required": False,
     "vi": "Mã chương trình khuyến mãi.", "en": "Promotion ID.", "example": "PROMO-T3"},
    {"name": "voucher_flag", "kind": "flag", "required": False,
     "vi": "Có dùng voucher không.", "en": "Voucher used.", "example": "0"},
    {"name": "voucher_amount", "kind": "number", "required": False,
     "vi": "Giá trị voucher.", "en": "Voucher amount.", "example": "0"},
    {"name": "source_updated_at", "kind": "datetime", "required": False,
     "vi": "Thời điểm bản ghi được cập nhật ở hệ thống nguồn (để phát hiện dữ liệu đến muộn).",
     "en": "Last update time in the source system (used to detect late-arriving data).",
     "example": "2026-03-15 10:00:00"},
    {"name": "batch_id", "kind": "text", "required": False,
     "vi": "Mã lô dữ liệu của hệ thống nguồn (nếu có).", "en": "Source system batch ID (if any).",
     "example": "B20260315"},
]
FIELD_NAMES = [f["name"] for f in FIELDS]
FIELD_BY_NAME = {f["name"]: f for f in FIELDS}
REQUIRED_CORE = ["sku_id", "fc_id", "order_qty"]  # plus created_at OR order_date


def normalize_header(h) -> str:
    """Exact-match normalisation only: case, accents, spaces/dashes. No fuzzy matching."""
    if h is None:
        return ""
    s = unicodedata.normalize("NFKD", str(h)).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[\s\-\.]+", "_", s.strip().lower())
    return s.strip("_")


def suggest_mapping(headers: list[str], aliases: dict[str, list[str]]) -> dict[str, str | None]:
    """Map internal field -> source header, by exact normalised name or a configured alias only."""
    norm = {normalize_header(h): h for h in headers if h is not None and str(h).strip()}
    out: dict[str, str | None] = {}
    for f in FIELD_NAMES:
        cands = [f] + [normalize_header(a) for a in aliases.get(f, [])]
        out[f] = next((norm[c] for c in cands if c in norm), None)
    return out

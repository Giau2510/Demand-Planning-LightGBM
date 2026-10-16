-- DE XUAT hieu chinh SQL D0 (15/10/2026) - CHUA duoc xac nhan nghiep vu, CHUA kich hoat.
-- So voi ban goc (phien ban 1):
--  (1) bo dau phay thua sau b.sales_price truoc FROM;
--  (2) LEFT JOIN -> JOIN cho b va c: ket qua GIONG ban goc, vi WHERE tren cot cua b va c da loai dong khong khop;
--  (3) dieu kien seller / sku_system_status cua bang master dua vao CTE `master` + DISTINCT: loai dong master trung
--      HOAN TOAN (truoc day nhan doi nhu cau); neu cung sub_sku_code co nhieu trang thai khac nhau thi van con trung
--      -> ung dung phat hien va CHAN ghi (khoa khong duy nhat);
--  (4) DATE(a.created_at, 'Asia/Ho_Chi_Minh'): CHI DUNG neu created_at la TIMESTAMP (UTC). Neu created_at la DATETIME
--      gio Viet Nam thi giu DATE(a.created_at) nhu ban goc. Dry-run va schema that se quyet dinh.
-- Luu y: a.order_status NOT IN ('CANCEL') cung loai cac don co order_status NULL (giu nguyen nhu ban goc).
WITH master AS (
  SELECT DISTINCT sub_sku_code, seller_code, sku_system_status
  FROM `lakehouse-prod-394907.gold_buymed_vn2.adhoc_pm_master_sku`
  WHERE seller_code IN ('MEDX')
    AND sku_system_status IN ('OUT_OF_STOCK', 'LIMIT', 'NORMAL')
)
SELECT
  a.fc_code,
  DATE(a.created_at, 'Asia/Ho_Chi_Minh') AS created_date,
  a.so_code,
  a.order_status,
  b.product_id,
  b.sku_code,
  b.item_code,
  c.seller_code,
  c.sku_system_status,
  b.demand_quantity,
  b.sales_price
FROM `lakehouse-prod-394907.gold_buymed_vn2.fact_order` a
JOIN `lakehouse-prod-394907.gold_buymed_vn2.fact_order_item` b
  ON a.order_id = b.order_id
JOIN master c
  ON b.item_code = c.sub_sku_code
WHERE b.created_date = CURRENT_DATE('Asia/Ho_Chi_Minh')
  AND a.order_status NOT IN ('CANCEL')

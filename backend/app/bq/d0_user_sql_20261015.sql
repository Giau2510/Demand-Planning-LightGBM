SELECT
  a.fc_code,
  DATE(a.created_at) AS created_date,
  a.so_code,
  a.order_status,
  b.product_id,
  b.sku_code,
  b.item_code,
  c.seller_code,
  c.sku_system_status,
  b.demand_quantity,
  b.sales_price,
FROM `lakehouse-prod-394907.gold_buymed_vn2.fact_order` a
LEFT JOIN `lakehouse-prod-394907.gold_buymed_vn2.fact_order_item` b
  ON a.order_id = b.order_id
LEFT JOIN `lakehouse-prod-394907.gold_buymed_vn2.adhoc_pm_master_sku` c
  ON b.item_code = c.sub_sku_code
WHERE 1 = 1
  AND b.created_date = CURRENT_DATE('Asia/Ho_Chi_Minh')
  AND a.order_status NOT IN ('CANCEL')
  AND c.seller_code IN ('MEDX')
  AND c.sku_system_status IN ('OUT_OF_STOCK', 'LIMIT', 'NORMAL')

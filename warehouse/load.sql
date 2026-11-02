-- Rebuild the warehouse from /data (idempotent). Run: docker compose exec db psql -U labops -f /warehouse/load.sql
\set ON_ERROR_STOP on
BEGIN;
\i /warehouse/schema.sql
\copy erp.suppliers FROM '/data/erp_suppliers.csv' CSV HEADER
\copy erp.materials FROM '/data/erp_materials.csv' CSV HEADER NULL ''
\copy erp.purchase_orders FROM '/data/erp_purchase_orders.csv' CSV HEADER
\copy erp.goods_receipts FROM '/data/erp_goods_receipts.csv' CSV HEADER
\copy erp.stock_batches FROM '/data/erp_stock_batches.csv' CSV HEADER
\copy erp.inventory_movements FROM '/data/erp_inventory_movements.csv' CSV HEADER NULL ''
\copy erp.process_orders FROM '/data/erp_process_orders.csv' CSV HEADER
\copy erp.sampling_plans FROM '/data/erp_sampling_plans.csv' CSV HEADER
\copy lims.specifications FROM '/data/lims_specifications.csv' CSV HEADER NULL ''
\copy lims.samples FROM '/data/lims_samples.csv' CSV HEADER NULL ''
\copy lims.analyses FROM '/data/lims_analyses.csv' CSV HEADER NULL ''
\copy mes.protocols FROM '/data/mes_protocols.csv' CSV HEADER
\copy mes.protocol_materials FROM '/data/mes_protocol_materials.csv' CSV HEADER
\copy mes.executions FROM '/data/mes_executions.csv' CSV HEADER
\copy mes.consumption FROM '/data/mes_consumption.csv' CSV HEADER
\copy lims.daily_wip FROM '/data/lims_daily_wip.csv' CSV HEADER
\copy lims.wait_events FROM '/data/lims_wait_events.csv' CSV HEADER NULL ''
COMMIT;

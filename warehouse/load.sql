-- Reload all CSVs from /data (idempotent). Run: docker compose exec db psql -U labops -f /warehouse/load.sql
\set ON_ERROR_STOP on
\i /warehouse/schema.sql
BEGIN;
TRUNCATE lims.results, lims.samples, mes.downtime, mes.consumption, mes.batches,
         procurement.receipts, procurement.po_lines, procurement.materials, procurement.suppliers;
\copy procurement.suppliers FROM '/data/suppliers.csv' CSV HEADER
\copy procurement.materials FROM '/data/materials.csv' CSV HEADER
\copy procurement.po_lines FROM '/data/po_lines.csv' CSV HEADER
\copy procurement.receipts FROM '/data/receipts.csv' CSV HEADER NULL ''
\copy mes.batches FROM '/data/mes_batches.csv' CSV HEADER NULL ''
\copy mes.consumption FROM '/data/mes_consumption.csv' CSV HEADER
\copy mes.downtime FROM '/data/mes_downtime.csv' CSV HEADER
\copy lims.samples FROM '/data/lims_samples.csv' CSV HEADER NULL ''
\copy lims.results FROM '/data/lims_results.csv' CSV HEADER NULL ''
COMMIT;

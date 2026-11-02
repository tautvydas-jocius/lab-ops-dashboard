-- One schema per source system, plus `analytics` views that join them.
CREATE SCHEMA IF NOT EXISTS procurement;
CREATE SCHEMA IF NOT EXISTS mes;
CREATE SCHEMA IF NOT EXISTS lims;
CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS procurement.suppliers (
  supplier_id text PRIMARY KEY, name text, country text, category text);
CREATE TABLE IF NOT EXISTS procurement.materials (
  material_id text PRIMARY KEY, name text, spend_type text, category text, uom text,
  standard_price_eur numeric);
CREATE TABLE IF NOT EXISTS procurement.po_lines (
  po_number bigint, po_line int, supplier_id text REFERENCES procurement.suppliers,
  material_id text REFERENCES procurement.materials, spend_type text, category text,
  order_date date, promised_date date, quantity numeric, uom text, unit_price_eur numeric,
  standard_price_eur numeric, ppv_eur numeric, buyer text, PRIMARY KEY (po_number, po_line));
CREATE TABLE IF NOT EXISTS procurement.receipts (
  receipt_id text PRIMARY KEY, po_number bigint, supplier_id text, material_id text,
  received_date date, quantity numeric, supplier_lot text, lims_sample_id text, accepted boolean);

CREATE TABLE IF NOT EXISTS mes.batches (
  batch_id text PRIMARY KEY, sku text, product text, line text, start_ts timestamp, end_ts timestamp,
  planned_run_hours numeric, planned_qty int, good_qty int, scrap_qty int, uom text,
  api_supplier_id text, disposition text);
CREATE TABLE IF NOT EXISTS mes.consumption (
  batch_id text REFERENCES mes.batches, material_id text, supplier_lot text, receipt_id text,
  quantity numeric);
CREATE TABLE IF NOT EXISTS mes.downtime (
  batch_id text REFERENCES mes.batches, line text, start_ts timestamp, minutes int, reason text);

CREATE TABLE IF NOT EXISTS lims.samples (
  sample_id text PRIMARY KEY, kind text, source_system text, source_ref text,
  product_or_material text, sample_type text, sample_point text, date_sampled timestamp,
  date_received timestamp, date_verified timestamp, status text, out_of_spec boolean);
CREATE TABLE IF NOT EXISTS lims.results (
  sample_id text REFERENCES lims.samples, keyword text, test text, result numeric, unit text,
  spec_min numeric, spec_max numeric, out_of_spec boolean, captured_ts timestamp);

-- Procurement: PO line with delivery performance and supplier quality
CREATE OR REPLACE VIEW analytics.po_performance AS
SELECT p.*, s.name AS supplier, s.country, m.name AS material,
       p.quantity * p.unit_price_eur AS spend_eur,
       r.received_date, r.received_date - p.promised_date AS days_late,
       r.received_date <= p.promised_date AS on_time, r.accepted AS lot_accepted
FROM procurement.po_lines p
JOIN procurement.suppliers s USING (supplier_id)
JOIN procurement.materials m USING (material_id)
LEFT JOIN procurement.receipts r USING (po_number);

-- MES: batch KPIs + LIMS release result
CREATE OR REPLACE VIEW analytics.batch_kpis AS
SELECT b.*, b.good_qty::numeric / b.planned_qty AS yield,
       EXTRACT(EPOCH FROM b.end_ts - b.start_ts) / 3600 AS actual_hours,
       COALESCE(d.minutes, 0) AS downtime_minutes,
       sp.name AS api_supplier
FROM mes.batches b
LEFT JOIN (SELECT batch_id, SUM(minutes) AS minutes FROM mes.downtime GROUP BY 1) d USING (batch_id)
LEFT JOIN procurement.suppliers sp ON sp.supplier_id = b.api_supplier_id;

-- LIMS: sample turnaround
CREATE OR REPLACE VIEW analytics.sample_tat AS
SELECT s.*, EXTRACT(EPOCH FROM s.date_verified - s.date_received) / 3600 AS tat_hours
FROM lims.samples s;

-- Cross-system genealogy: supplier lot -> batch -> release result
CREATE OR REPLACE VIEW analytics.lot_genealogy AS
SELECT c.supplier_lot, r.receipt_id, sp.name AS supplier, m.name AS material,
       r.accepted AS lot_accepted, b.batch_id, b.product, b.disposition,
       rs.sample_id AS release_sample, rs.out_of_spec AS release_oos
FROM mes.consumption c
JOIN procurement.receipts r USING (receipt_id)
JOIN procurement.suppliers sp ON sp.supplier_id = r.supplier_id
JOIN procurement.materials m ON m.material_id = c.material_id
JOIN mes.batches b USING (batch_id)
LEFT JOIN lims.samples rs ON rs.source_ref = b.batch_id AND rs.kind = 'Release';

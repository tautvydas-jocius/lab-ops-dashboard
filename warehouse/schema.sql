-- One schema per source system, plus `analytics` views that join them.
DROP SCHEMA IF EXISTS procurement, mes, lims, erp, analytics CASCADE;
CREATE SCHEMA erp;
CREATE SCHEMA lims;
CREATE SCHEMA mes;
CREATE SCHEMA analytics;

-- ERP: procurement, stock, and the demand that triggers QC sampling
CREATE TABLE erp.suppliers (supplier_id text PRIMARY KEY, name text, country text, category text, lead_time_days int);
CREATE TABLE erp.materials (material_id text PRIMARY KEY, name text, material_type text, uom text,
  standard_price_eur numeric, reorder_point numeric, shelf_life_days int);
CREATE TABLE erp.purchase_orders (po_number bigint, po_line int, supplier_id text REFERENCES erp.suppliers,
  material_id text REFERENCES erp.materials, material_type text, order_date date, promised_date date, quantity numeric,
  uom text, unit_price_eur numeric, standard_price_eur numeric, ppv_eur numeric, buyer text, PRIMARY KEY (po_number, po_line));
CREATE TABLE erp.goods_receipts (receipt_id text PRIMARY KEY, po_number bigint, supplier_id text, material_id text,
  received_date date, quantity numeric, batch_id text);
CREATE TABLE erp.stock_batches (batch_id text PRIMARY KEY, material_id text REFERENCES erp.materials, supplier_id text,
  receipt_id text, supplier_lot text, received_date date, expiry_date date, quantity_received numeric,
  quantity_on_hand numeric, status text);
CREATE TABLE erp.inventory_movements (movement_id text PRIMARY KEY, batch_id text REFERENCES erp.stock_batches,
  material_id text, movement_type text, quantity numeric, posted_ts timestamp, reference text);
CREATE TABLE erp.process_orders (order_id bigint PRIMARY KEY, material_id text, product text, line text, order_date date,
  quantity int, uom text);
CREATE TABLE erp.sampling_plans (plan_id text, trigger text, material_id text, sample_type text, sample_point text,
  samples_per_trigger int, analyses text);

-- LIMS: samples logged from sampling plans, predefined analyses with specifications
CREATE TABLE lims.specifications (keyword text PRIMARY KEY, test text, unit text, spec_min numeric, spec_max numeric);
CREATE TABLE lims.samples (sample_id text PRIMARY KEY, plan_id text, trigger text, trigger_ref text, material_id text,
  sample_type text, sample_point text, logged_ts timestamp, received_ts timestamp, completed_ts timestamp,
  verified_ts timestamp, status text, out_of_spec boolean);
CREATE TABLE lims.analyses (analysis_id text PRIMARY KEY, sample_id text REFERENCES lims.samples, keyword text, test text,
  unit text, spec_min numeric, spec_max numeric, result numeric, out_of_spec boolean, status text,
  completed_ts timestamp, execution_id text);

-- MES: test protocol execution and the lab stock each run consumed
CREATE TABLE mes.protocols (protocol_id text, keyword text PRIMARY KEY, analyst_minutes int, elapsed_minutes int,
  instrument text, lab_area text);
CREATE TABLE mes.protocol_materials (keyword text, material_id text, quantity_per_run numeric);
CREATE TABLE mes.executions (execution_id text PRIMARY KEY, analysis_id text REFERENCES lims.analyses,
  sample_id text, keyword text, protocol_id text, work_order_ts timestamp, analyst text, instrument text,
  start_ts timestamp, end_ts timestamp,
  analyst_minutes int, status text, attempt int);
CREATE TABLE mes.consumption (execution_id text REFERENCES mes.executions, batch_id text REFERENCES erp.stock_batches,
  material_id text, quantity numeric, uom text);

-- Purchase order lines with delivery performance
CREATE VIEW analytics.po_performance AS
SELECT p.*, s.name AS supplier, s.category AS supplier_category, m.name AS material,
       p.quantity * p.unit_price_eur AS spend_eur, g.received_date,
       g.received_date - p.promised_date AS days_late, g.received_date <= p.promised_date AS on_time,
       b.status AS batch_status
FROM erp.purchase_orders p
JOIN erp.suppliers s USING (supplier_id)
JOIN erp.materials m USING (material_id)
LEFT JOIN erp.goods_receipts g USING (po_number)
LEFT JOIN erp.stock_batches b ON b.batch_id = g.batch_id;

-- Samples with turnaround, the ERP trigger and the product/material
CREATE VIEW analytics.sample_tat AS
SELECT s.*, m.name AS material, m.material_type,
       CASE WHEN s.plan_id LIKE 'SP-REL%' THEN 'Release' ELSE 'In-process' END AS kind,
       EXTRACT(EPOCH FROM s.verified_ts - s.received_ts) / 3600 AS tat_hours
FROM lims.samples s JOIN erp.materials m USING (material_id);

-- Cost of every execution at standard price of the stock it consumed
CREATE VIEW analytics.execution_cost AS
SELECT e.*, COALESCE(c.cost_eur, 0) AS material_cost_eur
FROM mes.executions e
LEFT JOIN (SELECT c.execution_id, SUM(c.quantity * m.standard_price_eur) AS cost_eur
           FROM mes.consumption c JOIN erp.materials m USING (material_id) GROUP BY 1) c USING (execution_id);

-- Genealogy: which stock lot went into which test run on which sample
CREATE VIEW analytics.stock_usage AS
SELECT c.batch_id, b.supplier_lot, m.name AS material, sp.name AS supplier, b.status AS batch_status,
       e.execution_id, e.keyword, e.status AS execution_status, e.start_ts, e.sample_id, s.plan_id,
       c.quantity, c.quantity * m.standard_price_eur AS cost_eur
FROM mes.consumption c
JOIN erp.stock_batches b USING (batch_id)
JOIN erp.materials m ON m.material_id = c.material_id
JOIN erp.suppliers sp ON sp.supplier_id = b.supplier_id
JOIN mes.executions e USING (execution_id)
JOIN lims.samples s ON s.sample_id = e.sample_id;

-- Where work sits: daily snapshot of open analyses by state, and each day an analysis was skipped
CREATE TABLE lims.daily_wip (day date, state text, open_analyses int);
CREATE TABLE lims.wait_events (day date, analysis_id text, sample_id text, keyword text, reason text, material_id text);

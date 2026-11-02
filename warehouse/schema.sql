-- One schema per source system, plus `analytics` views focused on sample throughput and people.
DROP SCHEMA IF EXISTS procurement, mes, lims, erp, qc, analytics CASCADE;
CREATE SCHEMA erp;
CREATE SCHEMA lims;
CREATE SCHEMA mes;
CREATE SCHEMA qc;
CREATE SCHEMA analytics;

-- ERP: process orders and sampling plans (demand), lab stock lots (availability for MES)
CREATE TABLE erp.materials (material_id text PRIMARY KEY, name text, material_type text, uom text, shelf_life_days int);
CREATE TABLE erp.process_orders (order_id bigint PRIMARY KEY, material_id text, product text, line text, order_date date,
  quantity int, uom text);
CREATE TABLE erp.sampling_plans (plan_id text, trigger text, material_id text, sample_type text, sample_point text,
  samples_per_trigger int, analyses text);
CREATE TABLE erp.stock_batches (batch_id text PRIMARY KEY, material_id text REFERENCES erp.materials, received_date date,
  expiry_date date, quantity_received numeric, quantity_on_hand numeric, status text);
CREATE TABLE erp.inventory_movements (movement_id text PRIMARY KEY, batch_id text REFERENCES erp.stock_batches,
  material_id text, movement_type text, quantity numeric, posted_ts timestamp, reference text);

-- LIMS (SENAITE): samples from sampling plans, predefined analyses, QC review
CREATE TABLE lims.specifications (keyword text PRIMARY KEY, test text, unit text, spec_min numeric, spec_max numeric);
CREATE TABLE lims.samples (sample_id text PRIMARY KEY, plan_id text, trigger text, trigger_ref text, material_id text,
  sample_type text, sample_point text, logged_ts timestamp, received_ts timestamp, results_complete_ts timestamp,
  review_start_ts timestamp, verified_ts timestamp, reviewer text, review_minutes int, status text, out_of_spec boolean,
  queued_hours numeric, in_test_hours numeric);
CREATE TABLE lims.analyses (analysis_id text PRIMARY KEY, sample_id text REFERENCES lims.samples, keyword text, test text,
  unit text, spec_min numeric, spec_max numeric, result numeric, out_of_spec boolean, status text,
  completed_ts timestamp, execution_id text);
CREATE TABLE lims.daily_wip (day date, state text, open_analyses int);
CREATE TABLE lims.wait_events (day date, analysis_id text, sample_id text, keyword text, reason text, material_id text);

-- MES: test protocol execution pushed from LIMS, and the lab stock each run consumed
CREATE TABLE mes.protocols (protocol_id text, keyword text PRIMARY KEY, analyst_minutes int, elapsed_minutes int,
  instrument text, lab_area text);
CREATE TABLE mes.protocol_materials (keyword text, material_id text, quantity_per_run numeric);
CREATE TABLE mes.executions (execution_id text PRIMARY KEY, analysis_id text REFERENCES lims.analyses,
  sample_id text, keyword text, protocol_id text, work_order_ts timestamp, analyst text, instrument text,
  start_ts timestamp, end_ts timestamp, standard_minutes int, actual_minutes int, status text, attempt int);
CREATE TABLE mes.consumption (execution_id text REFERENCES mes.executions, batch_id text REFERENCES erp.stock_batches,
  material_id text, quantity numeric, uom text);

-- QC people and their daily capacity
CREATE TABLE qc.people (person text PRIMARY KEY, role text, lab_area text, start_date date);
CREATE TABLE qc.person_days (day date, person text REFERENCES qc.people, role text, available_minutes int, booked_minutes int);

-- Every sample's journey, split into stages (hours)
CREATE VIEW analytics.sample_cycle AS
SELECT s.*,
       CASE WHEN s.plan_id LIKE 'SP-REL%' THEN 'Release' ELSE 'In-process' END AS kind,
       f.analysts, f.runs, f.aborted_runs, f.bench_minutes,
       EXTRACT(EPOCH FROM s.verified_ts - s.received_ts) / 3600 AS cycle_hours,
       s.queued_hours AS wait_for_analyst_hours,   -- received -> last result, minus time something was on test
       s.in_test_hours AS testing_hours,           -- bench work, instrument runs and micro incubation
       EXTRACT(EPOCH FROM s.review_start_ts - s.results_complete_ts) / 3600 AS wait_for_review_hours,
       s.review_minutes / 60.0 AS review_hours,
       EXTRACT(EPOCH FROM s.verified_ts - s.results_complete_ts) / 3600 AS time_to_confirm_hours
FROM lims.samples s
LEFT JOIN (SELECT sample_id, min(start_ts) AS first_start, string_agg(DISTINCT analyst, ', ') AS analysts,
                  count(*) AS runs, count(*) FILTER (WHERE status <> 'Completed') AS aborted_runs,
                  sum(actual_minutes) AS bench_minutes
           FROM mes.executions GROUP BY 1) f USING (sample_id);

-- Analyst runs with efficiency against the protocol standard
CREATE VIEW analytics.analyst_runs AS
SELECT e.*, p.lab_area, e.standard_minutes::numeric / NULLIF(e.actual_minutes, 0) AS efficiency,
       EXTRACT(EPOCH FROM e.start_ts - e.work_order_ts) / 3600 AS work_order_to_start_hours
FROM mes.executions e JOIN mes.protocols p USING (keyword);

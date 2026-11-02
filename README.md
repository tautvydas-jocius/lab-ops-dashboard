# Lab Ops Analytics

Open-source analytics for a pharmaceutical QC laboratory, joining **ERP**, **LIMS** and **MES** data in one Postgres warehouse, with [Metabase](https://www.metabase.com/) dashboards on top and a live connector for [SENAITE LIMS](https://www.senaite.com/).

The data comes from a day-by-day simulation of how a QC laboratory works with its systems:

- **ERP planning:** a released process order fires predefined **sampling plans**.
- **LIMS (SENAITE):** QC logs the samples with **predefined analyses and specifications**, then pushes each analysis to MES as a **work order**.
- **MES:** executes the **test protocol** using analyst time and an instrument. It **consumes lab stock lots** (solvents, reference standards, media, vials) from ERP inventory, oldest expiry first, and returns the result to LIMS.
- **LIMS, QC review:** QC verifies the sample in LIMS and the batch disposition goes back to ERP.
- **ERP procurement:** keeps lab stock topped up by reorder point (POs, goods receipts, stock lots). QC never talks to procurement; it only sees whether stock is available.

Turnaround and backlog are not random numbers. They come out of a first-in-first-out queue worked by real analyst capacity, so demand spikes, stock-outs and failed runs show up as delays.

## Integrations

![ERP, LIMS and MES integration sequence](docs/renders/0-integrations.png)

## Dashboards

### 1 · ERP: procurement & lab stock
![ERP dashboard](docs/renders/1-erp-procurement-lab-stock.png)

### 2 · LIMS: samples & quality
![LIMS dashboard](docs/renders/2-lims-samples-quality.png)

### 3 · MES: test execution
![MES dashboard](docs/renders/3-mes-test-execution.png)

### 4 · Where the lab stalls
Each evening the simulation records where every open analysis is sitting:
- waiting for an analyst
- waiting for stock
- repeating an aborted run
- in test or incubation
- done but waiting on the rest of its sample
- awaiting QA review

![Stall dashboard](docs/renders/4-where-the-lab-stalls.png)

### 5 · Cost per test (ERP × MES × LIMS)
Lab stock consumed by each MES run, valued at ERP standard price and rolled up per test, per sampling plan and per sample.
![Cost dashboard](docs/renders/5-cost-per-test-erp-mes-lims.png)

## Stories in the data

The generator (`--seed 42`) plants a few events for the dashboards to surface:

1. **Price rise:** acetonitrile, the HPLC solvent, rises about 35% in price from August. Procurement pays more, which shows up as purchase price variance (PPV) on lab stock.
2. **Bad media lot:** one TSA plate lot fails growth promotion in September. The TAMC and E. coli runs that used it are aborted and repeated in MES. After four failures the lot is blocked in ERP inventory, plates run short until the next delivery, and release turnaround climbs.
3. **Late reagent deliveries:** the Karl Fischer reagent supplier delivers late a quarter of the time, so water tests wait for stock.
4. **Volume spike:** tablet volume is up 50% in September, so chemistry analysts become the bottleneck.

## Data model

| Schema | Tables |
|---|---|
| `erp` | `suppliers`, `materials`, `purchase_orders`, `goods_receipts`, `stock_batches`, `inventory_movements`, `process_orders`, `sampling_plans` |
| `lims` | `specifications`, `samples`, `analyses`, `daily_wip`, `wait_events` |
| `mes` | `protocols`, `protocol_materials`, `executions` (with the LIMS work-order time), `consumption` |
| `analytics` | `po_performance`, `sample_tat`, `execution_cost`, `stock_usage` (lot → run → sample genealogy) |

## Run it

Requires Docker and Python 3.10+ (stdlib only, plus Playwright for renders).

```bash
python3 generate/generate.py                      # simulate, writes data/*.csv
echo "MB_ADMIN_PASSWORD=$(openssl rand -hex 12)" > .env
docker compose up -d                              # Postgres loads data/ on first start
set -a; . ./.env; set +a
python3 metabase/provision.py                     # admin user, connection, 5 dashboards
open http://127.0.0.1:3300                        # log in as admin@example.com

pip install playwright && playwright install chromium
python3 metabase/render.py                        # refresh docs/renders/*.png
```

Reload after regenerating: `docker compose exec db psql -U labops -f /warehouse/load.sql`

The integration diagram is built from `docs/diagrams/integrations.sequence.json` with [archify](https://github.com/tt-a1i/archify).

### Optional: SENAITE LIMS

`senaite/setup.py` creates the master data in a SENAITE 2.x site: lab, analysis services, specifications, sample points and client. `senaite/push.py` creates the most recent simulated samples there, with results submitted and verified. `senaite/extract.py` reads samples and analyses back through the JSON API into the same CSV columns as `lims_samples` and `lims_analyses`.

```bash
export SENAITE_URL=http://127.0.0.1:8080/senaite SENAITE_PASSWORD=...
python3 senaite/setup.py && python3 senaite/push.py --days 14 && python3 senaite/extract.py
```

SENAITE accepts backdated sampling and receipt dates. It stamps result capture and verification with the time of the push, so turnaround read back from a seeded SENAITE reflects the push, not the simulated timeline.

## License

GPL-3.0, see [LICENSE](LICENSE).

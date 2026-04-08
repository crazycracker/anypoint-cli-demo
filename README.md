# anypoint-cli-demo

Production-ready assets for MuleSoft observability in Kibana, with **live real-time data fetched from CloudHub APIs**.

## What is included

- `kibana/mulesoft-job-status-dashboard.ndjson` – dashboard + visualizations + data view
- `kibana/mulesoft-index-template.json` – Elasticsearch index template
- `kibana/sample-mulesoft-job-run.json` – normalized sample event
- `scripts/cloudhub_realtime_collector.py` – real-time CloudHub API collector -> Elasticsearch
- `.env.example` – environment configuration template

## Architecture (live)

1. Collector authenticates with Anypoint using **client_id/client_secret**.
2. Collector polls CloudHub APIs for:
   - all environments
   - all APIs in each environment
   - schedules (if available)
   - job/run history and current status
3. Collector normalizes events into `mulesoft-job-runs-*`.
4. Kibana dashboard reads the index in real time via time picker.

## 1) Configure credentials and endpoints

Copy `.env.example` and provide your real values:

```bash
cp .env.example .env
```

Set at minimum:

- `ANYPOINT_CLIENT_ID`
- `ANYPOINT_CLIENT_SECRET`
- `ANYPOINT_ORG_ID`
- `ELASTIC_URL`
- `ELASTIC_API_KEY`

You can also override endpoint templates if your tenant uses different CloudHub API routes.

## 2) Install index template

Install `kibana/mulesoft-index-template.json` into Elasticsearch before starting ingestion.

## 3) Run live collector

```bash
set -a
source .env
set +a
python3 scripts/cloudhub_realtime_collector.py
```

The collector continuously polls CloudHub and indexes new/updated runs.

## 4) Import Kibana assets

1. Kibana -> Stack Management -> Saved Objects
2. Import `kibana/mulesoft-job-status-dashboard.ndjson`
3. Open dashboard **MuleSoft Unified Job & Schedule Operations**
4. Use Kibana time picker to change live/historical window (15m, 1h, 24h, custom)

## Dashboard outcomes

The dashboard supports:

- Environment-wide visibility
- API-wide visibility inside each environment
- Schedule visibility + schedule health
- Live status (`RUNNING`, `FAILED`, `SUCCESS`, etc.)
- Historical failure and execution trends
- Top failed APIs/schedules
- Latest execution history table

## Recommended alerts

- `job.status:"FAILED"` in last 5m
- `schedule.status:"MISSED"` in last 15m
- Failure-rate spike threshold
- No-data alert for critical APIs
- SLA breach on `job.duration_ms`

## Notes

- The collector is endpoint-template driven so it can adapt to tenant-specific CloudHub API paths.
- If schedules are not exposed for an API, schedule fields are skipped automatically.

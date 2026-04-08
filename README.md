# anypoint-cli-demo

Production-ready Kibana assets to monitor **all MuleSoft environments, APIs, schedules, live status, and historical execution health**.

## What you get

This package is designed as an operations dashboard (NOC/SRE friendly) and includes:

- Global visibility across **all environments** (`dev`, `qa`, `uat`, `prod`, etc.)
- Visibility across **all APIs inside each environment**
- Visibility across **all schedules** in APIs (if present), including enabled/disabled state and run status
- **Live status** (running/failed/success) and **historical trends**
- Failure/error surfacing with top failing environments/APIs/jobs/schedules
- Time-window analysis using Kibana time picker (Last 15m, 1h, 24h, custom)
- Ready-to-create alerting recommendations

## Files

- `kibana/mulesoft-job-status-dashboard.ndjson`  
  Importable Kibana saved objects (data view + visualizations + dashboard).
- `kibana/sample-mulesoft-job-run.json`  
  Example event document for job/schedule execution.
- `kibana/mulesoft-index-template.json`  
  Suggested Elasticsearch index template for stable field mappings.

## Canonical index and data model

Index pattern:

- `mulesoft-job-runs-*`

Core fields:

- `@timestamp` (`date`) – event time
- `environment` (`keyword`) – env name
- `organization.id` (`keyword`) – Anypoint org
- `api.id` (`keyword`) / `api.name` (`keyword`)
- `job.id` (`keyword`) / `job.name` (`keyword`)
- `job.type` (`keyword`) – `SCHEDULED|ON_DEMAND|EVENT_DRIVEN`
- `job.status` (`keyword`) – `SUCCESS|RUNNING|FAILED|CANCELLED|RETRYING|MISSED`
- `job.duration_ms` (`long`)
- `schedule.id` (`keyword`) / `schedule.name` (`keyword`)
- `schedule.cron` (`keyword`)
- `schedule.enabled` (`boolean`)
- `schedule.status` (`keyword`) – `ON_TIME|LATE|MISSED|PAUSED`
- `error.code` (`keyword`) / `error.message` (`text`)
- `worker.id` (`keyword`) / `worker.region` (`keyword`)
- `trace.id` (`keyword`) – for deep debugging

## Dashboard panels included

The dashboard **MuleSoft Unified Job & Schedule Operations** includes:

1. Job Executions Over Time (split by status)
2. Failure Trend Over Time (FAILED only)
3. Environment Coverage (top environments)
4. API Coverage (top APIs)
5. Schedule Health Distribution (ON_TIME/LATE/MISSED/PAUSED)
6. Top Failed APIs
7. Top Failed Schedules
8. Latest Executions (table/search)

These panels are all time-filter aware, so changing Kibana’s time picker updates everything live.

## Import

1. Open **Kibana → Stack Management → Saved Objects**
2. Click **Import**
3. Upload `kibana/mulesoft-job-status-dashboard.ndjson`
4. Open dashboard: **MuleSoft Unified Job & Schedule Operations**

## Required ingestion behavior (important)

To truly show *all* environments/APIs/schedules:

- Emit one document per execution attempt (job run)
- Populate `environment`, `api.*`, and `job.*` always
- Populate `schedule.*` for scheduled jobs
- Emit failures with both `job.status="FAILED"` and `error.*`
- Emit schedule-monitor events for `MISSED` or `LATE` schedules even if no run occurred

## Suggested live filters

- Environment-specific:

```kql
environment : "prod"
```

- API-specific:

```kql
api.name : "customer-orders-api"
```

- Failing schedules:

```kql
job.status : "FAILED" or schedule.status : ("LATE" or "MISSED")
```

- Running right now:

```kql
job.status : "RUNNING"
```

## Alerts you should add (recommended)

1. **Failed job detection**  
   Query: `job.status:"FAILED"` in last 5m, condition `count > 0`
2. **Missed schedules**  
   Query: `schedule.status:"MISSED"` in last 15m, condition `count > 0`
3. **Failure-rate spike**  
   Rule based on ratio: FAILED / total > threshold (e.g. 5%)
4. **No data from critical API**  
   Rule on `api.name` with no docs in expected interval
5. **Long-running jobs**  
   Query on `job.duration_ms` > SLA threshold

## Additional improvements you may want (added as requested)

If you want full enterprise observability, also add:

- SLO widgets (success rate, p95/p99 duration)
- Deployment markers (overlay release versions)
- Retry visibility (`job.attempt`, `job.max_attempts`)
- Correlation from dashboard to logs/traces by `trace.id`
- Tenant-level breakdown if multi-tenant APIs are used
- Cost/performance panels by worker/region

This repository gives the base assets; once data is flowing with these fields, you’ll have live + historical operations visibility end to end.

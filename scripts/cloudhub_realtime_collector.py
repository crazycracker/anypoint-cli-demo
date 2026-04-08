#!/usr/bin/env python3
"""Poll CloudHub APIs in near real time and index normalized docs into Elasticsearch.

This collector is intentionally endpoint-template driven so you can point it to the
exact CloudHub/Anypoint endpoints available in your tenant.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


def env(name: str, default: Optional[str] = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value or ""


class HttpClient:
    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout

    def request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        body: Optional[bytes] = None,
    ) -> Any:
        req = urllib.request.Request(url=url, method=method, headers=headers or {}, data=body)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
                if not payload:
                    return {}
                return json.loads(payload)
        except urllib.error.HTTPError as exc:
            msg = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {exc.code} for {url}: {msg}") from exc


class CloudHubCollector:
    def __init__(self) -> None:
        self.client = HttpClient(timeout=int(env("HTTP_TIMEOUT_SECONDS", "30")))

        self.auth_url = env(
            "ANYPOINT_AUTH_URL",
            "https://anypoint.mulesoft.com/accounts/api/v2/oauth2/token",
        )
        self.base_url = env("ANYPOINT_BASE_URL", "https://anypoint.mulesoft.com")
        self.client_id = env("ANYPOINT_CLIENT_ID", required=True)
        self.client_secret = env("ANYPOINT_CLIENT_SECRET", required=True)
        self.org_id = env("ANYPOINT_ORG_ID", required=True)

        self.environments_api = env(
            "CLOUDHUB_ENVIRONMENTS_API",
            "/accounts/api/organizations/{org_id}/environments",
        )
        self.apis_api = env(
            "CLOUDHUB_APIS_API",
            "/cloudhub/api/v2/applications?environmentId={env_id}",
        )
        self.schedules_api = env(
            "CLOUDHUB_SCHEDULES_API",
            "/cloudhub/api/v2/applications/{app_name}/schedules?environmentId={env_id}",
        )
        self.runs_api = env(
            "CLOUDHUB_RUNS_API",
            "/cloudhub/api/v2/applications/{app_name}/jobs/runs?environmentId={env_id}&limit=200",
        )

        self.elastic_url = env("ELASTIC_URL", required=True).rstrip("/")
        self.elastic_api_key = env("ELASTIC_API_KEY", required=True)
        self.index_prefix = env("ELASTIC_INDEX_PREFIX", "mulesoft-job-runs")

        self.poll_seconds = int(env("POLL_INTERVAL_SECONDS", "30"))
        self.state_path = env("STATE_FILE", ".cloudhub_collector_state.json")
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, str]:
        if not os.path.exists(self.state_path):
            return {}
        with open(self.state_path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def _save_state(self) -> None:
        with open(self.state_path, "w", encoding="utf-8") as handle:
            json.dump(self.state, handle)

    def token(self) -> str:
        data = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        ).encode("utf-8")
        response = self.client.request(
            "POST",
            self.auth_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=data,
        )
        token = response.get("access_token")
        if not token:
            raise RuntimeError("No access_token in auth response")
        return token

    def _join_url(self, path_or_url: str, **params: str) -> str:
        rendered = path_or_url.format(**params)
        if rendered.startswith("http://") or rendered.startswith("https://"):
            return rendered
        return f"{self.base_url}{rendered}"

    def _get(self, bearer: str, url: str) -> Any:
        return self.client.request("GET", url, headers={"Authorization": f"Bearer {bearer}"})

    @staticmethod
    def _items(payload: Any) -> List[Dict[str, Any]]:
        if isinstance(payload, list):
            return [i for i in payload if isinstance(i, dict)]
        if isinstance(payload, dict):
            for key in ("data", "items", "applications", "schedules", "runs"):
                val = payload.get(key)
                if isinstance(val, list):
                    return [i for i in val if isinstance(i, dict)]
        return []

    def list_environments(self, bearer: str) -> List[Dict[str, Any]]:
        configured = [s.strip() for s in env("ANYPOINT_ENV_IDS", "").split(",") if s.strip()]
        if configured:
            return [{"id": env_id, "name": env_id} for env_id in configured]

        url = self._join_url(self.environments_api, org_id=self.org_id)
        payload = self._get(bearer, url)
        envs = self._items(payload)
        if not envs:
            raise RuntimeError("No environments returned. Set ANYPOINT_ENV_IDS or adjust CLOUDHUB_ENVIRONMENTS_API.")
        return envs

    def list_apis(self, bearer: str, env_id: str) -> List[Dict[str, Any]]:
        url = self._join_url(self.apis_api, org_id=self.org_id, env_id=env_id)
        return self._items(self._get(bearer, url))

    def list_schedules(self, bearer: str, env_id: str, app_name: str) -> List[Dict[str, Any]]:
        url = self._join_url(self.schedules_api, org_id=self.org_id, env_id=env_id, app_name=urllib.parse.quote(app_name, safe=""))
        try:
            return self._items(self._get(bearer, url))
        except Exception:
            return []

    def list_runs(self, bearer: str, env_id: str, app_name: str) -> List[Dict[str, Any]]:
        url = self._join_url(self.runs_api, org_id=self.org_id, env_id=env_id, app_name=urllib.parse.quote(app_name, safe=""))
        try:
            return self._items(self._get(bearer, url))
        except Exception:
            return []

    @staticmethod
    def _pick(item: Dict[str, Any], keys: Iterable[str], default: Any = None) -> Any:
        for key in keys:
            if key in item and item[key] is not None:
                return item[key]
        return default

    def normalize(self, env_obj: Dict[str, Any], app: Dict[str, Any], run: Dict[str, Any], schedule: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        ts = self._pick(run, ["timestamp", "startTime", "startedAt", "createdAt"]) or datetime.now(timezone.utc).isoformat()
        status = str(self._pick(run, ["status", "state", "result"], "UNKNOWN")).upper()
        duration = self._pick(run, ["durationMs", "duration", "executionTimeMs"], 0)

        doc = {
            "@timestamp": ts,
            "environment": self._pick(env_obj, ["name", "id"], "unknown"),
            "organization": {"id": self.org_id},
            "api": {
                "id": self._pick(app, ["id", "applicationId", "domain"]),
                "name": self._pick(app, ["name", "domain", "fullDomain"], "unknown-api"),
            },
            "job": {
                "id": self._pick(run, ["id", "runId", "executionId"]),
                "name": self._pick(run, ["name", "jobName"], self._pick(app, ["name", "domain"], "unknown-job")),
                "type": "SCHEDULED" if schedule else self._pick(run, ["type"], "ON_DEMAND"),
                "status": status,
                "duration_ms": int(duration) if str(duration).isdigit() else 0,
            },
            "worker": {
                "id": self._pick(run, ["workerId", "instanceId"]),
                "region": self._pick(app, ["region", "workerRegion"]),
            },
            "trace": {
                "id": self._pick(run, ["traceId", "correlationId"]),
            },
        }

        if schedule:
            doc["schedule"] = {
                "id": self._pick(schedule, ["id", "scheduleId"]),
                "name": self._pick(schedule, ["name"], "unknown-schedule"),
                "cron": self._pick(schedule, ["cron", "expression"]),
                "enabled": bool(self._pick(schedule, ["enabled", "isEnabled"], False)),
                "status": str(self._pick(schedule, ["status"], "UNKNOWN")).upper(),
            }

        error_msg = self._pick(run, ["errorMessage", "error", "message"])
        error_code = self._pick(run, ["errorCode", "code"])
        if status == "FAILED" or error_msg or error_code:
            doc["error"] = {
                "code": error_code or "UNKNOWN",
                "message": error_msg or "Execution failed",
            }

        return doc

    def _index_name(self) -> str:
        return f"{self.index_prefix}-{datetime.now(timezone.utc).strftime('%Y.%m.%d')}"

    def _bulk_index(self, docs: List[Dict[str, Any]]) -> None:
        if not docs:
            return
        index = self._index_name()
        lines: List[str] = []
        for doc in docs:
            lines.append(json.dumps({"index": {"_index": index}}))
            lines.append(json.dumps(doc))
        body = ("\n".join(lines) + "\n").encode("utf-8")

        headers = {
            "Authorization": f"ApiKey {self.elastic_api_key}",
            "Content-Type": "application/x-ndjson",
        }
        self.client.request("POST", f"{self.elastic_url}/_bulk", headers=headers, body=body)

    def run_once(self) -> int:
        bearer = self.token()
        docs: List[Dict[str, Any]] = []

        for env_obj in self.list_environments(bearer):
            env_id = str(self._pick(env_obj, ["id", "name"], ""))
            if not env_id:
                continue

            for app in self.list_apis(bearer, env_id):
                app_name = str(self._pick(app, ["name", "domain", "fullDomain"], ""))
                if not app_name:
                    continue

                schedules = self.list_schedules(bearer, env_id, app_name)
                runs = self.list_runs(bearer, env_id, app_name)

                for run in runs:
                    run_id = str(self._pick(run, ["id", "runId", "executionId"], ""))
                    if not run_id:
                        continue

                    state_key = f"{env_id}:{app_name}:{run_id}"
                    run_updated = str(self._pick(run, ["updatedAt", "lastUpdated", "timestamp", "startTime"], ""))
                    if self.state.get(state_key) == run_updated:
                        continue

                    schedule = schedules[0] if schedules else None
                    docs.append(self.normalize(env_obj, app, run, schedule))
                    self.state[state_key] = run_updated

        self._bulk_index(docs)
        self._save_state()
        return len(docs)

    def loop(self) -> None:
        print(f"Starting CloudHub collector. Poll interval: {self.poll_seconds}s", flush=True)
        while True:
            try:
                count = self.run_once()
                print(f"[{datetime.now(timezone.utc).isoformat()}] Indexed docs: {count}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"Collector error: {exc}", file=sys.stderr, flush=True)
            time.sleep(self.poll_seconds)


if __name__ == "__main__":
    CloudHubCollector().loop()

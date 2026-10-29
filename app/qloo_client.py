"""The only module that talks to Qloo. Caches responses in memory and enforces the call budget."""

import json

import requests

from app.config import Settings

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class QlooError(Exception):
    def __init__(self, status: int | None, path: str, detail: str):
        super().__init__(f"Qloo {path} failed ({status or 'no response'}): {detail}")
        self.status = status


class QlooBudgetExceeded(QlooError):
    def __init__(self, path: str, max_calls: int):
        super().__init__(None, path, f"call budget of {max_calls} used up")


class QlooClient:
    def __init__(self, settings: Settings, max_calls: int = 40, timeout: float = 15, retries: int = 1):
        self._base = settings.qloo_base_url
        self._session = requests.Session()
        self._session.headers["X-Api-Key"] = settings.qloo_api_key
        self._timeout = timeout
        self._retries = retries
        self._cache: dict[tuple, dict] = {}
        self.max_calls = max_calls
        self.calls = 0  # HTTP attempts, retries included; cache hits are free
        self.last_cached = False

    def search(self, query: str, point: str, take: int = 5) -> list[dict]:
        params = {"query": query, "types": "urn:entity:place", "filter.location": point, "take": take}
        return self._request("GET", "/search", params=params).get("results", [])

    def entities(self, entity_ids: list[str]) -> list[dict]:
        return self._request("GET", "/entities", params={"entity_ids": ",".join(entity_ids)}).get("results", [])

    def insights_get(self, params: dict) -> list[dict]:
        return (self._request("GET", "/v2/insights", params=params).get("results") or {}).get("entities", [])

    def insights_post(self, body: dict) -> list[dict]:
        return (self._request("POST", "/v2/insights", body=body).get("results") or {}).get("entities", [])

    def _request(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        key = (method, path, json.dumps(params or body, sort_keys=True))
        self.last_cached = key in self._cache
        if self.last_cached:
            return self._cache[key]

        status, detail = None, ""
        for _ in range(1 + self._retries):
            if self.calls >= self.max_calls:
                raise QlooBudgetExceeded(path, self.max_calls)
            self.calls += 1
            try:
                resp = self._session.request(
                    method, self._base + path, params=params, json=body, timeout=self._timeout
                )
            except requests.Timeout:
                status, detail = None, f"no reply within {self._timeout}s"
                continue
            except requests.ConnectionError as exc:
                status, detail = None, f"connection error: {str(exc)[:200]}"
                continue
            if resp.ok:
                self._cache[key] = resp.json()
                return self._cache[key]
            status, detail = resp.status_code, resp.text[:300]
            if status not in RETRYABLE_STATUS:
                break
        raise QlooError(status, path, detail)

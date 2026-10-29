"""Minimal client for any OpenAI-compatible /chat/completions endpoint (Gemini, DeepSeek, ...).

Plain requests instead of the openai package: Windows Application Control blocks
openai's compiled dependency (jiter) on the dev machine.
"""

import hashlib
import json
import re
import time
from dataclasses import dataclass

import requests

from app.cache import Cache
from app.config import Settings

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


@dataclass
class CallInfo:
    ms: int
    attempts: int
    cached: bool = False


class LLMError(Exception):
    def __init__(self, message: str, info: CallInfo):
        super().__init__(message)
        self.info = info


class LLM:
    def __init__(self, settings: Settings, timeout: float = 45, retries: int = 1,
                 cache: Cache | None = None, read_cache: bool = True):
        self._settings = settings
        self._timeout = timeout
        self._retries = retries
        self._cache = cache
        self._read_cache = read_cache
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {settings.llm_api_key}"

    @property
    def enabled(self) -> bool:
        return self._settings.llm_enabled

    def chat(self, prompt: str, system: str | None = None) -> tuple[str, CallInfo]:
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        body = {"model": self._settings.llm_model, "messages": messages, "reasoning_effort": "low"}
        url = f"{self._settings.llm_base_url}/chat/completions"
        key = hashlib.sha256(json.dumps([body["model"], messages]).encode()).hexdigest()
        if self._cache is not None and self._read_cache:
            hit, text = self._cache.get(key)
            if hit:
                return text, CallInfo(ms=0, attempts=0, cached=True)
        start = time.perf_counter()
        error = "LLM disabled (no key in .env)"
        attempts = 0
        while self.enabled and attempts <= self._retries:
            attempts += 1
            try:
                resp = self._session.post(url, json=body, timeout=self._timeout)
            except requests.Timeout:
                error = f"no reply within {self._timeout}s"
                continue
            except requests.ConnectionError as exc:
                error = f"connection error: {str(exc)[:200]}"
                continue
            if resp.ok:
                info = CallInfo(int((time.perf_counter() - start) * 1000), attempts)
                text = resp.json()["choices"][0]["message"]["content"] or ""
                if self._cache is not None:
                    self._cache.set(key, text)
                return text, info
            error = f"HTTP {resp.status_code}: {resp.text[:300]}"
            if resp.status_code not in RETRYABLE_STATUS:
                break
        raise LLMError(error, CallInfo(int((time.perf_counter() - start) * 1000), attempts))

    def chat_json(self, prompt: str, system: str | None = None) -> tuple[object, CallInfo]:
        """Like chat(), but parses the reply as JSON. Shape validation is the caller's job."""
        text, info = self.chat(prompt, system)
        try:
            return json.loads(FENCE_RE.sub("", text.strip())), info
        except json.JSONDecodeError as exc:
            raise LLMError(f"reply is not JSON ({exc.msg}): {text[:200]}", info) from exc

"""Explicitly configured OpenAI-compatible model client; never used by factor runner."""
from __future__ import annotations
import json
import os
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

class ModelError(RuntimeError):
    pass

def read_json_text(text: str) -> dict:
    if not isinstance(text, str):
        raise ModelError("expected a JSON text response")
    s = text.strip()
    fence = chr(96) * 3
    if s.startswith(fence):
        lines = s.splitlines()
        if len(lines) < 3 or lines[0].strip().lower() not in (fence, fence + "json") or lines[-1].strip() != fence:
            raise ModelError("invalid fenced JSON")
        s = "\n".join(lines[1:-1])
    try:
        obj = json.loads(s)
    except json.JSONDecodeError as exc:
        raise ModelError(f"model returned invalid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ModelError("model must return a JSON object")
    return obj

class ChatCompletionsClient:
    def __init__(self, *, base_url=None, api_key=None, model=None, timeout=90, json_mode=False):
        self.base_url = (base_url or os.getenv("TREEVO_LLM_BASE_URL") or "").rstrip("/")
        self.model = model or os.getenv("TREEVO_LLM_MODEL") or ""
        self.api_key = api_key if api_key is not None else os.getenv("TREEVO_LLM_API_KEY", "")
        if not self.model or not self.base_url:
            raise ModelError("configure TREEVO_LLM_BASE_URL and TREEVO_LLM_MODEL")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in ("https", "http") or not parsed.hostname:
            raise ModelError("invalid model API endpoint")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ModelError("model API URL cannot contain credentials/query/fragment")
        if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ModelError("remote HTTP not allowed: use HTTPS")
        if not 1 <= timeout <= 300:
            raise ModelError("timeout must be in 1..300 seconds")
        self.timeout, self.json_mode = timeout, json_mode

    def complete(self, system: str, user: str) -> dict:
        payload = {"model": self.model, "temperature": 0.2,
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        request = Request(self.base_url + "/chat/completions",
                          data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.timeout, context=ssl.create_default_context()) as response:
                data = response.read(512 * 1024 + 1)
        except HTTPError as exc:
            raise ModelError(f"chat completion returned HTTP status {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            raise ModelError(f"model endpoint unavailable: {type(exc).__name__}") from exc
        if len(data) > 512 * 1024:
            raise ModelError("model response too large")
        try:
            response = json.loads(data.decode("utf-8"))
            content = response["choices"][0]["message"]["content"]
        except (ValueError, IndexError, TypeError, KeyError) as exc:
            raise ModelError("missing completion content") from exc
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return read_json_text(content)

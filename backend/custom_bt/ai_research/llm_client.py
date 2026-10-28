from __future__ import annotations

import json
import os
import ssl
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib import request


DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"


@dataclass
class LLMResponse:
    content: str
    parsed: Any
    raw: dict[str, Any]
    model: str
    finish_reason: str = ""
    usage: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload["usage"] is None:
            payload["usage"] = {}
        return payload


def load_local_env(path: str | Path = ".env.local") -> dict[str, str]:
    """Read a simple KEY=VALUE env file without mutating process env."""

    env_path = Path(path)
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def resolve_llm_settings(
    config: Mapping[str, Any],
    env_path: str | Path = ".env.local",
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    local_env = load_local_env(env_path)
    process_env = os.environ if environ is None else environ
    merged_env = {**local_env, **dict(process_env)}
    llm_config = dict(config.get("llm", {}))

    provider = merged_env.get("AI_RESEARCH_LLM_PROVIDER") or llm_config.get("provider", "none")
    model = merged_env.get("AI_RESEARCH_LLM_MODEL") or llm_config.get("model") or DEFAULT_DEEPSEEK_MODEL
    if provider == "deepseek" and model == "none":
        model = DEFAULT_DEEPSEEK_MODEL

    return {
        "provider": provider,
        "model": model,
        "api_key": merged_env.get("DEEPSEEK_API_KEY", ""),
        "base_url": merged_env.get("DEEPSEEK_BASE_URL") or llm_config.get("base_url") or DEEPSEEK_BASE_URL,
        "ca_bundle": (
            merged_env.get("DEEPSEEK_CA_BUNDLE")
            or merged_env.get("AI_RESEARCH_CA_BUNDLE")
            or merged_env.get("SSL_CERT_FILE")
            or merged_env.get("REQUESTS_CA_BUNDLE")
            or llm_config.get("ca_bundle")
            or ""
        ),
        "temperature": float(llm_config.get("temperature", 0.2)),
        "top_p": float(llm_config.get("top_p", 1.0)),
        "timeout_seconds": int(llm_config.get("timeout_seconds", 120)),
    }


def _certifi_bundle_path() -> str:
    try:
        import certifi
    except ImportError:
        return ""
    return str(certifi.where() or "")


def create_https_context(ca_bundle: str | Path | None = None) -> ssl.SSLContext:
    """Create an HTTPS context without depending on the Windows cert store.

    Some Windows Python/Conda environments fail while loading the OS certificate
    store with ASN1 parsing errors. Supplying a CA file, preferably certifi's
    bundle, avoids that path while preserving certificate verification.
    """

    candidates: list[str] = []
    if ca_bundle:
        candidates.append(str(Path(ca_bundle).expanduser()))
    certifi_bundle = _certifi_bundle_path()
    if certifi_bundle and certifi_bundle not in candidates:
        candidates.append(certifi_bundle)

    errors: list[str] = []
    for candidate in candidates:
        try:
            return ssl.create_default_context(cafile=candidate)
        except (OSError, ssl.SSLError) as exc:
            errors.append(f"{candidate}: {exc}")

    try:
        return ssl.create_default_context()
    except ssl.SSLError as exc:
        if errors:
            raise ssl.SSLError(
                "could not create HTTPS SSL context; "
                + "; ".join(errors)
                + f"; default context: {exc}"
            ) from exc
        raise


def parse_json_content(content: str) -> Any:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM response content is not valid JSON") from exc


class DeepSeekChatClient:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_DEEPSEEK_MODEL,
        base_url: str = DEEPSEEK_BASE_URL,
        temperature: float = 0.2,
        top_p: float = 1.0,
        timeout_seconds: int = 120,
        ca_bundle: str | Path | None = None,
        opener: Callable[..., Any] | None = None,
    ):
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is required for DeepSeek provider")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.top_p = top_p
        self.timeout_seconds = timeout_seconds
        self._ssl_context = None if opener else create_https_context(ca_bundle)
        self._opener = opener or self._urlopen

    def complete_json(self, prompt: str, system_prompt: str | None = None) -> LLMResponse:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "stream": False,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with self._opener(req, timeout=self.timeout_seconds) as response:
            raw = json.loads(response.read().decode("utf-8"))

        choices = raw.get("choices") or []
        if not choices:
            raise ValueError("DeepSeek response did not include choices")
        first = choices[0]
        content = str(first.get("message", {}).get("content", ""))
        return LLMResponse(
            content=content,
            parsed=parse_json_content(content),
            raw=raw,
            model=str(raw.get("model") or self.model),
            finish_reason=str(first.get("finish_reason", "")),
            usage=dict(raw.get("usage") or {}),
        )

    def _urlopen(self, req: request.Request, timeout: int) -> Any:
        return request.urlopen(req, timeout=timeout, context=self._ssl_context)


def create_llm_client(
    config: Mapping[str, Any],
    env_path: str | Path = ".env.local",
    environ: Mapping[str, str] | None = None,
) -> DeepSeekChatClient:
    settings = resolve_llm_settings(config, env_path=env_path, environ=environ)
    provider = settings["provider"]
    if provider != "deepseek":
        raise ValueError(f"unsupported llm provider: {provider}")
    return DeepSeekChatClient(
        api_key=settings["api_key"],
        model=settings["model"],
        base_url=settings["base_url"],
        temperature=settings["temperature"],
        top_p=settings["top_p"],
        timeout_seconds=settings["timeout_seconds"],
        ca_bundle=settings["ca_bundle"],
    )

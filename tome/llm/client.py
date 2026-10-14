"""OpenAI-compatible chat client (OpenRouter, vLLM, llama.cpp, Ollama).

A client is always bound to one series, and the provider policy is checked
when the client is created and again before every request, so text from a
copyrighted series cannot reach a provider it is not allowed to use.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

import httpx
import jsonschema

from tome.llm.policy import check_provider
from tome.llm.providers import Provider
from tome.llm.usage import UsageLog, UsageRecord, now
from tome.series import Series


class LLMError(RuntimeError):
    pass


class StructuredOutputError(LLMError):
    pass


@dataclass
class ChatResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None
    raw: dict


class ChatClient:
    def __init__(
        self,
        provider: Provider,
        series: Series,
        *,
        model: str | None = None,
        usage: UsageLog | None = None,
        http: httpx.Client | None = None,
        timeout: float = 120.0,
    ):
        check_provider(series, provider)
        self.provider = provider
        self.series = series
        self.model = model or provider.default_model
        if not self.model:
            raise LLMError(f"no model given and provider {provider.name!r} has no default")
        self.usage = usage if usage is not None else UsageLog()
        self._http = http or httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------
    def chat(
        self,
        messages: list[dict],
        *,
        purpose: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        response_format: dict | None = None,
        model: str | None = None,
    ) -> ChatResult:
        check_provider(self.series, self.provider)  # re-check on every call
        model = model or self.model
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **self.provider.extra_body,
        }
        if response_format is not None:
            body["response_format"] = response_format
        headers = {"Authorization": f"Bearer {self.provider.api_key()}", "X-Title": "tome"}
        started = time.monotonic()
        try:
            resp = self._http.post(
                f"{self.provider.base_url.rstrip('/')}/chat/completions", json=body, headers=headers
            )
            if resp.status_code >= 400:
                raise LLMError(f"{self.provider.name} HTTP {resp.status_code}: {resp.text[:500]}")
            data = resp.json()
            text = data["choices"][0]["message"].get("content") or ""
        except (httpx.HTTPError, LLMError, KeyError, IndexError, ValueError) as exc:
            self._log(model, purpose, {}, time.monotonic() - started, error=str(exc))
            raise exc if isinstance(exc, LLMError) else LLMError(str(exc)) from exc
        usage = data.get("usage") or {}
        self._log(data.get("model", model), purpose, usage, time.monotonic() - started)
        return ChatResult(
            text,
            data.get("model", model),
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            usage.get("cost"),
            data,
        )

    def _log(self, model, purpose, usage: dict, latency: float, error: str | None = None):
        pt, ct = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        self.usage.add(
            UsageRecord(
                ts=now(),
                provider=self.provider.name,
                model=model,
                series=self.series.id,
                purpose=purpose,
                prompt_tokens=pt,
                completion_tokens=ct,
                total_tokens=usage.get("total_tokens", pt + ct),
                cost_usd=usage.get("cost"),
                latency_s=round(latency, 3),
                ok=error is None,
                error=error,
            )
        )

    # ------------------------------------------------------------------
    def structured(
        self, messages: list[dict], schema: dict, *, name: str, purpose: str, retries: int = 1, **kw
    ) -> dict:
        """Chat, constrained to ``schema`` where the server supports it, then validate.

        Falls back to describing the schema in the prompt for servers without
        json_schema support, and retries once with the validation error.
        """
        messages = list(messages)
        use_schema = self.provider.supports_json_schema
        last_error = None
        for _attempt in range(retries + 1):
            if use_schema:
                fmt = {
                    "type": "json_schema",
                    "json_schema": {"name": name, "strict": True, "schema": schema},
                }
                msgs = messages
            else:
                fmt = None
                msgs = [*messages, {"role": "user", "content": schema_instruction(schema)}]
            try:
                result = self.chat(msgs, purpose=purpose, response_format=fmt, **kw)
            except LLMError as exc:
                if use_schema and "response_format" in str(exc).lower():
                    use_schema = False  # server rejected json_schema; retry via prompt
                    last_error = str(exc)
                    continue
                raise
            try:
                value = extract_json(result.text)
                jsonschema.validate(value, schema)
                return value
            except (ValueError, jsonschema.ValidationError) as exc:
                last_error = exc.message if hasattr(exc, "message") else str(exc)
                messages = [
                    *messages,
                    {"role": "assistant", "content": result.text},
                    {
                        "role": "user",
                        "content": "That did not match the JSON schema: "
                        f"{last_error}. Reply with corrected JSON only.",
                    },
                ]
        raise StructuredOutputError(f"no valid {name} after {retries + 1} attempts: {last_error}")


def schema_instruction(schema: dict) -> str:
    return (
        "Reply with a single JSON value and nothing else. It must validate against "
        f"this JSON schema:\n{json.dumps(schema)}"
    )


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


def extract_json(text: str):
    text = text.strip()
    m = _FENCE.match(text)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
        if start < 0:
            raise ValueError("no JSON found in response") from None
        value, _ = json.JSONDecoder().raw_decode(text[start:])
        return value

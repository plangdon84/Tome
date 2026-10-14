import json

import httpx
import pytest

from tome.llm.client import ChatClient, StructuredOutputError, extract_json
from tome.llm.policy import ProviderNotAllowed, check_provider
from tome.llm.providers import PLACEHOLDER_KEY, PRESETS, Provider, get_provider
from tome.llm.usage import UsageLog
from tome.series import Series

PD = Series("monte-cristo", "MC", "public_domain", ("openrouter", "vllm-local"))
HP = Series("harry-potter", "HP", "copyrighted", ("vllm-local", "openrouter", "rogue"))


# ------------------------------------------------------------------ policy --


def test_public_domain_may_use_listed_third_party_api():
    check_provider(PD, PRESETS["openrouter"])
    check_provider(PD, PRESETS["vllm-local"])


def test_unlisted_provider_is_refused_even_for_public_domain():
    with pytest.raises(ProviderNotAllowed, match="not in the allowed list"):
        check_provider(PD, PRESETS["ollama-local"])


def test_copyrighted_series_refuses_third_party_api_even_if_listed():
    with pytest.raises(ProviderNotAllowed, match="third-party AI API"):
        check_provider(HP, PRESETS["openrouter"])


def test_copyrighted_series_refuses_mislabelled_third_party_host():
    rogue = Provider("rogue", "https://api.openai.com/v1", "self_hosted")
    with pytest.raises(ProviderNotAllowed, match="third-party"):
        check_provider(HP, rogue)


@pytest.mark.parametrize(
    "url,ok",
    [
        ("http://localhost:8000/v1", True),
        ("http://127.0.0.1:8000/v1", True),
        ("http://10.0.3.7:8000/v1", True),
        ("http://[::1]:8000/v1", True),
        ("https://8.8.8.8/v1", False),
        ("https://gpu.example.com/v1", False),
    ],
)
def test_copyrighted_series_needs_a_private_address(url, ok):
    provider = PRESETS["vllm-local"].with_overrides(base_url=url)
    if ok:
        check_provider(HP, provider)
    else:
        with pytest.raises(ProviderNotAllowed, match="not a local/private"):
            check_provider(HP, provider)


def test_copyrighted_series_can_name_its_pod_host():
    hp = Series("hp", "HP", "copyrighted", ("vllm-local",), ("pod.tailnet.ts.net",))
    check_provider(
        hp, PRESETS["vllm-local"].with_overrides(base_url="http://pod.tailnet.ts.net/v1")
    )


def test_copyrighted_series_refuses_non_self_hosted_provider():
    hosted = Provider("rogue", "http://localhost:9999/v1", "third_party")
    with pytest.raises(ProviderNotAllowed, match="not self-hosted"):
        check_provider(HP, hosted)


def test_series_default_rights_are_copyrighted(tmp_path):
    f = tmp_path / "x.toml"
    f.write_text('id = "x"\nallowed_providers = ["openrouter"]\n')
    s = Series.load(f)
    assert s.rights == "copyrighted"
    with pytest.raises(ProviderNotAllowed):
        check_provider(s, PRESETS["openrouter"])


def test_committed_series_configs_are_public_domain():
    s = Series.find("monte-cristo")
    assert s.is_public_domain


def test_client_refuses_at_construction_and_on_every_call():
    with pytest.raises(ProviderNotAllowed):
        ChatClient(PRESETS["openrouter"], HP, usage=UsageLog(path=None))

    calls = []
    http = httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(r)))
    client = ChatClient(PRESETS["vllm-local"], HP, model="m", usage=UsageLog(path=None), http=http)
    client.provider = PRESETS["openrouter"]  # swapped after construction
    with pytest.raises(ProviderNotAllowed):
        client.chat([{"role": "user", "content": "chapter text"}], purpose="test")
    assert calls == []  # nothing left the process


# ------------------------------------------------------------------ client --


def completion(content: str, *, usage=None, model="m") -> dict:
    return {
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": usage
        or {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14, "cost": 0.00001},
    }


def mock_client(handler, provider="openrouter", series=PD, tmp_path=None, model=None):
    usage = UsageLog(path=tmp_path / "usage.jsonl" if tmp_path else None)
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return ChatClient(PRESETS[provider], series, model=model, usage=usage, http=http), usage


def test_chat_request_shape_auth_placeholder_and_usage_log(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=completion("hello"))

    client, usage = mock_client(handler, tmp_path=tmp_path)
    out = client.chat([{"role": "user", "content": "hi"}], purpose="smoke")
    assert out.text == "hello" and out.prompt_tokens == 11 and out.cost_usd == 0.00001
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["auth"] == f"Bearer {PLACEHOLDER_KEY}"
    assert seen["body"]["model"] == PRESETS["openrouter"].default_model
    assert seen["body"]["usage"] == {"include": True}
    logged = [json.loads(line) for line in (tmp_path / "usage.jsonl").read_text().splitlines()]
    assert logged[0]["prompt_tokens"] == 11 and logged[0]["purpose"] == "smoke"
    assert logged[0]["series"] == "monte-cristo"
    assert usage.prompt_tokens == 11 and usage.completion_tokens == 3


def test_real_api_key_is_used_when_set(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-real")
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json=completion("x"))

    client, _ = mock_client(handler)
    client.chat([{"role": "user", "content": "hi"}], purpose="t")
    assert seen["auth"] == "Bearer sk-or-real"


def test_errors_are_logged(tmp_path):
    client, usage = mock_client(lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(Exception, match="HTTP 500"):
        client.chat([{"role": "user", "content": "hi"}], purpose="t")
    assert usage.records[-1].ok is False


SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
    "additionalProperties": False,
}


def test_structured_uses_json_schema_and_validates():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=completion('```json\n{"name": "Dantès"}\n```'))

    client, _ = mock_client(handler)
    assert client.structured(
        [{"role": "user", "content": "q"}], SCHEMA, name="person", purpose="t"
    ) == {"name": "Dantès"}
    assert seen[0]["response_format"]["type"] == "json_schema"
    assert seen[0]["response_format"]["json_schema"]["schema"] == SCHEMA


def test_structured_retries_on_invalid_then_succeeds():
    replies = iter(['{"nom": 1}', '{"name": "Faria"}'])
    client, usage = mock_client(lambda r: httpx.Response(200, json=completion(next(replies))))
    assert (
        client.structured([{"role": "user", "content": "q"}], SCHEMA, name="p", purpose="t")["name"]
        == "Faria"
    )
    assert len(usage.records) == 2


def test_structured_falls_back_when_server_rejects_response_format():
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if "response_format" in body:
            return httpx.Response(400, text="response_format json_schema not supported")
        return httpx.Response(200, json=completion('{"name": "Mercédès"}'))

    client, _ = mock_client(handler, provider="vllm-local", model="m")
    assert client.structured([{"role": "user", "content": "q"}], SCHEMA, name="p", purpose="t") == {
        "name": "Mercédès"
    }
    assert "JSON schema" in seen[-1]["messages"][-1]["content"]


def test_structured_gives_up():
    client, _ = mock_client(lambda r: httpx.Response(200, json=completion("no json here")))
    with pytest.raises(StructuredOutputError):
        client.structured([{"role": "user", "content": "q"}], SCHEMA, name="p", purpose="t")


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('Sure! {"a": [1, 2]} hope that helps') == {"a": [1, 2]}
    with pytest.raises(ValueError):
        extract_json("nothing")


def test_provider_base_url_override(monkeypatch):
    monkeypatch.setenv("TOME_VLLM_LOCAL_BASE_URL", "http://127.0.0.1:9000/v1")
    assert get_provider("vllm-local").base_url == "http://127.0.0.1:9000/v1"


# -------------------------------------------------------------- live smoke --


@pytest.mark.live
def test_live_openrouter_smoke(tmp_path):
    """One tiny call to a cheap open-weight model (~$0.00001). Run with --run-live."""
    usage = UsageLog(path=tmp_path / "usage.jsonl")
    client = ChatClient(get_provider("openrouter"), PD, usage=usage)
    out = client.structured(
        [
            {"role": "system", "content": "You extract facts. Answer only from the text."},
            {
                "role": "user",
                "content": "Text: 'Ah, is it you, Dantès?' cried the man in the "
                "skiff. Who is being addressed? Give just the name.",
            },
        ],
        SCHEMA,
        name="person",
        purpose="smoke",
        max_tokens=50,
    )
    assert "dant" in out["name"].lower()
    rec = usage.records[-1]
    assert rec.ok and rec.prompt_tokens > 0 and rec.completion_tokens > 0
    print(
        f"\nlive smoke: model={rec.model} tokens={rec.prompt_tokens}+{rec.completion_tokens}"
        f" cost=${rec.cost_usd}"
    )

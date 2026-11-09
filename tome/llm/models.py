"""Per-model request settings: thinking mode and reasoning headroom.

Some candidate models reason before they answer. Reasoning must never reach a
summary, and it must not eat the token limit a summary is checked against, so
each family gets the switch that works for it on each kind of server:

- **Qwen3 (dense, e.g. Qwen3-14B, Qwen3-32B):** thinking off with the ``/no_think``
  soft switch at the end of the system prompt. It works on every server, since
  it is plain prompt text read by the chat template. OpenRouter's
  ``reasoning: {"enabled": false}`` did *not* turn it off on DeepInfra
  (2026-11-08), and neither did ``chat_template_kwargs``.
- **Qwen3.5:** no soft switch. On OpenRouter ``reasoning: {"enabled": false}``
  works on every host tried; vLLM reads ``chat_template_kwargs`` directly.
- **gpt-oss:** reasoning can't be turned off, only lowered. Low effort, plus
  headroom on ``max_tokens``, which counts reasoning tokens on both OpenRouter
  and vLLM.

Model ids are matched loosely, so the OpenRouter id (``qwen/qwen3-14b``) and the
Hugging Face id served by vLLM (``Qwen/Qwen3-14B-AWQ``) get the same settings.
Whatever the switch, the client also strips any ``<think>`` block from a reply.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Extra max_tokens for a model that always reasons. Low effort used tens to a
# few hundred tokens on a chapter; this leaves the reply its full budget.
REASONING_HEADROOM = 2048


@dataclass(frozen=True)
class ModelTraits:
    system_suffix: str = ""  # appended to the system message
    openrouter_body: dict = field(default_factory=dict)  # extra request fields, OpenRouter
    vllm_body: dict = field(default_factory=dict)  # extra request fields, vLLM
    reasoning_headroom: int = 0  # added to max_tokens

    def extra_body(self, dialect: str) -> dict:
        return {"openrouter": self.openrouter_body, "vllm": self.vllm_body}.get(dialect, {})


PLAIN = ModelTraits()
QWEN3 = ModelTraits(
    system_suffix="\n\n/no_think",
    vllm_body={"chat_template_kwargs": {"enable_thinking": False}},
)
QWEN3_5 = ModelTraits(
    openrouter_body={"reasoning": {"enabled": False}},
    vllm_body={"chat_template_kwargs": {"enable_thinking": False}},
)
GPT_OSS = ModelTraits(
    openrouter_body={"reasoning": {"effort": "low", "exclude": True}},
    vllm_body={"reasoning_effort": "low"},
    reasoning_headroom=REASONING_HEADROOM,
)

_RULES = [
    (re.compile(r"qwen3\.5"), QWEN3_5),
    # Qwen3 dense and MoE, but not the 2507 Instruct models, which never think.
    (re.compile(r"qwen3-(?!.*instruct-2507)\d"), QWEN3),
    (re.compile(r"gpt-oss"), GPT_OSS),
]


def traits_for(model: str) -> ModelTraits:
    name = model.lower()
    for pattern, traits in _RULES:
        if pattern.search(name):
            return traits
    return PLAIN


_THINK = re.compile(r"^\s*<think>.*?</think>\s*", re.S)


def strip_reasoning(text: str) -> str:
    """``text`` without a leading ``<think>...</think>`` block, as some servers leave one."""
    return _THINK.sub("", text, count=1)

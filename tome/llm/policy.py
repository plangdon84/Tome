"""Which providers may see which series' text. Enforced on every call.

Rule (DECISIONS.md §2): copyrighted books go only to open-weight models on
hardware we rent. In code that means a copyrighted series may only use a
provider that is

1. listed in the series' ``allowed_providers``,
2. marked ``self_hosted``, and
3. reachable at a loopback/private address (or a host the series config
   names explicitly), and never at a known AI-company API host.

Public-domain series only need (1).
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from tome.llm.providers import Provider
from tome.series import Series

THIRD_PARTY_API_HOSTS = (
    "openrouter.ai",
    "api.openai.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
    "api.mistral.ai",
    "api.together.xyz",
    "api.groq.com",
    "api.deepseek.com",
    "api.fireworks.ai",
    "api.cohere.com",
    "api.x.ai",
    "api.perplexity.ai",
)


class ProviderNotAllowed(PermissionError):
    pass


def _host_is_private(host: str) -> bool:
    if host in ("localhost",) or host.endswith(".localhost") or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def check_provider(series: Series, provider: Provider) -> None:
    """Raise ProviderNotAllowed unless ``provider`` may process ``series``."""
    if provider.name not in series.allowed_providers:
        raise ProviderNotAllowed(
            f"provider {provider.name!r} is not in the allowed list for series "
            f"{series.id!r}: {list(series.allowed_providers)}"
        )
    if series.is_public_domain:
        return
    host = (urlparse(provider.base_url).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in THIRD_PARTY_API_HOSTS):
        raise ProviderNotAllowed(
            f"series {series.id!r} is copyrighted; {host} is a third-party AI API"
        )
    if provider.hosting != "self_hosted":
        raise ProviderNotAllowed(
            f"series {series.id!r} is copyrighted; provider {provider.name!r} is not self-hosted"
        )
    if not (_host_is_private(host) or host in series.self_hosted_hosts):
        raise ProviderNotAllowed(
            f"series {series.id!r} is copyrighted; {host!r} is not a local/private address "
            "or a host listed in the series' self_hosted_hosts"
        )

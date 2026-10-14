"""Per-series configuration, including which LLM providers may see its text.

Series files are TOML. Public-domain series are committed under ``series/``;
copyrighted series live in the gitignored ``library/series/``.

    id = "monte-cristo"
    title = "The Count of Monte Cristo"
    rights = "public_domain"          # or "copyrighted" (the default)
    allowed_providers = ["openrouter", "vllm-local"]
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

RIGHTS = ("public_domain", "copyrighted")
SEARCH_DIRS = (Path("series"), Path("library") / "series")


@dataclass(frozen=True)
class Series:
    id: str
    title: str
    rights: str = "copyrighted"
    allowed_providers: tuple[str, ...] = ()
    # Extra hostnames that count as self-hosted for this series (e.g. a pod's
    # private tunnel name). Known AI-company API hosts are refused regardless.
    self_hosted_hosts: tuple[str, ...] = field(default=())

    def __post_init__(self):
        if self.rights not in RIGHTS:
            raise ValueError(f"series {self.id}: rights must be one of {RIGHTS}")

    @property
    def is_public_domain(self) -> bool:
        return self.rights == "public_domain"

    @classmethod
    def load(cls, path: str | Path) -> Series:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            id=data["id"],
            title=data.get("title", data["id"]),
            # Anything not explicitly public domain is treated as copyrighted.
            rights=data.get("rights", "copyrighted"),
            allowed_providers=tuple(data.get("allowed_providers", ())),
            self_hosted_hosts=tuple(data.get("self_hosted_hosts", ())),
        )

    @classmethod
    def find(cls, series_id: str, dirs=SEARCH_DIRS) -> Series:
        for d in dirs:
            path = Path(d) / f"{series_id}.toml"
            if path.exists():
                return cls.load(path)
        raise FileNotFoundError(f"no series config {series_id}.toml in {[str(d) for d in dirs]}")

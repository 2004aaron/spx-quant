"""Tagged parameter loading. Every parameter carries a validation tag and a source."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "params.toml"
TAGS = {"validated", "unvalidated", "unvalidated: tested, not supported", "unvalidated: partially supported"}


class MissingParam(KeyError):
    def __init__(self, name: str):
        super().__init__(name)
        self.name = name

    def __str__(self) -> str:
        return f"required parameter '{self.name}' is not configured in params.toml"


@dataclass(frozen=True)
class Params:
    sections: dict
    provenance: dict

    def __getattr__(self, name: str) -> dict:
        sections = self.__dict__.get("sections", {})
        if name.startswith("__") or name not in sections:
            raise AttributeError(name)
        return sections[name]

    def need(self, section: str, key: str):
        try:
            return self.sections[section][key]
        except KeyError:
            raise MissingParam(f"{section}.{key}") from None

    def tag(self, name: str) -> str:
        return self.provenance.get(name, {}).get("tag", "untagged")

    def summary(self) -> str:
        counts: dict[str, int] = {}
        for meta in self.provenance.values():
            counts[meta["tag"]] = counts.get(meta["tag"], 0) + 1
        return "Parameters: " + ", ".join(f"{n} {tag}" for tag, n in sorted(counts.items()))


def load_params(path: Path | str = DEFAULT_PATH) -> Params:
    raw = tomllib.loads(Path(path).read_text())
    prov = raw.pop("provenance", {})
    values = {f"{section}.{key}" for section, block in raw.items() for key in block}
    untagged = sorted(values - prov.keys())
    if untagged:
        raise ValueError(f"untagged parameters: {', '.join(untagged)}")
    bad = sorted(k for k, m in prov.items() if k in values and (m.get("tag") not in TAGS or not m.get("source")))
    if bad:
        raise ValueError(f"parameters with invalid tag or missing source: {', '.join(bad)}")
    return Params(raw, {k: m for k, m in prov.items() if k in values})

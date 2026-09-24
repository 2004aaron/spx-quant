"""Tagged parameter loading (US-12). Every parameter carries a validation tag and a source."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "params.toml"
TAGS = {"validated", "unvalidated", "unvalidated: tested, not supported", "unvalidated: partially supported"}


@dataclass(frozen=True)
class Params:
    regime: dict
    vol_buckets: dict
    strangle: dict
    liquidity: dict
    feed: dict
    provenance: dict

    def summary(self) -> str:
        counts: dict[str, int] = {}
        for meta in self.provenance.values():
            counts[meta["tag"]] = counts.get(meta["tag"], 0) + 1
        return "Parameters: " + ", ".join(f"{n} {tag}" for tag, n in sorted(counts.items()))


def load_params(path: Path | str = DEFAULT_PATH) -> Params:
    raw = tomllib.loads(Path(path).read_text())
    prov = raw.pop("provenance", {})
    values = {f"{section}.{key}": v for section, block in raw.items() for key, v in block.items()}
    untagged = sorted(k for k in values if k not in prov)
    if untagged:
        raise ValueError(f"untagged parameters: {', '.join(untagged)}")
    bad = sorted(k for k, m in prov.items() if m.get("tag") not in TAGS or not m.get("source"))
    if bad:
        raise ValueError(f"parameters with invalid tag or missing source: {', '.join(bad)}")
    return Params(**raw, provenance=prov)

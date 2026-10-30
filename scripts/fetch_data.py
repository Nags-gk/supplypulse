"""Download the DataCo Smart Supply Chain dataset (pinned mirror commit) and verify its size/rows.

Source of record: Constante, Silva & Pereira (2019), "DataCo SMART SUPPLY CHAIN FOR BIG DATA
ANALYSIS", Mendeley Data, licensed CC BY 4.0. This script pulls a GitHub mirror pinned to a commit
so builds are reproducible. The raw file (~96 MB) is never committed to this repo.
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

MIRROR = (
    "https://raw.githubusercontent.com/ashishpatel26/DataCo-SMART-SUPPLY-CHAIN-FOR-BIG-DATA-ANALYSIS/"
    "7a466e7a4e9a8705c9b7b081dc081d2d16907fbc"
)
FILES = {
    "DataCoSupplyChainDataset.csv": 95_729_629,  # expected bytes
    "DescriptionDataCoSupplyChain.csv": 3_391,
}
EXPECTED_LINES = 180_520  # header + 180,519 order lines


def main(dest: str = "data/raw") -> int:
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    for name, size in FILES.items():
        target = out / name
        if target.exists() and target.stat().st_size == size:
            print(f"ok (cached) {target}")
            continue
        print(f"downloading {name} ...")
        urllib.request.urlretrieve(f"{MIRROR}/{name}", target)
        if target.stat().st_size != size:
            print(f"size mismatch for {name}: {target.stat().st_size} != {size}", file=sys.stderr)
            return 1
    with open(out / "DataCoSupplyChainDataset.csv", "rb") as fh:
        lines = sum(1 for _ in fh)
    if lines != EXPECTED_LINES:
        print(f"unexpected line count {lines} != {EXPECTED_LINES}", file=sys.stderr)
        return 1
    print("dataset verified")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))

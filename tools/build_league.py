"""
Build a league from a Cricsheet CSV2 zip into data/leagues/<slug>/.

    python tools/build_league.py raw/ilt20_male_csv2.zip "International League T20" ILT20

The same thing the site's Admin → Add a league page does, for building on a computer.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import build_league, save  # noqa: E402


def main(zip_path: str, name: str, short: str) -> None:
    t = time.time()
    tables, meta = build_league(zip_path, name=name, short=short,
                                progress=lambda f, s: print(f"  {f:4.0%}  {s}"))
    out = save(tables, meta)
    print(f"{meta['name']}: {meta['matches']} matches, seasons {meta['seasons'][0]}–{meta['seasons'][-1]} → {out}"
          f"  ({time.time() - t:.0f}s)")
    print({k: v for k, v in meta.items() if k.startswith("has_")})


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])

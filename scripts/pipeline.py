"""
Build step: inject the latest screen output into the template and write the
GitHub Pages output.

    template.html + data/candidates.json  ->  docs/index.html

Run after a screen:
    python run_screen.py
    python scripts/pipeline.py

The data is inlined into docs/index.html (replacing the __SCREEN_DATA__
placeholder) so the published page is self-contained and needs no fetch. The
template keeps a fetch fallback so it still works standalone for local dev.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "template.html"
DATA = ROOT / "data" / "candidates.json"
OUT_DIR = ROOT / "docs"
OUT = OUT_DIR / "index.html"

PLACEHOLDER = '"__SCREEN_DATA__"'


def build() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")

    if DATA.exists():
        payload = json.loads(DATA.read_text(encoding="utf-8"))
    else:
        payload = {
            "universe_size": 0, "fetched": 0, "num_candidates": 0,
            "num_watchlist": 0, "candidates": [], "watchlist": [],
        }

    # Compact to a single line so the inlined value is a valid one-line JS
    # string literal (a single-quoted JS string cannot span raw newlines).
    data = json.dumps(payload, separators=(",", ":"))

    # Embed as a single-quoted JS string literal. Escape backslashes, single
    # quotes, and any stray line/para separators that would break the literal.
    escaped = (data.replace("\\", "\\\\").replace("'", "\\'")
                   .replace("\n", "\\n").replace("\r", "\\r")
                   .replace(" ", "\\u2028").replace(" ", "\\u2029"))
    injected = "'" + escaped + "'"

    if PLACEHOLDER not in template:
        raise SystemExit("Placeholder __SCREEN_DATA__ not found in template.html")

    html = template.replace(PLACEHOLDER, injected, 1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT} ({len(html):,} bytes)")


if __name__ == "__main__":
    build()

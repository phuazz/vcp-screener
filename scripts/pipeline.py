"""
Build step: inject the latest screen and backtest output into the template and
write the GitHub Pages output.

    template.html + data/candidates.json + data/backtest.json  ->  docs/index.html

Run after a screen and/or backtest:
    python run_screen.py
    python run_backtest.py        # occasional; the backtest changes slowly
    python scripts/pipeline.py

Each dataset is inlined into docs/index.html (replacing its placeholder) so the
published page is self-contained and needs no fetch. The template keeps fetch
fallbacks so it still works standalone for local dev.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "template.html"
SCREEN_DATA = ROOT / "data" / "candidates.json"
BACKTEST_DATA = ROOT / "data" / "backtest.json"
OUT_DIR = ROOT / "docs"
OUT = OUT_DIR / "index.html"

EMPTY_SCREEN = {
    "universe_size": 0, "fetched": 0, "num_candidates": 0,
    "num_watchlist": 0, "candidates": [], "watchlist": [],
}

# Line and paragraph separators are valid JSON but break a JS string literal.
LINE_SEP = " "
PARA_SEP = " "


def _inject(template: str, placeholder: str, path: Path, fallback: dict) -> str:
    """Replace a "<placeholder>" JS string literal with the file's JSON.

    The JSON is compacted to a single line (a single-quoted JS string cannot
    span raw newlines) and escaped so the inlined value is a valid literal.
    """
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else fallback
    data = json.dumps(payload, separators=(",", ":"))
    escaped = (data.replace("\\", "\\\\").replace("'", "\\'")
                   .replace("\n", "\\n").replace("\r", "\\r")
                   .replace(LINE_SEP, "\\u2028").replace(PARA_SEP, "\\u2029"))
    token = '"' + placeholder + '"'
    if token not in template:
        raise SystemExit(f"Placeholder {placeholder} not found in template.html")
    return template.replace(token, "'" + escaped + "'", 1)


def build() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")
    html = _inject(template, "__SCREEN_DATA__", SCREEN_DATA, EMPTY_SCREEN)
    html = _inject(html, "__BACKTEST_DATA__", BACKTEST_DATA, {})

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT} ({len(html):,} bytes)")


if __name__ == "__main__":
    build()

"""Render the player template with synthetic data and check its invariants.

This runs on a bare interpreter in CI: no network, no BBC material, no
Whisper. It only proves that the template still renders into a page that
works offline and keeps the promises the README makes to users.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "assets" / "player-template.html"

# A 44-byte silent WAV is enough: the checks never decode it.
TINY_WAV = (
    "data:audio/wav;base64,"
    "UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA="
)

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def render() -> str:
    lesson = {
        "mode": "full",
        "generated_at": "2026-01-01T00:00:00",
        "episode": {
            "id": "999999",
            "title": "Self test episode",
            "duration_seconds": 8,
            "bbc_page_url": "https://www.bbc.co.uk/learningenglish/",
            "transcript_pdf_url": "https://downloads.bbc.co.uk/learningenglish/x.pdf",
        },
        "shadow": {
            "algorithm_version": "selftest",
            "model_name": "none",
            "sentences": [
                {
                    "id": f"s{n}",
                    "text": f"Self test sentence number {n}.",
                    "translation_zh": f"第 {n} 句的翻译。",
                    "start": float(n),
                    "end": float(n) + 0.9,
                    "glossary": [{"surface": "test", "meaning": "测试"}],
                    "diagnosis_tags": ["B"],
                    "listening_focus": f"第 {n} 句的听力提示。",
                }
                for n in (1, 2, 3)
            ],
        },
    }
    template = TEMPLATE.read_text(encoding="utf-8")
    return (template
            .replace("__LESSON_JSON__", json.dumps(lesson, ensure_ascii=False))
            .replace("__AUDIO_SRC__", TINY_WAV)
            .replace("__TITLE__", lesson["episode"]["title"]))


def main() -> int:
    check(TEMPLATE.exists(), f"missing template: {TEMPLATE}")
    if failures:
        print("\n".join(failures))
        return 1

    page = render()

    # Every placeholder must be substituted, or the page ships with literal
    # __TOKEN__ text where the lesson should be.
    leftovers = sorted(set(re.findall(r"__[A-Z_]+__", page)))
    check(not leftovers, f"unsubstituted placeholders: {leftovers}")

    # The page is handed to people as a single file they double-click. Anything
    # fetched from the network would break it offline.
    for pattern, label in (
        (r"<script[^>]+\ssrc=", "<script src>"),
        (r"<link[^>]+\shref=", "<link href>"),
        (r"<img[^>]+\ssrc=", "<img src>"),
        (r"@import", "@import"),
    ):
        check(not re.search(pattern, page, re.I), f"page is not self-contained: found {label}")

    # The embedded payload is what the desktop app's importer reads.
    data = re.search(
        r'<script[^>]*type="application/json"[^>]*id="lesson-data"[^>]*>(.*?)</script>',
        page, re.S)
    check(data is not None, 'missing <script id="lesson-data">')
    if data:
        try:
            payload = json.loads(data.group(1))
            rows = payload.get("shadow", {}).get("sentences", [])
            check(len(rows) == 3, f"expected 3 sentences in the payload, got {len(rows)}")
            starts = [row["start"] for row in rows]
            check(starts == sorted(starts), "sentences must be in audio order")
        except json.JSONDecodeError as error:
            check(False, f"lesson payload is not valid JSON: {error}")

    # The microphone must be requested once per page, not once per sentence.
    check("ensureMicStream" in page, "missing the shared-microphone helper")
    gum_calls = page.count("getUserMedia({ audio: true })")
    check(gum_calls == 1, f"getUserMedia must be called from one place, found {gum_calls}")

    # A stale instruction here is what used to send beginners to a terminal.
    check("http://localhost" not in page,
          "the page must not tell users to start a local server")

    if failures:
        print("selftest_render FAILED")
        for item in failures:
            print(f"  - {item}")
        return 1

    print(f"selftest_render OK  ({len(page) / 1024:.0f} KB rendered)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

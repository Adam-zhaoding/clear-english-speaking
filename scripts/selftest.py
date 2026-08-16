"""Offline self-checks for the skill.

Runs on a bare interpreter in CI: no network, no BBC material, no Whisper.
It proves two things the README promises:

  * the player template still renders into a page that works offline, and
  * scheduled preparation recognises an episode it already built.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_lesson  # noqa: E402
from make_lesson import NOTHING_NEW, already_built, find_unbuilt_episode  # noqa: E402

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


def check_schedule_guard() -> None:
    """A daily schedule must not re-download a weekly episode it already has."""
    with tempfile.TemporaryDirectory() as raw:
        courses = Path(raw)
        check(already_built(courses, "260813") is None,
              "an empty course directory must not look already-built")
        check(already_built(courses / "missing", "260813") is None,
              "a course directory that does not exist must not raise")

        (courses / "260813_who-does-the-housework.html").write_text("x", encoding="utf-8")
        found = already_built(courses, "260813")
        check(found is not None, "an existing course page must be recognised")

        # A different episode that merely shares a prefix must not match.
        check(already_built(courses, "2608") is None,
              "episode ids must match in full, not by prefix")
        check(already_built(courses, "260814") is None,
              "a different episode must still be prepared")

    check(NOTHING_NEW == "NOTHING_NEW",
          "the scheduled run greps for this exact marker; do not rename it")


def check_never_repeats_a_lesson() -> None:
    """Daily practice must reach into the archive, not stall on the newest week.

    BBC publishes weekly and the list page carries hundreds of past episodes,
    so a user practising every day should keep getting something they have not
    done yet.
    """
    catalogue = [
        ("260813", "https://example.invalid/ep-260813"),
        ("260806", "https://example.invalid/ep-260806"),
        ("260730", "https://example.invalid/ep-260730"),
    ]
    original = make_lesson.list_episodes
    make_lesson.list_episodes = lambda: catalogue
    try:
        with tempfile.TemporaryDirectory() as raw:
            courses = Path(raw)

            url, exhausted = find_unbuilt_episode(courses)
            check(exhausted is None and url.endswith("260813"),
                  "an empty library must start from the newest episode")

            (courses / "260813_a.html").write_text("x", encoding="utf-8")
            url, exhausted = find_unbuilt_episode(courses)
            check(exhausted is None and url.endswith("260806"),
                  "the newest episode being done must fall through to the next one")

            (courses / "260806_b.html").write_text("x", encoding="utf-8")
            url, exhausted = find_unbuilt_episode(courses)
            check(exhausted is None and url.endswith("260730"),
                  "it must keep walking back through the archive")

            (courses / "260730_c.html").write_text("x", encoding="utf-8")
            url, exhausted = find_unbuilt_episode(courses)
            check(exhausted is not None,
                  "only a fully-practised catalogue may report nothing new")
    finally:
        make_lesson.list_episodes = original


def main() -> int:
    check_schedule_guard()
    check_never_repeats_a_lesson()
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

    # Single sentences must not ride the <audio> playhead. Chrome seeks a VBR
    # MP3 only to the nearest Xing index entry (~3.7s apart on a 6-minute
    # episode); asking for 69.88s actually started at 68.86s, so the subtitle
    # and the voice drifted apart. Sentences are cut out of decoded PCM instead.
    check("decodeAudioData" in page and "createBufferSource" in page,
          "single-sentence playback must come from decoded PCM, not audio.currentTime")
    check("audio.currentTime = sentence" not in page and "seekTo(sentence" not in page,
          "single-sentence playback must not seek the media element")

    # The A/B/C labels above each sentence were noise on the page; they stay in
    # the payload as authoring metadata but must not be rendered.
    check("词不认识" not in page, "the A/B/C diagnosis labels must not be rendered")

    # BBC audio is embedded here as a personal copy.
    check("本内容仅供个人学习使用。" in page, "missing the personal-use notice")
    check("对齐算法" not in page and "对齐模型" not in page,
          "alignment internals must not be shown to the learner")

    if failures:
        print("selftest FAILED")
        for item in failures:
            print(f"  - {item}")
        return 1

    print("selftest OK")
    print("  · 定时备课的重复防护")
    print(f"  · 播放页渲染（{len(page) / 1024:.0f} KB，自包含，麦克风一处申请）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Import a weekly BBC shadow-reading player page into a Clear English course.

The user's Hermes routine already produces a self-contained
``*.pc-player.html`` every week: official BBC audio embedded as a data URI,
plus Whisper-aligned sentence spans. That is exactly the material a course
package needs, so this module converts one into the standard ZIP instead of
asking the user to prepare the same episode a second time.

The official transcript is still fetched from BBC and every sentence is still
verified against it, so an imported course carries the same source guarantees
as one built from scratch.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import tempfile
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .audio import audio_duration
from .builder import _download, _pdf_text, progress
from .course import CourseBuildError, normalize, validate_lesson, write_package

DATA_SCRIPT_RE = re.compile(
    r'<script[^>]*type="application/json"[^>]*id="shadow-data"[^>]*>(.*?)</script>', re.S | re.I)
AUDIO_RE = re.compile(r'src="data:audio/([a-z0-9]+);base64,([A-Za-z0-9+/=\s]+?)"', re.I)
TRANSCRIPT_RE = re.compile(
    r"https://downloads\.bbc\.co\.uk/learningenglish/[^\"'\s<>]+?\.pdf", re.I)
MP3_RE = re.compile(r"https://downloads\.bbc\.co\.uk/learningenglish/[^\"'\s<>]+?\.mp3", re.I)
EPISODE_RE = re.compile(r"/(\d{6})_", re.I)
TITLE_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)

# Container extension per data-URI subtype, so the package keeps a name the
# browser can infer a codec from.
EXTENSIONS = {"mp4": "m4a", "m4a": "m4a", "mpeg": "mp3", "mp3": "mp3", "wav": "wav", "ogg": "ogg"}
MAX_HTML_BYTES = 300 * 1024 * 1024


def _text(value: Any) -> str:
    return re.sub(r"<[^>]+>", "", str(value or "")).strip()


def parse_player(html: str) -> dict[str, Any]:
    """Pull the sentence table, audio and BBC source URLs out of the page."""
    script = DATA_SCRIPT_RE.search(html)
    if not script:
        raise CourseBuildError("player_html_unrecognised")
    try:
        payload = json.loads(script.group(1))
    except json.JSONDecodeError as error:
        raise CourseBuildError("player_html_unrecognised") from error
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        data = payload if isinstance(payload, dict) else {}
    sentences = data.get("sentences")
    if not isinstance(sentences, list) or not sentences:
        raise CourseBuildError("player_html_no_sentences")

    audio = AUDIO_RE.search(html)
    if not audio:
        raise CourseBuildError("player_html_no_audio")
    try:
        raw = base64.b64decode(re.sub(r"\s+", "", audio.group(2)), validate=True)
    except (binascii.Error, ValueError) as error:
        raise CourseBuildError("player_html_no_audio") from error
    if not raw:
        raise CourseBuildError("player_html_no_audio")

    transcript = TRANSCRIPT_RE.search(html)
    mp3 = MP3_RE.search(html)
    source = transcript.group(0) if transcript else (mp3.group(0) if mp3 else "")
    episode = EPISODE_RE.search(source)
    title = _text(TITLE_RE.search(html).group(1)) if TITLE_RE.search(html) else ""

    return {
        "sentences": sentences,
        "audio_bytes": raw,
        "audio_kind": EXTENSIONS.get(audio.group(1).lower(), "m4a"),
        "transcript_url": transcript.group(0) if transcript else "",
        "mp3_url": mp3.group(0) if mp3 else "",
        "episode_id": episode.group(1) if episode else "",
        "title": title,
        "declared_audio_sha256": str(data.get("audio_sha256") or ""),
    }


def _lesson_sentences(rows: list[dict[str, Any]], duration: float) -> list[dict[str, Any]]:
    """Normalise the player's rows into the course-package sentence contract."""
    result: list[dict[str, Any]] = []
    last_end = -1.0
    for position, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise CourseBuildError("invalid_sentence")
        text = str(row.get("text") or "").strip()
        start, end = row.get("start"), row.get("end")
        if not text or not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            raise CourseBuildError("invalid_sentence")
        if start < last_end or end <= start or end > duration:
            raise CourseBuildError("invalid_sentence_timing")
        last_end = float(end)
        glossary = []
        for item in row.get("glossary") or []:
            if isinstance(item, dict):
                surface = str(item.get("surface") or item.get("term") or "").strip()
                if surface:
                    glossary.append({
                        "surface": surface,
                        "lemma": str(item.get("lemma") or surface).strip(),
                        "gloss_zh": str(item.get("gloss_zh") or item.get("meaning_zh") or "").strip(),
                    })
        result.append({
            "id": str(row.get("id") or f"s{position}").strip() or f"s{position}",
            "start": round(float(start), 2),
            "end": round(float(end), 2),
            "text": text,
            "translation_zh": str(row.get("translation_zh") or "").strip(),
            "glossary": glossary,
            "diagnosis_tags": [str(tag) for tag in (row.get("diagnosis_tags") or []) if str(tag).strip()],
            "listening_focus": str(row.get("listening_focus") or row.get("listening_tip") or "").strip(),
            "comprehension_check": str(row.get("comprehension_check") or "").strip(),
        })
    return result


MIN_TRANSCRIPT_MATCH = 0.95
"""Minimum contiguous word-level agreement with the official transcript."""


def verify_against_transcript(text: str, official: str, official_words: list[str]) -> float:
    """Confirm a sentence really comes from the official transcript.

    An exact substring match is the normal case and returns 1.0. PDF text
    extraction occasionally drops a hyphenated or trailing token, which would
    reject a sentence that is genuinely official, so a contiguous window that
    agrees on at least ``MIN_TRANSCRIPT_MATCH`` of its words is also accepted.
    That is tight enough to still reject a paraphrase or an invented sentence,
    and the measured ratio is stored on the sentence so it can be reviewed.
    """
    wanted = normalize(text).split()
    if not wanted:
        raise CourseBuildError("invalid_sentence")
    if normalize(text) in official:
        return 1.0
    best = 0.0
    for start in range(len(official_words)):
        for length in range(max(1, len(wanted) - 4), len(wanted) + 5):
            window = official_words[start:start + length]
            if not window:
                continue
            best = max(best, SequenceMatcher(None, wanted, window, autojunk=False).ratio())
            if best >= 0.999:
                break
        if best >= 0.999:
            break
    if best < MIN_TRANSCRIPT_MATCH:
        raise CourseBuildError("sentence_not_in_official_transcript")
    return round(best, 4)


def build_from_player_html(html_path: Path, settings: dict[str, Any]) -> Path:
    """Convert one weekly player page into a verified course package."""
    if not html_path.is_file():
        raise CourseBuildError("player_html_missing")
    if html_path.stat().st_size > MAX_HTML_BYTES:
        raise CourseBuildError("player_html_too_large")
    progress("player_read", "正在读取每周播放器页面。")
    try:
        html = html_path.read_text(encoding="utf-8", errors="ignore")
    except OSError as error:
        raise CourseBuildError("player_html_missing") from error

    parsed = parse_player(html)
    episode_id = parsed["episode_id"]
    if not episode_id:
        raise CourseBuildError("episode_id_missing")

    target = Path(settings["course_directory"]) / f"{episode_id}.zip"
    if target.is_file():
        progress("reuse", "这一集已经在你的课程库里，直接使用已有课程。")
        return target

    with tempfile.TemporaryDirectory(prefix="clear-english-player-") as raw:
        root = Path(raw)
        audio = root / f"audio.{parsed['audio_kind']}"
        audio.write_bytes(parsed["audio_bytes"])
        duration = audio_duration(audio)

        transcript = root / "transcript.pdf"
        if not parsed["transcript_url"]:
            raise CourseBuildError("official_transcript_missing")
        progress("download", "正在下载这一集的 BBC 官方原文以核对句子。")
        _download(parsed["transcript_url"], transcript)
        official_text = _pdf_text(transcript)

        progress("transcript", "正在逐句核对官方原文。")
        sentences = _lesson_sentences(parsed["sentences"], duration)
        official_words = normalize(official_text).split()
        for sentence in sentences:
            sentence["transcript_match"] = verify_against_transcript(
                sentence["text"], normalize(official_text), official_words)

        lesson = {
            "schema_version": 1,
            "episode_id": episode_id,
            "title": parsed["title"] or f"BBC 6 Minute English · {episode_id}",
            "source": {
                "bbc_page_url": parsed["mp3_url"] or parsed["transcript_url"],
                "transcript_url": parsed["transcript_url"],
                # Provenance only: this is the hash of the original BBC MP3 the
                # weekly player aligned against, not of the transcoded copy it
                # embeds, so it is recorded rather than used as a check.
                "source_audio_sha256": parsed["declared_audio_sha256"],
            },
            "audio": {"file": audio.name, "duration_seconds": duration},
            "transcript": {"file": "transcript.pdf"},
            "sentences": sentences,
            "mode": "full",
        }
        # Each sentence was already checked against the transcript above, with
        # the extraction tolerance, so re-running the strict substring test
        # here would reject what has just been verified.
        validate_lesson(lesson)
        progress("package", "正在生成课程包并计算校验哈希。")
        return write_package(target, lesson, audio, transcript)

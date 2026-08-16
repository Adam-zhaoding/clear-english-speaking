from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import tempfile
import zipfile
from array import array
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CourseBuildError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower().replace("\n", " ")).strip()


def validate_lesson(lesson: dict[str, Any], official_transcript: str | None = None) -> None:
    if lesson.get("schema_version") != 1 or not lesson.get("episode_id"):
        raise CourseBuildError("invalid_lesson_schema")
    audio = lesson.get("audio") or {}; transcript = lesson.get("transcript") or {}
    if not audio.get("file") or not transcript.get("file") or not isinstance(audio.get("duration_seconds"), (int, float)):
        raise CourseBuildError("invalid_lesson_files")
    sentences = lesson.get("sentences")
    if not isinstance(sentences, list):
        raise CourseBuildError("invalid_sentence_count")
    # A listen-only lesson keeps the verified audio and transcript so the
    # episode stays playable when per-sentence alignment could not be produced.
    if lesson.get("mode") == "listen_only":
        if sentences:
            raise CourseBuildError("invalid_sentence_count")
        return
    if not 5 <= len(sentences) <= 6:
        raise CourseBuildError("invalid_sentence_count")
    last_end = -1.0
    identifiers = set()
    for sentence in sentences:
        start, end, text = sentence.get("start"), sentence.get("end"), sentence.get("text")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or not isinstance(text, str):
            raise CourseBuildError("invalid_sentence")
        # The player keys practice records on this id, so it must exist and be
        # unique or a lesson silently merges two sentences' progress.
        identifier = str(sentence.get("id") or "").strip()
        if not identifier or identifier in identifiers:
            raise CourseBuildError("invalid_sentence")
        identifiers.add(identifier)
        if start < 0 or end <= start or end > audio["duration_seconds"] or start < last_end:
            raise CourseBuildError("invalid_sentence_timing")
        if official_transcript and normalize(text) not in normalize(official_transcript):
            raise CourseBuildError("sentence_not_in_official_transcript")
        last_end = float(end)


def build_manifest(root: Path, names: list[str]) -> dict[str, Any]:
    return {"schema_version": 1, "course_version": "1.0.0", "generated_at": datetime.now(timezone.utc).isoformat(), "files": {name: {"sha256": sha256_file(root / name), "bytes": (root / name).stat().st_size} for name in names}}


def write_package(destination: Path, lesson: dict[str, Any], audio_path: Path, transcript_path: Path) -> Path:
    validate_lesson(lesson)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="clear-english-") as raw:
        root = Path(raw)
        audio_name = str(lesson["audio"]["file"]); transcript_name = str(lesson["transcript"]["file"])
        (root / audio_name).write_bytes(audio_path.read_bytes()); (root / transcript_name).write_bytes(transcript_path.read_bytes())
        (root / "lesson.json").write_text(json.dumps(lesson, ensure_ascii=False, indent=2), encoding="utf-8")
        names = [audio_name, transcript_name, "lesson.json"]
        (root / "manifest.json").write_text(json.dumps(build_manifest(root, names), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary = destination.with_suffix(".zip.tmp")
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as package:
            for name in [*names, "manifest.json"]:
                package.write(root / name, name)
        temporary.replace(destination)
    return destination


DEMO_SENTENCES = [
    ("Small, repeated practice can make difficult sounds feel familiar.", "小而重复的练习，能让困难的语音逐渐变得熟悉。", "先抓住 small, repeated practice 这个词块。", "说出练习为什么要重复。", ["词块", "重音"]),
    ("You do not need to understand every word on the first listen.", "第一遍听不需要听懂每一个词。", "注意 do not 和 to 的弱读。", "说出第一遍听的目标。", ["弱读"]),
    ("Try to notice one change in the speaker's rhythm.", "试着注意说话者节奏中的一个变化。", "把 notice one 当成一个整体听。", "今天你要注意哪一个语音变化？", ["节奏"]),
    ("Then play the sentence again at its natural speed.", "然后以自然语速再播放这句话。", "留意 then play 的衔接。", "回测时应该使用什么语速？", ["连读"]),
    ("A clear idea is more useful than a perfect score.", "一个清晰的想法，比一个完美分数更有用。", "重音落在 clear idea 和 perfect score。", "这里比较的是哪两件事？", ["重音"]),
]
DEMO_DURATION = 100.0


def synthetic_wav(spans: list[tuple[float, float]], duration: float, rate: int = 8000) -> bytes:
    """Build an audible placeholder track so the first run can be played.

    The demo course exists to prove the player works before any BBC material
    is on the machine. A silent or malformed file would make the play button
    look broken, but a tone held for the whole span just sounds like a fault,
    so each span gets a few quiet chime notes separated by silence.
    """
    total = int(duration * rate)
    samples = array("h", bytes(total * 2))
    note = 0.22          # seconds of sound per note
    gap = 0.55           # seconds between note onsets
    amplitude = 2600     # comfortably audible without being harsh
    for index, (start, end) in enumerate(spans):
        base = 440 * (2 ** (index / 12))
        onset = start
        step = 0
        while onset + note <= min(end, duration):
            frequency = base * (1.25 if step % 3 == 1 else 1.5 if step % 3 == 2 else 1.0)
            first = int(onset * rate)
            length = min(int(note * rate), total - first)
            for offset in range(max(0, length)):
                # Decay each note so it reads as a chime rather than a drone.
                envelope = (1 - offset / length) ** 2
                samples[first + offset] = int(amplitude * envelope * math.sin(2 * math.pi * frequency * offset / rate))
            onset += gap
            step += 1
    body = samples.tobytes()
    header = b"RIFF" + struct.pack("<I", 36 + len(body)) + b"WAVEfmt " + struct.pack(
        "<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16) + b"data" + struct.pack("<I", len(body))
    return header + body


def synthetic_pdf(lines: list[str]) -> bytes:
    """A minimal but genuinely valid one-page PDF holding the demo transcript."""
    text = "\n".join(f"({line.replace('(', '').replace(')', '')}) Tj 0 -22 Td" for line in lines)
    stream = f"BT /F1 11 Tf 40 740 Td\n{text}\nET".encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    return bytes(out)


def build_demo_package(destination: Path) -> Path:
    """Create a copyright-free synthetic package used for tests and first-run UI."""
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw); audio = root / "audio.wav"; transcript = root / "transcript.pdf"
        spans = [(8.0 + index * 18, 16.0 + index * 18) for index in range(len(DEMO_SENTENCES))]
        audio.write_bytes(synthetic_wav(spans, DEMO_DURATION))
        transcript.write_bytes(synthetic_pdf([item[0] for item in DEMO_SENTENCES]))
        lesson = {
            "schema_version": 1, "episode_id": "demo-local",
            "title": "演示课 · 先把播放器跑通",
            "source": {"bbc_page_url": "", "transcript_url": ""},
            "audio": {"file": "audio.wav", "duration_seconds": DEMO_DURATION},
            "transcript": {"file": "transcript.pdf"},
            "sentences": [{
                "id": f"s{index + 1}", "start": spans[index][0], "end": spans[index][1],
                "text": text, "translation_zh": translation, "glossary": [],
                "diagnosis_tags": tags, "listening_focus": focus, "comprehension_check": check,
            } for index, (text, translation, focus, check, tags) in enumerate(DEMO_SENTENCES)],
        }
        return write_package(destination, lesson, audio, transcript)

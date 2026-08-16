from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .audio import audio_duration
from .course import CourseBuildError, normalize, validate_lesson, write_package
from .discovery import OfficialAssets, discover_official_assets, fetch_official_page
from .settings import get_model_key

EPISODE_PAGE_RE = re.compile(r"https://www\.bbc\.(?:co\.uk|com)/learningenglish/english/features/6-minute-english_\d{4}/(?:ep-)?\d{6}", re.I)


# Failures of the sentence layer alone. The official audio and transcript are
# already downloaded and verified at that point, so the episode can still be
# delivered as a listen-only lesson rather than lost entirely.
SENTENCE_LEVEL_FAILURES = frozenset({
    "sentence_alignment_failed",
    "invalid_sentence_timing",
    "sentence_not_in_official_transcript",
    "invalid_sentence_count",
    "invalid_sentence",
    "whisper_words_missing",
    "whisper_model_unavailable",
    "whisper_dependency_unavailable",
})
LISTEN_ONLY_REASONS = {
    "sentence_alignment_failed": "有句子没能在音频里定位到，可能音频与文稿版本不完全一致。",
    "invalid_sentence_timing": "句子时间轴重叠或超出音频长度。",
    "sentence_not_in_official_transcript": "备课助手挑的句子和官方文稿对不上。",
    "invalid_sentence_count": "备课助手给出的重点句不是 5–6 句。",
    "invalid_sentence": "备课助手给出的句子缺少必要字段。",
    "whisper_words_missing": "语音识别没有从这段音频里得到可用的词。",
    "whisper_model_unavailable": "语音识别模型不可用，无法生成逐句时间轴。",
    "whisper_dependency_unavailable": "本机语音对齐组件缺失，无法生成逐句时间轴。",
}


def progress(stage: str, message: str) -> None:
    """Report a build phase so the desktop UI can show more than a spinner.

    The course path is the only thing written to stdout, so progress goes to
    stderr on its own line and the desktop shell streams it while the build
    runs.
    """
    print(f"PROGRESS\t{stage}\t{message}", file=sys.stderr, flush=True)


def whisper_model_cached(size: str) -> bool:
    """True when the local Whisper weights are already on this machine."""
    root = Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface")
    hub = root / "hub" if (root / "hub").is_dir() else root
    return any(hub.glob(f"models--Systran--faster-whisper-{size}/snapshots/*/model.bin"))


# A drafting agent is a language model, so the same teaching field arrives
# under different names from run to run. Dropping the ones that do not match
# exactly would silently ship a lesson with no hints and no vocabulary, which
# is what a beginner would notice first.
_FIELD_ALIASES = {
    "listening_focus": ("listening_focus", "listening_tip", "listening_hint", "focus"),
    "comprehension_check": ("comprehension_check", "comprehension", "check", "question"),
    "glossary": ("glossary", "vocab", "vocabulary", "words", "terms"),
    "diagnosis_tags": ("diagnosis_tags", "diagnosis", "tags", "difficulty_tags"),
}
_GLOSS_ALIASES = {
    "surface": ("surface", "term", "word", "phrase", "expression"),
    "lemma": ("lemma", "base", "root", "pos"),
    "gloss_zh": ("gloss_zh", "meaning_zh", "translation_zh", "zh", "meaning", "definition_zh"),
}


def _pick(source: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = source.get(name)
        if value not in (None, "", [], {}):
            return value
    return None


def _normalise_glossary(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    items = []
    for entry in value:
        if isinstance(entry, str):
            items.append({"surface": entry, "lemma": entry, "gloss_zh": ""})
            continue
        if not isinstance(entry, dict):
            continue
        surface = _pick(entry, _GLOSS_ALIASES["surface"])
        if not isinstance(surface, str) or not surface.strip():
            continue
        gloss = _pick(entry, _GLOSS_ALIASES["gloss_zh"])
        lemma = _pick(entry, _GLOSS_ALIASES["lemma"])
        items.append({
            "surface": surface.strip(),
            "lemma": lemma.strip() if isinstance(lemma, str) else surface.strip(),
            "gloss_zh": gloss.strip() if isinstance(gloss, str) else "",
        })
    return items


def _normalise_sentence(sentence: dict[str, Any]) -> dict[str, Any]:
    """Keep only the course-package fields, filled from whichever alias appeared."""
    tags = _pick(sentence, _FIELD_ALIASES["diagnosis_tags"])
    if isinstance(tags, str):
        tags = [tags]
    result = {
        "text": sentence["text"].strip(),
        "translation_zh": str(sentence.get("translation_zh") or "").strip(),
        "glossary": _normalise_glossary(_pick(sentence, _FIELD_ALIASES["glossary"])),
        "diagnosis_tags": [str(tag) for tag in tags if str(tag).strip()] if isinstance(tags, list) else [],
        "listening_focus": str(_pick(sentence, _FIELD_ALIASES["listening_focus"]) or "").strip(),
        "comprehension_check": str(_pick(sentence, _FIELD_ALIASES["comprehension_check"]) or "").strip(),
    }
    return result


def load_external_draft(path: Path) -> dict[str, Any]:
    """Read the narrow JSON contract written by a local Agent such as WorkBuddy."""
    try:
        # Some agents write a UTF-8 BOM; utf-8-sig reads both forms.
        draft = json.loads(path.read_text(encoding="utf-8-sig"))
        page_url = draft["bbc_page_url"]
        sentences = draft["sentences"]
    except (OSError, KeyError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise CourseBuildError("external_draft_invalid") from error
    if not isinstance(page_url, str) or not EPISODE_PAGE_RE.fullmatch(page_url) or not isinstance(sentences, list) or not 5 <= len(sentences) <= 6:
        raise CourseBuildError("external_draft_invalid")
    for sentence in sentences:
        if not isinstance(sentence, dict) or not isinstance(sentence.get("text"), str) or not sentence["text"].strip():
            raise CourseBuildError("external_draft_invalid")
    return {
        "bbc_page_url": page_url,
        "title": str(draft.get("title") or "").strip(),
        "sentences": [_normalise_sentence(sentence) for sentence in sentences],
    }


def discover_candidates(index_url: str) -> list[str]:
    return list(dict.fromkeys(EPISODE_PAGE_RE.findall(fetch_official_page(index_url))))


def _download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "ClearEnglish/0.1 (personal learning tool)"})
    try:
        with urllib.request.urlopen(request, timeout=60) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        # A dropped connection halfway through is the common case; never let it
        # reach the user as a stack trace.
        raise CourseBuildError("download_failed") from error
    if target.stat().st_size == 0: raise CourseBuildError("downloaded_file_empty")


def _pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
        text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
        if text.strip():
            return text
    except ImportError:
        pass
    except Exception as error:  # a malformed download must not surface as a stack trace
        raise CourseBuildError("official_transcript_unreadable") from error
    process = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True,
                             check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if process.returncode == 0 and process.stdout.strip(): return process.stdout
    raise CourseBuildError("official_transcript_unreadable")


def _duration(path: Path) -> float:
    return audio_duration(path)


def _model_json(transcript: str, assets: OfficialAssets, settings: dict[str, Any], api_key: str) -> dict[str, Any]:
    model = settings["model"]
    if not model.get("base_url") or not model.get("model") or not api_key: raise CourseBuildError("model_configuration_missing")
    prompt = f'''Return JSON only. Choose exactly 5 or 6 short sentences copied verbatim from this official BBC transcript. For each supply text, translation_zh, glossary (array), diagnosis_tags, listening_focus, comprehension_check. Do not invent English text. Episode: {assets.episode_id}. Transcript:\n{transcript[:24000]}'''
    payload = json.dumps({"model": model["model"], "temperature": 0.1, "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}}).encode("utf-8")
    url = str(model["base_url"]).rstrip("/") + "/chat/completions"
    request = urllib.request.Request(url, data=payload, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    try:
        response = json.loads(urllib.request.urlopen(request, timeout=90).read())
        content = response["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as error:
        raise CourseBuildError("model_generation_failed") from error


def _word_timestamps(audio: Path, size: str = "small") -> list[tuple[str, float, float]]:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as error:
        raise CourseBuildError("whisper_dependency_unavailable") from error
    if whisper_model_cached(size):
        progress("whisper_load", "正在加载本机语音模型。")
    else:
        progress("whisper_download", "首次备课需要下载语音识别模型（约 500MB），只需一次，请保持联网。")
    try:
        model = WhisperModel(size, device="cpu", compute_type="int8")
    except Exception as error:
        raise CourseBuildError("whisper_model_unavailable") from error
    progress("whisper_run", "正在逐词对齐音频与官方原文，这一步最慢，通常需要几分钟。")
    segments, _ = model.transcribe(str(audio), word_timestamps=True, vad_filter=True)
    words: list[tuple[str, float, float]] = []
    for segment in segments:
        for word in segment.words or []:
            words.append((word.word, float(word.start), float(word.end)))
    if not words: raise CourseBuildError("whisper_words_missing")
    return words


def _tokens(text: str) -> list[str]: return [item for item in normalize(text).split() if item]


def _best_word_alignment(wanted: list[str], actual: list[str], cursor: int) -> tuple[int, int, int, float] | None:
    """Find a conservative Whisper match while tolerating a few ASR differences."""
    best: tuple[int, int, int, float] | None = None
    minimum = max(1, len(wanted) - 3)
    maximum = len(wanted) + 4
    for start in range(cursor, len(actual)):
        for length in range(minimum, maximum + 1):
            candidate = actual[start:start + length]
            if not candidate:
                continue
            blocks = SequenceMatcher(None, wanted, candidate, autojunk=False).get_matching_blocks()
            matched = sum(block.size for block in blocks)
            coverage = matched / len(wanted)
            if coverage < 0.8:
                continue
            first = next((block for block in blocks if block.size), None)
            last = next((block for block in reversed(blocks) if block.size), None)
            if first is None or last is None:
                continue
            first_index = start + first.b
            last_index = start + last.b + last.size - 1
            candidate_value = (first_index, last_index, matched, coverage)
            if best is None or candidate_value[3] > best[3] or (candidate_value[3] == best[3] and candidate_value[2] > best[2]):
                best = candidate_value
    return best


def align_sentences(sentences: list[dict[str, Any]], words: list[tuple[str, float, float]], duration: float) -> None:
    flat: list[str] = []
    positions: list[tuple[float, float]] = []
    for raw_word, start, end in words:
        parts = _tokens(raw_word)
        flat.extend(parts)
        positions.extend([(start, end)] * len(parts))
    cursor = 0; last_end = 0.0
    for sentence in sentences:
        wanted = _tokens(str(sentence["text"]))
        match = _best_word_alignment(wanted, flat, cursor)
        if match is None: raise CourseBuildError("sentence_alignment_failed")
        start, end, _, _ = match
        sentence["start"], sentence["end"] = round(positions[start][0], 2), round(positions[end][1], 2)
        cursor = end + 1
        if sentence["start"] < last_end or sentence["end"] > duration: raise CourseBuildError("invalid_sentence_timing")
        last_end = sentence["end"]


def build_from_official_page(page_url: str, settings: dict[str, Any], external_draft: dict[str, Any] | None = None) -> Path:
    progress("discover", "正在核对 BBC 官方页面、音频与正式原文。")
    assets = discover_official_assets(page_url); output_dir = Path(settings["course_directory"]); target = output_dir / f"{assets.episode_id}.zip"
    # A verified package may already have been written when the desktop UI
    # refreshes or restarts. Returning it makes the handoff import idempotent
    # without overwriting the user's local course.
    if target.is_file():
        progress("reuse", "这一集已经构建过，直接使用本机已有课程。")
        return target
    api_key = get_model_key(settings["model"].get("api_key_ref", "clear-english-model-key"))
    with tempfile.TemporaryDirectory(prefix="clear-english-bbc-") as raw:
        root = Path(raw); audio = root / "audio.mp3"; transcript = root / "transcript.pdf"
        progress("download", "正在从 BBC 官方地址下载音频与正式原文。")
        _download(assets.mp3_url, audio); _download(assets.transcript_url, transcript)
        progress("transcript", "正在读取官方原文并逐句核对。")
        official_text = _pdf_text(transcript)
        draft = external_draft or _model_json(official_text, assets, settings, api_key)
        sentences = draft.get("sentences")
        if not isinstance(sentences, list): raise CourseBuildError("model_sentences_missing")
        duration = _duration(audio)
        # Practice records are keyed by sentence id, so every lesson needs
        # stable ids. Model and agent drafts never supply them.
        for position, sentence in enumerate(sentences, start=1):
            if isinstance(sentence, dict) and not str(sentence.get("id") or "").strip():
                sentence["id"] = f"s{position}"
        title = draft.get("title") or f"BBC 6 Minute English · {assets.episode_id}"
        lesson: dict[str, Any] = {
            "schema_version": 1, "episode_id": assets.episode_id, "title": title,
            "source": {"bbc_page_url": assets.page_url, "transcript_url": assets.transcript_url},
            "audio": {"file": "audio.mp3", "duration_seconds": duration},
            "transcript": {"file": "transcript.pdf"}, "sentences": sentences, "mode": "full",
        }
        try:
            align_sentences(sentences, _word_timestamps(audio, settings.get("whisper_model", "small")), duration)
            validate_lesson(lesson, official_text)
        except CourseBuildError as error:
            # The audio and transcript are already verified official BBC files.
            # Throwing them away because the sentence layer failed would leave
            # the user with nothing after a multi-minute download, so keep a
            # clearly-labelled listen-only lesson instead.
            code = str(error)
            if not settings.get("listen_only_fallback", True) or code not in SENTENCE_LEVEL_FAILURES:
                raise
            progress("listen_only", f"逐句训练未能生成（{code}），已保留可完整收听的整集课程。")
            lesson["sentences"] = []
            lesson["mode"] = "listen_only"
            lesson["degraded"] = {"code": code, "reason": LISTEN_ONLY_REASONS.get(code, "逐句训练未能生成。")}
            validate_lesson(lesson)
        progress("package", "正在生成课程包并计算校验哈希。")
        return write_package(target, lesson, audio, transcript)


def build_from_external_draft(draft_path: Path, settings: dict[str, Any]) -> Path:
    draft = load_external_draft(draft_path)
    return build_from_official_page(draft["bbc_page_url"], settings, draft)


def build_next_course(settings: dict[str, Any]) -> Path:
    existing = {item.stem for item in Path(settings["course_directory"]).glob("*.zip")}
    candidates = discover_candidates(settings["bbc_index_url"])
    for page_url in candidates:
        try:
            asset = discover_official_assets(page_url)
            if asset.episode_id not in existing: return build_from_official_page(page_url, settings)
        except CourseBuildError:
            continue
    raise CourseBuildError("no_eligible_episode")

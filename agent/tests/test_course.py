from __future__ import annotations

import base64
import json
import struct
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent.bbc_course_agent.audio import audio_duration, mp3_duration, mp4_duration, wav_duration
from agent.bbc_course_agent.builder import align_sentences, build_from_official_page, load_external_draft
from agent.bbc_course_agent.course import CourseBuildError, build_demo_package, synthetic_wav, validate_lesson
from agent.bbc_course_agent.discovery import OfficialAssets, discover_official_assets
from agent.bbc_course_agent.player_import import build_from_player_html


def mp4_file(seconds: float, timescale: int = 1000) -> bytes:
    """A minimal MP4 container carrying only the duration in its ``mvhd`` box."""
    mvhd_body = struct.pack(">BBBB", 0, 0, 0, 0) + struct.pack(">II", 0, 0) \
        + struct.pack(">II", timescale, int(seconds * timescale)) + bytes(80)
    mvhd = struct.pack(">I", 8 + len(mvhd_body)) + b"mvhd" + mvhd_body
    moov = struct.pack(">I", 8 + len(mvhd)) + b"moov" + mvhd
    ftyp_body = b"M4A " + struct.pack(">I", 512) + b"M4A mp42isom"
    ftyp = struct.pack(">I", 8 + len(ftyp_body)) + b"ftyp" + ftyp_body
    return ftyp + moov


def mpeg_frames(count: int, bitrate_index: int = 0b1001, rate_index: int = 0b00) -> bytes:
    """A minimal CBR MPEG-1 Layer III stream: 128 kbps at 44.1 kHz."""
    bitrate = 128000
    rate = 44100
    length = (1152 // 8) * bitrate // rate
    header = bytes([0xFF, 0xFB, (bitrate_index << 4) | (rate_index << 2), 0x00])
    return (header + bytes(length - 4)) * count


class CoursePackageTests(unittest.TestCase):
    def test_demo_package_has_verified_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            package = build_demo_package(Path(raw) / "demo.zip")
            with zipfile.ZipFile(package) as archive:
                self.assertEqual({"audio.wav", "transcript.pdf", "lesson.json", "manifest.json"}, set(archive.namelist()))
                lesson = json.loads(archive.read("lesson.json"))
                manifest = json.loads(archive.read("manifest.json"))
                audio = archive.read("audio.wav")
                transcript = archive.read("transcript.pdf")
            validate_lesson(lesson)
            self.assertEqual(5, len(lesson["sentences"]))
            self.assertIn("lesson.json", manifest["files"])
            # The first run must produce something a browser can actually play.
            self.assertAlmostEqual(lesson["audio"]["duration_seconds"], wav_duration(audio), places=1)
            self.assertTrue(transcript.startswith(b"%PDF-"))
            self.assertGreater(max(audio[44:]), 0)

    def test_demo_sentences_stay_inside_the_demo_audio(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            package = build_demo_package(Path(raw) / "demo.zip")
            with zipfile.ZipFile(package) as archive:
                lesson = json.loads(archive.read("lesson.json"))
        for sentence in lesson["sentences"]:
            self.assertLessEqual(sentence["end"], lesson["audio"]["duration_seconds"])
            self.assertLess(sentence["start"], sentence["end"])

    def test_a_built_lesson_always_carries_sentence_ids(self) -> None:
        """The player keys practice records on sentence id; a real BBC package
        that omits it cannot be imported at all."""
        assets = OfficialAssets(
            "260101",
            "https://www.bbc.co.uk/learningenglish/english/features/6-minute-english_2026/ep-260101",
            "https://downloads.bbc.co.uk/audio.mp3", "https://downloads.bbc.co.uk/transcript.pdf")
        text = " ".join(f"sentence number {n} here" for n in range(1, 6))
        draft = {"bbc_page_url": assets.page_url, "title": "Episode", "sentences": [
            {"text": f"sentence number {n} here", "translation_zh": "x", "glossary": [],
             "diagnosis_tags": [], "listening_focus": "", "comprehension_check": ""} for n in range(1, 6)]}
        words = [(word, float(i), float(i) + 0.5) for i, word in enumerate(text.split())]

        def fake_download(url: str, target: Path) -> None:
            # Long enough that every generated word timestamp stays in range.
            target.write_bytes(mpeg_frames(1200) if target.suffix == ".mp3" else b"%PDF x %%EOF")

        with tempfile.TemporaryDirectory() as raw:
            with patch("agent.bbc_course_agent.builder.discover_official_assets", return_value=assets), \
                 patch("agent.bbc_course_agent.builder._download", side_effect=fake_download), \
                 patch("agent.bbc_course_agent.builder._pdf_text", return_value=text), \
                 patch("agent.bbc_course_agent.builder._word_timestamps", return_value=words):
                package = build_from_official_page(assets.page_url, {"course_directory": raw, "model": {}}, draft)
            with zipfile.ZipFile(package) as archive:
                lesson = json.loads(archive.read("lesson.json"))
        self.assertEqual(["s1", "s2", "s3", "s4", "s5"], [s["id"] for s in lesson["sentences"]])
        self.assertEqual("full", lesson["mode"])
        # Agent bookkeeping fields must never reach the course package.
        for sentence in lesson["sentences"]:
            self.assertNotIn("speaker", sentence)
            self.assertNotIn("vocab", sentence)

    def test_rejects_a_lesson_whose_sentences_have_no_id(self) -> None:
        lesson = {"schema_version": 1, "episode_id": "x", "audio": {"file": "a.mp3", "duration_seconds": 30},
                  "transcript": {"file": "t.pdf"},
                  "sentences": [{"start": i, "end": i + 1, "text": "line"} for i in range(5)]}
        with self.assertRaisesRegex(CourseBuildError, "invalid_sentence"):
            validate_lesson(lesson)

    def test_rejects_duplicate_sentence_ids(self) -> None:
        lesson = {"schema_version": 1, "episode_id": "x", "audio": {"file": "a.mp3", "duration_seconds": 30},
                  "transcript": {"file": "t.pdf"},
                  "sentences": [{"id": "s1", "start": i, "end": i + 1, "text": "line"} for i in range(5)]}
        with self.assertRaisesRegex(CourseBuildError, "invalid_sentence"):
            validate_lesson(lesson)

    def test_rejects_overlapping_timestamps(self) -> None:
        lesson = {"schema_version": 1, "episode_id": "x", "audio": {"file": "audio.mp3", "duration_seconds": 30}, "transcript": {"file": "transcript.pdf"}, "sentences": [{"id": f"s{i}", "start": 1, "end": 3, "text": "line"} for i in range(5)]}
        with self.assertRaisesRegex(CourseBuildError, "invalid_sentence_timing"):
            validate_lesson(lesson)

    def test_workbuddy_draft_requires_bbc_page_and_sentences(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "draft.json"
            path.write_text(json.dumps({"bbc_page_url": "https://www.bbc.com/learningenglish/english/features/6-minute-english_2026/ep-260101", "sentences": [{"text": "A sentence.", "translation_zh": "一句话。"} for _ in range(5)]}), encoding="utf-8")
            draft = load_external_draft(path)
        self.assertEqual(5, len(draft["sentences"]))
        self.assertEqual("https://www.bbc.com/learningenglish/english/features/6-minute-english_2026/ep-260101", draft["bbc_page_url"])

    def test_workbuddy_draft_keeps_teaching_fields_written_under_aliases(self) -> None:
        """Real WorkBuddy output uses listening_tip/vocab; none of it may be lost."""
        sentence = {
            "index": 1,
            "speaker": "Myra Anubi",
            "text": "A sentence.",
            "translation_zh": "一句话。",
            "listening_tip": "注意 left out 的连读。",
            "comprehension_check": "她担心什么？",
            "vocab": [{"term": "bestie", "pos": "n. (slang)", "meaning_zh": "闺蜜"}],
        }
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "draft.json"
            path.write_text(json.dumps({
                "bbc_page_url": "https://www.bbc.com/learningenglish/english/features/6-minute-english_2026/ep-260101",
                "sentences": [dict(sentence) for _ in range(5)],
            }, ensure_ascii=False), encoding="utf-8")
            draft = load_external_draft(path)
        first = draft["sentences"][0]
        self.assertEqual("注意 left out 的连读。", first["listening_focus"])
        self.assertEqual("她担心什么？", first["comprehension_check"])
        self.assertEqual([{"surface": "bestie", "lemma": "n. (slang)", "gloss_zh": "闺蜜"}], first["glossary"])
        # Agent-only bookkeeping must not leak into the course package.
        self.assertEqual(
            {"text", "translation_zh", "glossary", "diagnosis_tags", "listening_focus", "comprehension_check"},
            set(first.keys()),
        )

    def test_workbuddy_draft_accepts_a_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "draft.json"
            path.write_text(json.dumps({
                "bbc_page_url": "https://www.bbc.com/learningenglish/english/features/6-minute-english_2026/ep-260101",
                "sentences": [{"text": "A sentence.", "translation_zh": "一句话。"} for _ in range(5)],
            }), encoding="utf-8-sig")
            self.assertEqual(5, len(load_external_draft(path)["sentences"]))

    def test_workbuddy_draft_rejects_missing_sentence_text(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "draft.json"
            path.write_text(json.dumps({"bbc_page_url": "https://www.bbc.com/learningenglish/english/features/6-minute-english_2026/ep-260101", "sentences": [{} for _ in range(5)]}), encoding="utf-8")
            with self.assertRaisesRegex(CourseBuildError, "external_draft_invalid"):
                load_external_draft(path)


class AudioDurationTests(unittest.TestCase):
    """A first-time user has no ffmpeg, so duration must be read in-process."""

    def test_measures_a_constant_bitrate_mp3_without_external_tools(self) -> None:
        stream = mpeg_frames(100)
        self.assertAlmostEqual(100 * 1152 / 44100, mp3_duration(stream), places=3)

    def test_skips_an_id3v2_tag_before_the_first_frame(self) -> None:
        payload = b"x" * 40
        tag = b"ID3\x03\x00\x00" + bytes([0, 0, 0, len(payload)]) + payload
        self.assertAlmostEqual(mp3_duration(tag + mpeg_frames(20)), 20 * 1152 / 44100, places=3)

    def test_ignores_a_trailing_id3v1_tag(self) -> None:
        stream = mpeg_frames(30) + b"TAG" + bytes(125)
        self.assertAlmostEqual(mp3_duration(stream), 30 * 1152 / 44100, places=3)

    def test_measures_an_mp4_container(self) -> None:
        """The weekly BBC player embeds AAC in M4A, not MP3."""
        self.assertAlmostEqual(373.85, mp4_duration(mp4_file(373.85)), places=2)

    def test_measures_a_wav_file(self) -> None:
        self.assertAlmostEqual(12.0, wav_duration(synthetic_wav([(1.0, 2.0)], 12.0)), places=3)

    def test_rejects_a_file_that_is_not_audio(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            broken = Path(raw) / "audio.mp3"
            broken.write_bytes(b"CLEAR_ENGLISH_SYNTHETIC_AUDIO")
            with self.assertRaisesRegex(CourseBuildError, "audio_duration_unavailable"):
                audio_duration(broken)


class DiscoveryTests(unittest.TestCase):
    @staticmethod
    def _page(html: bytes):
        """Stand in for urlopen, which the engine now uses as a context manager."""
        response = MagicMock()
        response.read.return_value = html
        opened = MagicMock()
        opened.__enter__.return_value = response
        return patch("urllib.request.urlopen", return_value=opened)

    def test_uses_official_transcript_not_worksheet(self) -> None:
        html = b'''<a href="https://downloads.bbc.co.uk/learningenglish/features/6min/260101_demo_transcript.pdf">Transcript</a><a href="https://downloads.bbc.co.uk/learningenglish/features/6min/260101_demo_download.mp3">Audio</a><a href="https://downloads.bbc.co.uk/learningenglish/features/6min/260101_demo_worksheet.pdf">Worksheet</a>'''
        with self._page(html):
            asset = discover_official_assets("https://www.bbc.com/learningenglish/english/features/6-minute-english_2026/ep-260101")
        self.assertEqual("260101", asset.episode_id)
        self.assertTrue(asset.transcript_url.endswith("_transcript.pdf"))

    def test_accepts_the_single_official_non_worksheet_pdf(self) -> None:
        html = b'''<a href="https://downloads.bbc.co.uk/learningenglish/features/6min/240912_episode.pdf">Transcript</a><a href="https://downloads.bbc.co.uk/learningenglish/features/6min/240912_episode_download.mp3">Audio</a><a href="https://downloads.bbc.co.uk/learningenglish/features/6min/240912_episode_worksheet.pdf">Worksheet</a>'''
        with self._page(html):
            asset = discover_official_assets("https://www.bbc.co.uk/learningenglish/english/features/6-minute-english_2024/ep-240912")
        self.assertTrue(asset.transcript_url.endswith("240912_episode.pdf"))
        self.assertNotIn("worksheet", asset.transcript_url)

    def test_rejects_ambiguous_unlabelled_pdfs(self) -> None:
        html = b'''<a href="https://downloads.bbc.co.uk/learningenglish/features/6min/240912_a.pdf">One</a><a href="https://downloads.bbc.co.uk/learningenglish/features/6min/240912_b.pdf">Two</a><a href="https://downloads.bbc.co.uk/learningenglish/features/6min/240912_download.mp3">Audio</a>'''
        with self._page(html):
            with self.assertRaisesRegex(CourseBuildError, "official_transcript_missing"):
                discover_official_assets("https://www.bbc.co.uk/learningenglish/english/features/6-minute-english_2024/ep-240912")

    def test_rejects_non_bbc_page(self) -> None:
        with self.assertRaisesRegex(CourseBuildError, "non_official_bbc_page"):
            discover_official_assets("https://example.com/episode")

    def test_a_missing_page_is_an_error_code_not_a_traceback(self) -> None:
        error = urllib.error.HTTPError("https://www.bbc.co.uk/x", 404, "Not Found", {}, None)  # type: ignore[arg-type]
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(CourseBuildError, "bbc_page_not_found"):
                discover_official_assets("https://www.bbc.co.uk/learningenglish/english/features/6-minute-english_2024/ep-240912")

    def test_an_offline_machine_is_an_error_code_not_a_traceback(self) -> None:
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no route to host")):
            with self.assertRaisesRegex(CourseBuildError, "bbc_page_unreachable"):
                discover_official_assets("https://www.bbc.co.uk/learningenglish/english/features/6-minute-english_2024/ep-240912")


class AlignmentTests(unittest.TestCase):
    def test_tolerates_one_whisper_word_difference(self) -> None:
        sentence = {"text": "This is a difficult phrase today."}
        words = [(word, float(index), float(index + 1)) for index, word in enumerate("this is a different phrase today".split())]
        align_sentences([sentence], words, 10)
        self.assertEqual(0.0, sentence["start"])
        self.assertEqual(6.0, sentence["end"])

    def test_rejects_low_coverage_alignment(self) -> None:
        sentence = {"text": "This sentence should not match the audio."}
        words = [(word, float(index), float(index + 1)) for index, word in enumerate("completely unrelated spoken words here today".split())]
        with self.assertRaisesRegex(CourseBuildError, "sentence_alignment_failed"):
            align_sentences([sentence], words, 10)


class ListenOnlyFallbackTests(unittest.TestCase):
    """Losing the sentence layer must not cost the user the whole episode."""

    def _build(self, failure: CourseBuildError, **overrides: object) -> dict:
        assets = OfficialAssets(
            "260101",
            "https://www.bbc.co.uk/learningenglish/english/features/6-minute-english_2026/ep-260101",
            "https://downloads.bbc.co.uk/audio.mp3",
            "https://downloads.bbc.co.uk/transcript.pdf",
        )
        draft = {"bbc_page_url": assets.page_url, "title": "Episode", "sentences": [
            {"text": "A sentence.", "translation_zh": "一句话。", "glossary": [],
             "diagnosis_tags": [], "listening_focus": "", "comprehension_check": ""} for _ in range(5)]}
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)

            def fake_download(url: str, target: Path) -> None:
                target.write_bytes(mpeg_frames(200) if target.suffix == ".mp3" else b"%PDF-1.4 A sentence. %%EOF")

            settings = {"course_directory": str(root / "courses"), "model": {}, **overrides}
            with patch("agent.bbc_course_agent.builder.discover_official_assets", return_value=assets), \
                 patch("agent.bbc_course_agent.builder._download", side_effect=fake_download), \
                 patch("agent.bbc_course_agent.builder._pdf_text", return_value="A sentence."), \
                 patch("agent.bbc_course_agent.builder._word_timestamps", side_effect=failure):
                package = build_from_official_page(assets.page_url, settings, draft)
                with zipfile.ZipFile(package) as archive:
                    return {
                        "names": set(archive.namelist()),
                        "lesson": json.loads(archive.read("lesson.json")),
                        "audio_bytes": len(archive.read("audio.mp3")),
                    }

    def test_keeps_the_playable_episode_when_alignment_fails(self) -> None:
        result = self._build(CourseBuildError("sentence_alignment_failed"))
        lesson = result["lesson"]
        self.assertEqual({"audio.mp3", "transcript.pdf", "lesson.json", "manifest.json"}, result["names"])
        self.assertEqual("listen_only", lesson["mode"])
        self.assertEqual([], lesson["sentences"])
        self.assertEqual("sentence_alignment_failed", lesson["degraded"]["code"])
        self.assertIn("定位", lesson["degraded"]["reason"])
        # The audio the user waited for is still there, with a real duration.
        self.assertGreater(result["audio_bytes"], 0)
        self.assertGreater(lesson["audio"]["duration_seconds"], 0)

    def test_keeps_the_episode_when_the_speech_model_is_unavailable(self) -> None:
        lesson = self._build(CourseBuildError("whisper_model_unavailable"))["lesson"]
        self.assertEqual("listen_only", lesson["mode"])

    def test_still_fails_hard_when_the_fallback_is_switched_off(self) -> None:
        with self.assertRaisesRegex(CourseBuildError, "sentence_alignment_failed"):
            self._build(CourseBuildError("sentence_alignment_failed"), listen_only_fallback=False)

    def test_a_source_failure_never_becomes_a_listen_only_course(self) -> None:
        with self.assertRaisesRegex(CourseBuildError, "downloaded_file_empty"):
            self._build(CourseBuildError("downloaded_file_empty"))


class PlayerImportTests(unittest.TestCase):
    """The weekly BBC shadow player page is a supported course source."""

    PAGE = (
        '<html><h1>Who Does The Housework</h1>'
        '<script type="application/json" id="shadow-data">%s</script>'
        '<audio src="data:audio/mp4;base64,%s"></audio>'
        '<a href="https://downloads.bbc.co.uk/learningenglish/features/6min/260813_x_transcript.pdf">Transcript</a>'
        '<a href="https://downloads.bbc.co.uk/learningenglish/features/6min/260813_x_download.mp3">Audio</a>'
        '</html>'
    )

    def _page(self, sentences: list[dict], audio: bytes) -> str:
        payload = json.dumps({"data": {"sentences": sentences, "audio_sha256": "deadbeef"}})
        return self.PAGE % (payload, base64.b64encode(audio).decode())

    def _rows(self) -> list[dict]:
        return [{"id": f"s{n}", "start": 10.0 * n, "end": 10.0 * n + 4, "text": f"Official sentence {n}."}
                for n in range(1, 6)]

    def _build(self, sentences: list[dict], official: str) -> dict:
        audio = mp4_file(120.0)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            page = root / "player.html"
            page.write_text(self._page(sentences, audio), encoding="utf-8")

            def fake_download(url: str, target: Path) -> None:
                target.write_bytes(b"%PDF-1.4 x %%EOF")

            with patch("agent.bbc_course_agent.player_import._download", side_effect=fake_download), \
                 patch("agent.bbc_course_agent.player_import._pdf_text", return_value=official):
                package = build_from_player_html(page, {"course_directory": str(root / "courses")})
                with zipfile.ZipFile(package) as archive:
                    return {"names": set(archive.namelist()), "lesson": json.loads(archive.read("lesson.json"))}

    def test_imports_a_weekly_player_into_a_verified_course(self) -> None:
        official = " ".join(f"Official sentence {n}." for n in range(1, 6))
        result = self._build(self._rows(), official)
        lesson = result["lesson"]
        self.assertEqual({"audio.m4a", "transcript.pdf", "lesson.json", "manifest.json"}, result["names"])
        self.assertEqual("260813", lesson["episode_id"])
        self.assertEqual("Who Does The Housework", lesson["title"])
        self.assertEqual(5, len(lesson["sentences"]))
        self.assertAlmostEqual(120.0, lesson["audio"]["duration_seconds"], places=1)
        self.assertTrue(all(item["transcript_match"] == 1.0 for item in lesson["sentences"]))

    def test_tolerates_a_token_the_pdf_extractor_dropped(self) -> None:
        """A real transcript PDF occasionally loses a trailing word."""
        spoken = ("Both these projects agree about one thing men doing more to help around "
                  "the house results in happier homes even if that means cleaning now and then")
        rows = self._rows()
        rows[0]["text"] = f"{spoken}."
        official = spoken.rsplit(" ", 1)[0] + " " + " ".join(f"Official sentence {n}." for n in range(2, 6))
        lesson = self._build(rows, official)["lesson"]
        match = lesson["sentences"][0]["transcript_match"]
        self.assertLess(match, 1.0)
        self.assertGreaterEqual(match, 0.95)

    def test_rejects_a_sentence_that_was_paraphrased(self) -> None:
        rows = self._rows()
        rows[0]["text"] = "Something entirely different that nobody ever said on this programme."
        official = " ".join(f"Official sentence {n}." for n in range(1, 6))
        with self.assertRaisesRegex(CourseBuildError, "sentence_not_in_official_transcript"):
            self._build(rows, official)

    def test_rejects_a_page_without_the_expected_data_block(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            page = Path(raw) / "player.html"
            page.write_text("<html><body>not a player</body></html>", encoding="utf-8")
            with self.assertRaisesRegex(CourseBuildError, "player_html_unrecognised"):
                build_from_player_html(page, {"course_directory": raw})

    def test_rejects_a_page_with_no_embedded_audio(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            page = Path(raw) / "player.html"
            payload = json.dumps({"data": {"sentences": self._rows()}})
            page.write_text(f'<script type="application/json" id="shadow-data">{payload}</script>', encoding="utf-8")
            with self.assertRaisesRegex(CourseBuildError, "player_html_no_audio"):
                build_from_player_html(page, {"course_directory": raw})


class ExistingCourseTests(unittest.TestCase):
    def test_returns_existing_package_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw) / "240912.zip"
            target.write_bytes(b"existing package")
            assets = OfficialAssets("240912", "https://www.bbc.co.uk/learningenglish/english/features/6-minute-english_2024/ep-240912", "https://downloads.bbc.co.uk/audio.mp3", "https://downloads.bbc.co.uk/transcript.pdf")
            with patch("agent.bbc_course_agent.builder.discover_official_assets", return_value=assets):
                result = build_from_official_page(assets.page_url, {"course_directory": raw, "model": {}})
        self.assertEqual(target, result)


if __name__ == "__main__":
    unittest.main()

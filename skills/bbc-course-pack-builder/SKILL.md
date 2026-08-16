---
name: bbc-course-pack-builder
description: Build a private, local Clear English Speaking course package from BBC Learning English 6 Minute English. Use whenever the user asks to download BBC 6 Minute English material, create/import a course ZIP, run scheduled local lesson preparation, or diagnose missing BBC audio, Transcript, alignment, course-package or local-agent failures.
compatibility: Requires the local bbc-course-agent; never requires Hermes, Feishu credentials, or cloud account access.
---

# BBC Course Pack Builder

## Purpose

Create a local `audio + transcript.pdf + lesson.json + manifest.json` ZIP for Clear English Speaking. The generated ZIP remains on the user's device; it is not a public redistribution artifact.

## WorkBuddy desktop handoff

When this Skill is installed by the Clear English Speaking desktop player, a task file appears under `.clear-english-speaking/jobs/<id>/task.json` in the current WorkBuddy workspace.

1. Read that task file and obey its `output_draft` path.
2. Use an official BBC Learning English 6 Minute English page and its formal Transcript to prepare **only** a teaching draft.
3. Write one UTF-8 JSON file to `output_draft` with `bbc_page_url`, `title`, and 5–6 `sentences`. Every sentence needs verbatim `text` and `translation_zh`; optional fields are `glossary`, `diagnosis_tags`, `listening_focus`, and `comprehension_check`.
4. Do not download MP3/PDF, create a ZIP, request an API key, write outside the task output, or modify WorkBuddy settings. The Clear English Speaking desktop app performs deterministic download, alignment, hash and ZIP validation after it sees this draft.
5. End with only: `草案已写入`.

This mode is designed for users who only installed WorkBuddy. A new WorkBuddy session is required after Skill installation so that WorkBuddy discovers the complete Skill directory.

## Source rules

1. Use only a BBC Learning English 6 Minute English official episode page.
2. Discover the MP3 from that page. Never infer an MP3 name from a transcript filename.
3. Transcript PDF selection, matching what the build engine enforces:
   - Consider only PDFs on `downloads.bbc.co.uk/learningenglish/`.
   - Discard every candidate whose URL contains `worksheet`, regardless of link text.
   - Prefer an explicitly named `*_transcript.pdf` or `*_transcript_.pdf`.
   - BBC also publishes some episodes with an unlabelled main transcript. Such a
     PDF is acceptable **only when it is the single remaining non-worksheet
     candidate**. Two or more unlabelled candidates is an ambiguity, not a
     choice: stop with `official_transcript_missing`.
   - Whichever PDF is chosen still has to pass full text extraction and
     verbatim per-sentence verification downstream. Filename alone never
     qualifies a transcript.
4. Keep audio, Transcript, selected sentences and episode ID from one episode.
5. A candidate without a verifiable official Transcript remains `needs_source_validation`, not a finished course.

## Build workflow

The Clear English Speaking desktop application embeds this engine and runs it for you;
the steps below describe what it does after it receives a draft. A draft author
performs step 4 only.

1. The desktop app writes the job and hands you `task.json`.
2. Any user-owned model endpoint/key lives in the OS credential store; never put a key in a prompt, ZIP, log, screenshot, or repository.
3. The engine downloads the official assets of a previously unseen episode into a temporary directory.
4. Teaching fields are drafted: translations, glossary items, listening-focus hints, A/B/C diagnosis tags and comprehension checks. English `text` is always copied verbatim from the official Transcript.
5. The engine verifies every selected sentence against the official Transcript text. Exactly 5–6 sentences are required.
6. The engine measures audio duration in-process and runs word-timestamp alignment with local Whisper, rejecting overlapping, out-of-range or low-coverage sentence spans.
7. Every course file is hashed into `manifest.json` and one ZIP is written atomically into the course directory.
8. The player imports only a completed ZIP, re-checking every hash. On any failure, old courses are preserved and a short error code is recorded.

## Operational states

- `ready`: ZIP passed content, timing and hash validation.
- `needs_source_validation`: official page/audio/Transcript proof is incomplete.
- `no_eligible_episode`: no new valid episode exists; create nothing.
- `official_mp3_missing`, `official_transcript_missing`, `sentence_not_in_official_transcript`, `invalid_sentence_timing`: stop and explain the specific repair path.

## Safety and copyright

- Do not bypass regional controls, access controls or copyright notices.
- Do not upload or commit BBC source audio, PDFs or completed BBC course ZIPs.
- Do not treat ASR output as official text.
- Do not upload recording files or personal learning records.

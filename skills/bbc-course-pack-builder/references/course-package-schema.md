# Clear English Speaking course package schema v1

```text
episode.zip
├── audio.mp3|m4a
├── transcript.pdf
├── lesson.json
└── manifest.json
```

`lesson.json` requires `schema_version: 1`, episode/source metadata, audio duration, official Transcript file, and 5–6 ordered sentence objects. Each sentence requires `id`, `start`, `end`, official `text`, `translation_zh`, `glossary`, `diagnosis_tags`, `listening_focus`, and `comprehension_check`.

`manifest.json` contains `schema_version: 1`, generated time, course version, and SHA-256/byte count for the audio, Transcript and `lesson.json`. The client rejects missing files, unknown schema versions, invalid hashes and overlapping/out-of-range sentence ranges.

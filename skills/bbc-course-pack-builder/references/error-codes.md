# Local build error codes

The engine stops on the first failure and never writes a partial course. An
existing ZIP for the same episode is always preserved.

## Source verification

| Code | Meaning | Repair |
|---|---|---|
| `non_official_bbc_page` | The supplied page is not an official BBC Learning English URL. | Choose the official episode page. |
| `bbc_page_not_found` | The episode page returned 404. | Choose another episode. |
| `bbc_page_unreachable` | BBC could not be reached (DNS, proxy, timeout). | Check connectivity and retry. |
| `download_failed` | The connection dropped while fetching audio or the transcript. | Check connectivity and retry. |
| `episode_id_missing` | The URL carries no `ep-YYMMDD` style episode id. | Use the canonical episode URL. |
| `official_mp3_missing` | No real MP3 was found on the page. | Skip this episode; do not guess a URL. |
| `official_transcript_missing` | No formal Transcript PDF was found, or two or more unlabelled candidates were ambiguous. | Skip it; never use a worksheet PDF. |
| `official_transcript_unreadable` | The Transcript PDF downloaded but no text could be extracted. | Retry; if it persists, choose another episode. |
| `downloaded_file_empty` | BBC returned a zero-byte file. | Check the network and retry. |

## Draft and teaching content

| Code | Meaning | Repair |
|---|---|---|
| `external_draft_invalid` | The agent draft is not valid UTF-8 JSON, or misses `bbc_page_url` / 5–6 `sentences` with non-empty `text`. | Re-send the task to the agent. |
| `sentence_not_in_official_transcript` | A selected sentence differs from the official text after normalisation. | Regenerate the draft; never relax this check. |
| `invalid_sentence_count` | The lesson does not contain exactly 5 or 6 sentences. | Regenerate the draft. |
| `model_configuration_missing` | API mode has no base URL, model or key. | Complete the API configuration. |
| `model_generation_failed` | The user's model service returned no usable JSON. | Check endpoint, model name and quota. |
| `model_sentences_missing` | The model response had no `sentences` array. | Retry, or switch to WorkBuddy. |

## Audio and timing

| Code | Meaning | Repair |
|---|---|---|
| `audio_duration_unavailable` | The downloaded audio is not a parseable MP3/WAV. | Check the network and retry. |
| `whisper_dependency_unavailable` | `faster-whisper` is not present in this build. | Reinstall Clear English. |
| `whisper_model_unavailable` | The speech model could not be loaded or downloaded. | The first build downloads ~500 MB; confirm connectivity and retry. |
| `whisper_words_missing` | Alignment produced no words at all. | Choose another episode. |
| `sentence_alignment_failed` | A sentence could not be located in the audio at ≥80% ordered word coverage. | Regenerate the draft or choose another episode; never fabricate timestamps. |
| `invalid_sentence_timing` | Time ranges overlap, go backwards, or exceed the audio duration. | Re-run alignment. |

## Scheduling

| Code | Meaning | Repair |
|---|---|---|
| `no_eligible_episode` | No unlearned, verifiable candidate exists. | Do nothing and wait for the next schedule. |

## Player-side import

The player recomputes every manifest hash before a course becomes playable and
rejects, with a plain-language message rather than a code: a non-ZIP file, an
archive over 200 MB, more than 32 entries, unsafe or duplicate entry names, a
manifest path that escapes the package root, a byte-size or SHA-256 mismatch,
a lesson outside schema version 1, sentence counts outside 5–6, duplicate
sentence ids, and timings that overlap or exceed the audio duration.

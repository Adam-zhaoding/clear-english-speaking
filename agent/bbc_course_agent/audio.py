"""Audio duration without external tools.

A first-time user only installs Clear English. They do not have ffmpeg on
PATH, so the course build must be able to measure an MP3 on its own. This
module parses MPEG audio frame headers (and RIFF/WAVE headers) in pure
Python; ``ffprobe`` is only consulted as an optional cross-check when the
machine happens to have it.
"""

from __future__ import annotations

import struct
import subprocess
from pathlib import Path

from .course import CourseBuildError

# MPEG version ids: 0 = MPEG 2.5, 2 = MPEG 2, 3 = MPEG 1 (1 is reserved).
_BITRATES_V1_L3 = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0)
_BITRATES_V2_L3 = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0)
_SAMPLE_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}
_SAMPLES_PER_FRAME = {3: 1152, 2: 576, 0: 576}


def _id3v2_size(data: bytes) -> int:
    """Length of a leading ID3v2 tag, which is not part of the audio stream."""
    if len(data) < 10 or data[:3] != b"ID3":
        return 0
    if any(byte & 0x80 for byte in data[6:10]):
        return 0
    size = 0
    for byte in data[6:10]:
        size = (size << 7) | byte
    footer = 10 if data[5] & 0x10 else 0
    return 10 + size + footer


def _frame_header(data: bytes, offset: int) -> tuple[int, float] | None:
    """Decode one MPEG audio frame at ``offset`` into (byte length, seconds)."""
    if offset + 4 > len(data):
        return None
    header = struct.unpack(">I", data[offset:offset + 4])[0]
    if header & 0xFFE00000 != 0xFFE00000:
        return None
    version = (header >> 19) & 0b11
    layer = (header >> 17) & 0b11
    bitrate_index = (header >> 12) & 0b1111
    rate_index = (header >> 10) & 0b11
    padding = (header >> 9) & 0b1
    if version == 1 or layer != 0b01 or rate_index == 0b11:
        return None  # reserved version, or not Layer III
    if bitrate_index in (0, 0b1111):
        return None  # free-form or invalid bitrate
    table = _BITRATES_V1_L3 if version == 3 else _BITRATES_V2_L3
    bitrate = table[bitrate_index] * 1000
    sample_rate = _SAMPLE_RATES[version][rate_index]
    samples = _SAMPLES_PER_FRAME[version]
    if not bitrate or not sample_rate:
        return None
    length = (samples // 8) * bitrate // sample_rate + padding
    if length <= 4:
        return None
    return length, samples / sample_rate


def _xing_frame_count(data: bytes, offset: int, version: int, channel_mode: int) -> int | None:
    """Read the frame count a VBR encoder stores in the first frame."""
    if version == 3:
        side_info = 17 if channel_mode == 0b11 else 32
    else:
        side_info = 9 if channel_mode == 0b11 else 17
    marker = offset + 4 + side_info
    tag = data[marker:marker + 4]
    if tag in (b"Xing", b"Info"):
        flags = struct.unpack(">I", data[marker + 4:marker + 8])[0]
        if flags & 0x1:
            return struct.unpack(">I", data[marker + 8:marker + 12])[0]
        return None
    if data[offset + 4 + 32:offset + 4 + 36] == b"VBRI":
        return struct.unpack(">I", data[offset + 4 + 46:offset + 4 + 50])[0]
    return None


def mp3_duration(data: bytes) -> float | None:
    """Total playing time of an MPEG Layer III stream, in seconds."""
    offset = _id3v2_size(data)
    limit = len(data)
    if data[-128:-125] == b"TAG":
        limit -= 128  # trailing ID3v1 tag is not audio
    # Locate the first real frame; some files carry junk before the stream.
    while offset < limit - 4:
        frame = _frame_header(data, offset)
        if frame and _frame_header(data, offset + frame[0]):
            break
        offset += 1
    else:
        return None
    header = struct.unpack(">I", data[offset:offset + 4])[0]
    version = (header >> 19) & 0b11
    rate_index = (header >> 10) & 0b11
    channel_mode = (header >> 6) & 0b11
    count = _xing_frame_count(data, offset, version, channel_mode)
    if count:
        return count * _SAMPLES_PER_FRAME[version] / _SAMPLE_RATES[version][rate_index]
    total = 0.0
    while offset < limit:
        frame = _frame_header(data, offset)
        if not frame:
            break
        total += frame[1]
        offset += frame[0]
    return total or None


def wav_duration(data: bytes) -> float | None:
    """Playing time of a PCM RIFF/WAVE file."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    offset = 12
    byte_rate = 0
    while offset + 8 <= len(data):
        chunk = data[offset:offset + 4]
        size = struct.unpack("<I", data[offset + 4:offset + 8])[0]
        body = offset + 8
        if chunk == b"fmt " and size >= 16:
            byte_rate = struct.unpack("<I", data[body + 8:body + 12])[0]
        elif chunk == b"data" and byte_rate:
            return min(size, len(data) - body) / byte_rate
        offset = body + size + (size & 1)
    return None


def mp4_duration(data: bytes) -> float | None:
    """Playing time of an MP4/M4A container, read from its ``mvhd`` box.

    The weekly BBC player embeds AAC audio in an M4A container, so this path
    matters for importing it.
    """
    def walk(start: int, end: int) -> float | None:
        offset = start
        while offset + 8 <= end:
            size = struct.unpack(">I", data[offset:offset + 4])[0]
            kind = data[offset + 4:offset + 8]
            body = offset + 8
            if size == 1:  # 64-bit extended size
                if body + 8 > end:
                    return None
                size = struct.unpack(">Q", data[body:body + 8])[0]
                body += 8
            elif size == 0:
                size = end - offset
            if size < 8 or offset + size > end:
                return None
            if kind == b"mvhd":
                version = data[body]
                cursor = body + 4 + (16 if version == 1 else 8)
                if version == 1:
                    timescale = struct.unpack(">I", data[cursor:cursor + 4])[0]
                    length = struct.unpack(">Q", data[cursor + 4:cursor + 12])[0]
                else:
                    timescale = struct.unpack(">I", data[cursor:cursor + 4])[0]
                    length = struct.unpack(">I", data[cursor + 4:cursor + 8])[0]
                return length / timescale if timescale else None
            if kind in (b"moov", b"trak", b"mdia"):
                found = walk(body, offset + size)
                if found is not None:
                    return found
            offset += size
        return None

    if len(data) < 12 or data[4:8] != b"ftyp":
        return None
    return walk(0, len(data))


def _ffprobe_duration(path: Path) -> float | None:
    """Optional cross-check for machines that already have ffmpeg installed."""
    try:
        process = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, ValueError):
        return None
    try:
        value = float(process.stdout.strip())
    except ValueError:
        return None
    return value if value > 0 else None


def audio_duration(path: Path) -> float:
    """Measure an audio file without requiring any external program."""
    try:
        data = path.read_bytes()
    except OSError as error:
        raise CourseBuildError("audio_duration_unavailable") from error
    if data[:4] == b"RIFF":
        value = wav_duration(data)
    elif data[4:8] == b"ftyp":
        value = mp4_duration(data)
    else:
        value = mp3_duration(data)
    if value is None:
        value = _ffprobe_duration(path)
    if value is None or value <= 0:
        raise CourseBuildError("audio_duration_unavailable")
    return value

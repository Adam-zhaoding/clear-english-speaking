"""把测试音频内嵌进探针模板，产出可直接双击的单文件 runtime-probe.html。

用法：
    python build_probe.py

不依赖任何第三方库。生成的 HTML 完全自包含，可离线打开。
"""
import base64
import io
import math
import struct
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "runtime-probe.template.html"
OUTPUT = HERE / "runtime-probe.html"

RATE = 8000
DURATION = 8.0
BEEP_MS = 70
PLACEHOLDER = "__TONE_B64__"


def envelope(index: int, total: int) -> float:
    """短促的淡入淡出，避免爆音。"""
    attack = int(total * 0.15)
    release = int(total * 0.35)
    if index < attack:
        return index / attack
    if index > total - release:
        return (total - index) / release
    return 1.0


def build_tone() -> bytes:
    """每秒一个「滴」，音高逐秒递增；0 秒处双击，便于人耳判断 seek 落点。"""
    total_samples = int(RATE * DURATION)
    beep_samples = int(RATE * BEEP_MS / 1000)
    marks = {second: 440 + second * 110 for second in range(int(DURATION))}
    double_click = int(0.12 * RATE)

    frames = bytearray()
    for n in range(total_samples):
        value = 0.0
        for second, freq in marks.items():
            offset = n - second * RATE
            if 0 <= offset < beep_samples:
                value += 0.62 * envelope(offset, beep_samples) * math.sin(
                    2 * math.pi * freq * (offset / RATE)
                )
        offset = n - double_click
        if 0 <= offset < beep_samples:
            value += 0.62 * envelope(offset, beep_samples) * math.sin(
                2 * math.pi * 440 * (offset / RATE)
            )
        frames += struct.pack("<h", int(max(-1.0, min(1.0, value)) * 32000))

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(bytes(frames))
    return buffer.getvalue()


def main() -> None:
    if not TEMPLATE.exists():
        raise SystemExit(f"找不到模板：{TEMPLATE}")

    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise SystemExit(f"模板里没有占位符 {PLACEHOLDER}，无法注入音频。")

    wav = build_tone()
    encoded = base64.b64encode(wav).decode("ascii")
    html = template.replace(PLACEHOLDER, encoded)

    # 原子写：先写临时文件再替换，中断不留半成品
    temporary = OUTPUT.with_suffix(".html.tmp")
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(OUTPUT)

    print(f"音频     : {len(wav):,} bytes（{DURATION:g}s @ {RATE}Hz）")
    print(f"base64   : {len(encoded):,} chars")
    print(f"已生成   : {OUTPUT}")
    print(f"文件大小 : {OUTPUT.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()

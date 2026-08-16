"""WorkBuddy 沙箱能力探针。

在 WorkBuddy 里让它执行这个脚本，一次测完三件事：
  1. 沙箱能否绑定本地端口并通过 http://localhost 自己访问自己（决定录音方案是否成立）
  2. 沙箱能否访问 BBC 官方域（决定备课链路是否成立）
  3. 本地 Whisper 是否可用、跑一段音频要多久（决定备课总耗时）

只读不写系统配置，不安装任何东西，不碰 Hermes 的任何任务。
产出：同目录下的 probe-workbuddy.json + 终端上的人类可读报告。

用法：
    python probe_workbuddy.py
    python probe_workbuddy.py --audio 某个真实的.mp3    # 顺便实测 Whisper 耗时
"""
from __future__ import annotations

import argparse
import http.server
import importlib.util
import json
import os
import platform
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPORT = HERE / "probe-workbuddy.json"

BBC_PAGE = "https://www.bbc.co.uk/learningenglish/english/features/6-minute-english"
BBC_ASSET = (
    "https://downloads.bbc.co.uk/learningenglish/features/6min/"
    "260813_6_minute_english_who_does_the_housework_download.mp3"
)

results: list[dict] = []


def record(key: str, title: str, state: str, value: str, detail: dict | None = None) -> None:
    """state: pass / warn / fail / skip"""
    results.append(
        {"key": key, "title": title, "state": state, "value": value, "detail": detail or {}}
    )
    mark = {"pass": "[ OK ]", "warn": "[WARN]", "fail": "[FAIL]", "skip": "[SKIP]"}[state]
    print(f"{mark} {title}: {value}")


# ---------------------------------------------------------------- 1. 运行环境
def probe_environment() -> None:
    print("\n=== 1. 运行环境 ===")
    record(
        "python",
        "Python",
        "pass",
        f"{platform.python_version()} @ {sys.executable}",
        {"version": platform.python_version(), "executable": sys.executable},
    )
    record(
        "platform",
        "操作系统",
        "pass",
        f"{platform.system()} {platform.release()} / {platform.machine()}",
    )
    record("cwd", "当前工作目录", "pass", str(Path.cwd()))

    # 能否在当前目录写文件
    try:
        probe_file = HERE / ".__write_probe__"
        probe_file.write_text("probe", encoding="utf-8")
        probe_file.unlink()
        record("write", "目录写权限", "pass", f"可写入 {HERE}")
    except Exception as error:  # noqa: BLE001
        record("write", "目录写权限", "fail", f"{type(error).__name__}: {error}")

    for tool in ("ffmpeg", "ffprobe", "node"):
        path = shutil.which(tool)
        record(
            f"tool_{tool}",
            f"外部工具 {tool}",
            "pass" if path else "warn",
            path or "未安装（备课流水线不依赖它，仅记录）",
        )


# ---------------------------------------------------------------- 2. 端口绑定
def probe_localhost() -> None:
    """这是最关键的一项：localhost 是安全上下文，能起服务就能解锁网页录音。"""
    print("\n=== 2. 本地端口与 localhost 服务 ===")

    chosen = None
    for port in range(8765, 8785):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe_socket:
                probe_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe_socket.bind(("127.0.0.1", port))
                probe_socket.listen(1)
            chosen = port
            break
        except OSError:
            continue

    if chosen is None:
        record("bind", "绑定本地端口", "fail", "8765-8784 全部无法绑定，沙箱可能禁止监听")
        record("localhost_http", "localhost HTTP 自访问", "skip", "无端口可用")
        return

    record("bind", "绑定本地端口", "pass", f"127.0.0.1:{chosen} 可监听")

    # 真的起一个 http.server，然后自己请求自己
    handler_dir = str(HERE)

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=handler_dir, **kwargs)

        def log_message(self, *args):  # 静音
            return

    server = None
    try:
        socketserver.TCPServer.allow_reuse_address = True
        server = socketserver.TCPServer(("127.0.0.1", chosen), QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.4)

        started = time.perf_counter()
        with urllib.request.urlopen(f"http://127.0.0.1:{chosen}/", timeout=5) as response:
            status = response.status
            size = len(response.read())
        elapsed = (time.perf_counter() - started) * 1000
        record(
            "localhost_http",
            "localhost HTTP 自访问",
            "pass" if status == 200 else "warn",
            f"HTTP {status} · {size} bytes · {elapsed:.0f}ms",
            {"port": chosen, "url": f"http://localhost:{chosen}/"},
        )

        probe_html = HERE / "runtime-probe.html"
        if probe_html.exists():
            record(
                "probe_url",
                "探针页面可访问地址",
                "pass",
                f"http://localhost:{chosen}/runtime-probe.html",
                {"hint": "用这个地址打开探针页，麦克风才可能被允许"},
            )
        else:
            record(
                "probe_url",
                "探针页面可访问地址",
                "warn",
                "runtime-probe.html 不在同目录，先运行 build_probe.py",
            )
    except Exception as error:  # noqa: BLE001
        record("localhost_http", "localhost HTTP 自访问", "fail", f"{type(error).__name__}: {error}")
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()


# ---------------------------------------------------------------- 3. 出网能力
def probe_network() -> None:
    print("\n=== 3. 出网与 BBC 官方来源 ===")
    targets = [
        ("bbc_page", "BBC 期次列表页", BBC_PAGE, "GET"),
        ("bbc_asset", "BBC 官方音频（只读 header）", BBC_ASSET, "HEAD"),
    ]
    for key, title, url, method in targets:
        try:
            request = urllib.request.Request(url, method=method, headers={"User-Agent": "probe/1.0"})
            started = time.perf_counter()
            with urllib.request.urlopen(request, timeout=15) as response:
                status = response.status
                length = response.headers.get("Content-Length", "?")
                content_type = response.headers.get("Content-Type", "?")
            elapsed = (time.perf_counter() - started) * 1000
            record(
                key,
                title,
                "pass" if status == 200 else "warn",
                f"HTTP {status} · {content_type} · {length} bytes · {elapsed:.0f}ms",
            )
        except urllib.error.HTTPError as error:
            record(key, title, "warn", f"HTTP {error.code}")
        except Exception as error:  # noqa: BLE001
            record(key, title, "fail", f"{type(error).__name__}: {error}")


# ---------------------------------------------------------------- 4. 备课依赖
def module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def probe_dependencies() -> None:
    print("\n=== 4. 备课流水线依赖 ===")
    needed = {
        "requests": "下载官方音频与页面",
        "bs4": "解析 BBC 页面找 MP3 / PDF 链接",
        "pypdf": "抽取 Transcript PDF 正文",
        "mutagen": "读音频时长（替代 ffprobe）",
        "faster_whisper": "词级时间戳对齐（首选）",
        "whisper": "词级时间戳对齐（备选）",
    }
    missing = []
    for module, purpose in needed.items():
        ok = module_available(module)
        if not ok:
            missing.append(module)
        record(f"dep_{module}", f"{module}（{purpose}）", "pass" if ok else "warn",
               "已安装" if ok else "未安装")

    if missing:
        record(
            "dep_summary",
            "缺失依赖",
            "warn",
            f"缺 {len(missing)} 个：{' '.join(missing)}",
            {"install_hint": "pip install " + " ".join(
                m.replace("bs4", "beautifulsoup4").replace("faster_whisper", "faster-whisper")
                for m in missing if m != "whisper"
            )},
        )
    else:
        record("dep_summary", "缺失依赖", "pass", "全部就绪")

    # pip 是否可用（只查询，不安装）
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True, text=True, timeout=30,
        )
        ok = completed.returncode == 0
        record("pip", "pip 可用性", "pass" if ok else "warn",
               completed.stdout.strip()[:90] if ok else "pip 不可用")
    except Exception as error:  # noqa: BLE001
        record("pip", "pip 可用性", "warn", f"{type(error).__name__}: {error}")


# ---------------------------------------------------------------- 5. Whisper 实测
def probe_whisper(audio_path: str | None) -> None:
    print("\n=== 5. 本地 Whisper 实测 ===")
    if not module_available("faster_whisper"):
        record("whisper_run", "Whisper 转写实测", "skip",
               "faster-whisper 未安装，先装再重跑本项")
        return
    if not audio_path:
        record("whisper_run", "Whisper 转写实测", "skip",
               "未提供音频，用 --audio 某个.mp3 重跑本项")
        return

    source = Path(audio_path)
    if not source.exists():
        record("whisper_run", "Whisper 转写实测", "fail", f"找不到音频 {source}")
        return

    try:
        from faster_whisper import WhisperModel  # noqa: PLC0415

        load_started = time.perf_counter()
        model = WhisperModel("base.en", device="cpu", compute_type="int8")
        load_seconds = time.perf_counter() - load_started

        run_started = time.perf_counter()
        segments, info = model.transcribe(str(source), word_timestamps=True, language="en")
        words = 0
        last_end = 0.0
        for segment in segments:
            last_end = max(last_end, segment.end)
            words += len(segment.words or [])
        run_seconds = time.perf_counter() - run_started

        ratio = run_seconds / info.duration if info.duration else 0
        record(
            "whisper_run",
            "Whisper 转写实测",
            "pass" if ratio < 1.5 else "warn",
            f"音频 {info.duration:.0f}s → 耗时 {run_seconds:.0f}s（{ratio:.2f}× 实时）· {words} 个词级时间戳",
            {
                "modelLoadSeconds": round(load_seconds, 1),
                "transcribeSeconds": round(run_seconds, 1),
                "audioSeconds": round(info.duration, 1),
                "realtimeRatio": round(ratio, 2),
                "wordCount": words,
                "lastEnd": round(last_end, 2),
            },
        )
    except Exception as error:  # noqa: BLE001
        record("whisper_run", "Whisper 转写实测", "fail", f"{type(error).__name__}: {error}")


# ---------------------------------------------------------------- 汇总
def summarize() -> dict:
    counts = {state: sum(1 for item in results if item["state"] == state)
              for state in ("pass", "warn", "fail", "skip")}

    def state_of(key: str) -> str:
        for item in results:
            if item["key"] == key:
                return item["state"]
        return "skip"

    verdicts = {
        "localhost_recording": (
            "可行：沙箱能起 localhost 服务，网页录音这条路是通的"
            if state_of("localhost_http") == "pass"
            else "不可行：沙箱起不了本地服务，网页录音需改用系统录音机降级"
        ),
        "bbc_pipeline": {
            "pass": "可行：能直连 BBC 官方来源",
            "warn": "可疑：BBC 返回了非 200，换一期再试",
            "fail": "受阻：拿不到 BBC 官方资源，备课链路需要代理或人工下载",
            "skip": "未测：本次跳过了出网测试",
        }[state_of("bbc_asset")],
        "whisper": {
            "pass": "可行：本地 Whisper 能跑，耗时已记录",
            "warn": "偏慢：能跑但耗时超过音频时长的 1.5 倍，备课要等",
            "fail": "不可行：Whisper 报错，见 detail",
            "skip": "未测：缺依赖或未提供音频",
        }[state_of("whisper_run")],
    }

    payload = {
        "probe": "workbuddy-sandbox",
        "version": 1,
        "capturedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "counts": counts,
        "verdicts": verdicts,
        "checks": results,
    }
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 58)
    print(f"通过 {counts['pass']} · 降级 {counts['warn']} · 失败 {counts['fail']} · 跳过 {counts['skip']}")
    print("-" * 58)
    for name, text in verdicts.items():
        print(f"  {name:22} {text}")
    print("=" * 58)
    print(f"完整结果已写入：{REPORT}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="WorkBuddy 沙箱能力探针")
    parser.add_argument("--audio", help="用于实测 Whisper 耗时的音频文件（可选）")
    parser.add_argument("--skip-network", action="store_true", help="跳过出网测试")
    args = parser.parse_args()

    print("WorkBuddy 沙箱能力探针 v1")
    print(f"脚本位置：{HERE}")

    probe_environment()
    probe_localhost()
    if not args.skip_network:
        probe_network()
    else:
        record("network", "出网测试", "skip", "已按参数跳过")
    probe_dependencies()
    probe_whisper(args.audio)
    summarize()


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import secrets
import sys
import threading
import time
import traceback
from datetime import datetime, time as clock_time, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .builder import build_from_external_draft, build_next_course
from .course import CourseBuildError, build_demo_package
from .settings import load_settings, save_settings

WEEKDAY_LABELS = {1: "周一", 2: "周二", 3: "周三", 4: "周四", 5: "周五", 6: "周六", 7: "周日"}


def _status() -> dict[str, object]:
    settings = load_settings()
    schedule = settings["schedule"]
    labels = "、".join(WEEKDAY_LABELS.get(day, str(day)) for day in schedule.get("days", []))
    return {
        "nextRun": f"{labels} {schedule['time']} · {schedule.get('timezone', 'local')}",
        "lastResult": settings.get("last_result"),
        "courseDirectory": settings["course_directory"],
        "needsPair": not bool(settings.get("pairing_token")),
    }


def _run_scheduled_build() -> str:
    settings = load_settings()
    try:
        if not (settings["model"].get("base_url") and settings["model"].get("model")):
            result = "已跳过：尚未配置本地模型，未下载 BBC 素材。"
        else:
            result = f"已写入课程：{build_next_course(settings).name}。"
    except CourseBuildError as error:
        result = str(error)
    settings["last_run"] = datetime.now().astimezone().isoformat(timespec="seconds")
    settings["last_result"] = result
    save_settings(settings)
    return result


def _schedule_loop() -> None:
    """On resume, run at most the latest missed scheduled slot."""
    last_seen = datetime.now().astimezone()
    while True:
        settings = load_settings()
        schedule = settings["schedule"]
        try:
            now = datetime.now(ZoneInfo(schedule.get("timezone", "Asia/Shanghai")))
        except ZoneInfoNotFoundError:
            now = datetime.now().astimezone()
        try:
            scheduled_time = clock_time.fromisoformat(schedule["time"])
            missed = []
            for offset in range(8):
                day = now.date() - timedelta(days=offset)
                candidate = datetime.combine(day, scheduled_time, tzinfo=now.tzinfo)
                if day.isoweekday() in schedule.get("days", []) and last_seen < candidate <= now:
                    missed.append(candidate)
            if missed:
                _run_scheduled_build()
        except (TypeError, ValueError):
            pass
        last_seen = now
        time.sleep(20)


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, value: dict[str, object]) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "null"))
        self.send_header("Vary", "Origin")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        return self.headers.get("X-Clear-English-Token", "") == load_settings().get("pairing_token", "")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "null"))
        self.send_header("Access-Control-Allow-Methods", "GET,POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,X-Clear-English-Token")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/status":
            self._json(200, _status())
        elif self.path == "/courses":
            if not self._authorized():
                self._json(401, {"error": "pairing_required"})
                return
            directory = Path(load_settings()["course_directory"])
            self._json(200, {"courses": [{"id": item.stem, "filename": item.name} for item in directory.glob("*.zip")]})
        elif self.path.startswith("/courses/"):
            if not self._authorized():
                self._json(401, {"error": "pairing_required"})
                return
            target = Path(load_settings()["course_directory"]) / f"{unquote(self.path.removeprefix('/courses/'))}.zip"
            if not target.is_file():
                self._json(404, {"error": "course_not_found"})
                return
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "null"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/settings":
            if not self._authorized(): self._json(401, {"error": "pairing_required"})
            else: self._json(200, load_settings())
        else:
            self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path == "/pair":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                code = json.loads(self.rfile.read(length) or "{}").get("code", "")
                settings = load_settings()
                if code != settings.get("pairing_code"):
                    self._json(403, {"error": "invalid_pairing_code"})
                    return
                settings["pairing_token"] = secrets.token_urlsafe(32)
                settings["pairing_code"] = secrets.token_urlsafe(12)
                save_settings(settings)
                self._json(200, {"token": settings["pairing_token"]})
            except (ValueError, json.JSONDecodeError):
                self._json(400, {"error": "invalid_pairing_request"})
            return
        if not self._authorized():
            self._json(401, {"error": "pairing_required"})
            return
        if self.path == "/settings":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                incoming = json.loads(self.rfile.read(length) or "{}")
                settings = load_settings()
                settings.update({key: value for key, value in incoming.items() if key in {"course_directory", "schedule"}})
                save_settings(settings)
                self._json(200, {"result": "设置已保存到本机。"})
            except (ValueError, json.JSONDecodeError):
                self._json(400, {"error": "invalid_settings"})
            return
        if self.path != "/run":
            self._json(404, {"error": "not_found"})
            return
        settings = load_settings()
        target = Path(settings["course_directory"]) / "demo-local.zip"
        try:
            configured = bool(settings["model"].get("base_url") and settings["model"].get("model"))
            result = build_next_course(settings) if configured else build_demo_package(target)
            settings["last_result"] = f"已写入课程：{result.name}。" if configured else f"已写入合成演示课程：{result.name}。配置模型后可启用 BBC 正式备课。"
            save_settings(settings)
            self._json(200, {"result": settings["last_result"]})
        except CourseBuildError as error:
            self._json(400, {"result": str(error)})

    def log_message(self, *_: object) -> None:
        return


def main() -> int:
    """Entry point that always exits with a code, never a stack trace.

    The desktop shell surfaces the last stderr line to the user, so an
    unhandled exception here would put a Python traceback in front of a
    beginner instead of an actionable message.
    """
    try:
        return _main()
    except CourseBuildError as error:
        print(str(error), file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print("build_cancelled", file=sys.stderr, flush=True)
        return 1
    except Exception as error:  # noqa: BLE001 - last line of defence
        traceback.print_exc(file=sys.stderr)
        print(f"unexpected_engine_error: {type(error).__name__}", file=sys.stderr, flush=True)
        return 1


def _main() -> int:
    # The desktop shell reads these pipes as UTF-8. Without this, a Chinese
    # Windows would emit code-page bytes and mangle progress text and paths.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Clear English local course agent")
    parser.add_argument("command", nargs="?", default="serve",
                        choices=["serve", "demo-package", "status", "run-scheduled", "build-draft", "import-player"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--draft", type=Path)
    parser.add_argument("--html", type=Path, help="a weekly BBC shadow-reading player page to import")
    args = parser.parse_args()
    if args.command == "demo-package":
        output = args.output or Path(load_settings()["course_directory"]) / "demo-local.zip"
        print(build_demo_package(output))
        return 0
    if args.command == "status":
        print(json.dumps(_status(), ensure_ascii=False))
        return 0
    if args.command == "run-scheduled":
        print(_run_scheduled_build())
        return 0
    if args.command == "build-draft":
        if not args.draft:
            parser.error("build-draft requires --draft")
        print(build_from_external_draft(args.draft, load_settings()))
        return 0
    if args.command == "import-player":
        if not args.html:
            parser.error("import-player requires --html")
        from .player_import import build_from_player_html
        print(build_from_player_html(args.html, load_settings()))
        return 0
    settings = load_settings()
    print(f"bbc-course-agent listening only on http://127.0.0.1:8765\npairing code: {settings['pairing_code']}")
    threading.Thread(target=_schedule_loop, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

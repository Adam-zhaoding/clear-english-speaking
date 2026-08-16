from __future__ import annotations

import json
import os
import platform
import secrets
from pathlib import Path
from typing import Any


def app_dir() -> Path:
    configured = os.environ.get("CLEAR_ENGLISH_HOME")
    if configured:
        return Path(configured)
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "EnglishSpeakingPlayer"
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local")) / "EnglishSpeakingPlayer"


def default_settings() -> dict[str, Any]:
    root = app_dir()
    return {
        "course_directory": str(root / "courses"),
        "schedule": {"days": [1, 3, 6], "time": "17:30", "timezone": "Asia/Shanghai"},
        "model": {"base_url": "", "model": "", "api_key_ref": "clear-english-model-key"},
        "bbc_index_url": "https://www.bbc.com/learningenglish/english/features/6-minute-english",
        "whisper_model": "small",
        "last_run": None,
        "last_result": "尚未运行"
    }


def settings_path() -> Path:
    return app_dir() / "settings.json"


def load_settings() -> dict[str, Any]:
    path = settings_path()
    if not path.exists():
        result = default_settings()
    else:
        result = {**default_settings(), **json.loads(path.read_text(encoding="utf-8"))}
    if not result.get("pairing_code"):
        result["pairing_code"] = secrets.token_urlsafe(12)
    save_settings(result)
    return result


def save_settings(data: dict[str, Any]) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def get_model_key(reference: str) -> str:
    try:
        import keyring  # type: ignore
        return keyring.get_password("clear-english", reference) or ""
    except ImportError:
        return ""

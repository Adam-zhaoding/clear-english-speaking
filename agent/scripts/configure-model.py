"""Store the user-owned model configuration without placing the API key in JSON."""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.bbc_course_agent.settings import load_settings, save_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure a local OpenAI-compatible model for Clear English")
    parser.add_argument("--base-url", required=True, help="Example: https://api.example.com/v1")
    parser.add_argument("--model", required=True, help="Model identifier supplied by your provider")
    args = parser.parse_args()
    try:
        import keyring  # type: ignore
    except ImportError:
        print("Install keyring first: python -m pip install keyring")
        return 2
    secret = getpass.getpass("API key (stored only in the OS credential store): ")
    if not secret:
        print("No API key entered; nothing changed.")
        return 1
    settings = load_settings()
    reference = settings["model"]["api_key_ref"]
    keyring.set_password("clear-english", reference, secret)
    settings["model"].update({"base_url": args.base_url.rstrip("/"), "model": args.model})
    save_settings(settings)
    print("Model configuration saved. The API key was not written to settings.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Minimal configuration; no required third-party packages."""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def db_path() -> Path:
    raw = os.getenv("EMPORIO_DB", "data/emporio.sqlite")
    path = Path(raw).expanduser()
    return path if path.is_absolute() else ROOT / path


def demo_dir() -> Path:
    return ROOT / "data" / "demo"


def load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env", override=False)

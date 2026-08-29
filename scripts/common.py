#!/usr/bin/env python3
"""パスと日時まわりの共通処理。collect.py と build_html.py が共有する。"""

from pathlib import Path
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config" / "keywords.json"
DATA_FILE = BASE_DIR / "data" / "posts.json"


def now_jst_iso():
    """現在時刻を JST の ISO8601 文字列で返す。"""
    return datetime.now(JST).isoformat()


def parse_timestamp(ts):
    """
    投稿時刻 ('2026-08-29T10:30:00+0000' 形式) を datetime に。
    パースできなければ None。
    """
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    return None

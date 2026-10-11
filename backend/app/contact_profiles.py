import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


ROOT = Path("/home/admin/jessyca-whatsapp")
DATA_DIR = ROOT / "data"
PROFILE_FILE = DATA_DIR / "contact_profiles.json"

_lock = Lock()


def _now():
    return datetime.now(
        timezone.utc
    ).isoformat()


def _load():
    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not PROFILE_FILE.exists():
        return {}

    try:
        with PROFILE_FILE.open(
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        if isinstance(data, dict):
            return data

    except Exception:
        pass

    return {}


def _save(data):
    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp = PROFILE_FILE.with_suffix(
        ".json.tmp"
    )

    with temp.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )

        f.flush()
        os.fsync(
            f.fileno()
        )

    os.replace(
        temp,
        PROFILE_FILE,
    )


def get_profile(chat_id):
    with _lock:
        data = _load()

        profile = data.get(
            chat_id,
            {},
        )

        if not isinstance(
            profile,
            dict,
        ):
            return {}

        return dict(profile)


def update_profile(
    chat_id,
    updates,
):
    with _lock:
        data = _load()

        profile = data.get(
            chat_id,
            {},
        )

        if not isinstance(
            profile,
            dict,
        ):
            profile = {}

        if not isinstance(
            updates,
            dict,
        ):
            updates = {}

        for key, value in updates.items():
            if value is None:
                continue

            profile[key] = value

        profile[
            "last_interaction"
        ] = _now()

        data[chat_id] = profile

        _save(data)

        return dict(profile)


def add_pending(
    chat_id,
    text,
):
    text = str(
        text
    ).strip()

    if not text:
        return get_profile(
            chat_id
        )

    with _lock:
        data = _load()

        profile = data.get(
            chat_id,
            {},
        )

        if not isinstance(
            profile,
            dict,
        ):
            profile = {}

        pending = profile.get(
            "pending",
            [],
        )

        if not isinstance(
            pending,
            list,
        ):
            pending = []

        normalized = {
            str(item).strip().lower()
            for item in pending
            if str(item).strip()
        }

        if (
            text.lower()
            not in normalized
        ):
            pending.append(
                text[:180]
            )

        profile["pending"] = (
            pending[-20:]
        )

        profile[
            "last_interaction"
        ] = _now()

        data[chat_id] = profile

        _save(data)

        return dict(profile)


def clear_pending(
    chat_id,
):
    return update_profile(
        chat_id,
        {
            "pending": [],
        },
    )


def set_priority(
    chat_id,
    priority,
):
    allowed = {
        "normal",
        "important",
        "urgent",
    }

    if priority not in allowed:
        priority = "normal"

    return update_profile(
        chat_id,
        {
            "priority": priority,
        },
    )

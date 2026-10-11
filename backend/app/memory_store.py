import json
import os
from collections import OrderedDict
from pathlib import Path

ROOT = Path("/home/admin/jessyca-whatsapp")
DATA_DIR = ROOT / "data"
MEMORY_FILE = DATA_DIR / "conversations.json"

MAX_CONVERSATIONS = 200
MAX_MESSAGES_PER_CHAT = 8


def load_histories():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not MEMORY_FILE.exists():
        return OrderedDict()

    try:
        with MEMORY_FILE.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        histories = OrderedDict()

        for chat_id, messages in raw.items():
            if not isinstance(chat_id, str):
                continue

            if not isinstance(messages, list):
                continue

            clean_messages = []

            for message in messages[-MAX_MESSAGES_PER_CHAT:]:
                if not isinstance(message, dict):
                    continue

                role = message.get("role")
                content = message.get("content")

                if role not in ("user", "assistant"):
                    continue

                if not isinstance(content, str):
                    continue

                clean_messages.append({
                    "role": role,
                    "content": content[:600],
                })

            if clean_messages:
                histories[chat_id] = clean_messages

        while len(histories) > MAX_CONVERSATIONS:
            histories.popitem(last=False)

        return histories

    except Exception:
        # Si el JSON se corrompe, no impedimos que Jessyca arranque.
        return OrderedDict()


def save_histories(histories):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    serializable = OrderedDict()

    items = list(histories.items())[-MAX_CONVERSATIONS:]

    for chat_id, messages in items:
        serializable[str(chat_id)] = messages[-MAX_MESSAGES_PER_CHAT:]

    temp_file = MEMORY_FILE.with_suffix(".json.tmp")

    with temp_file.open("w", encoding="utf-8") as f:
        json.dump(
            serializable,
            f,
            ensure_ascii=False,
            indent=2,
        )
        f.flush()
        os.fsync(f.fileno())

    os.replace(temp_file, MEMORY_FILE)

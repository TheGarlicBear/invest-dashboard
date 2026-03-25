
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Tuple, Dict, Any

DATA_DIR = Path("data/auth")
USERS_PATH = DATA_DIR / "users.json"
APP_SALT = "invest-dashboard-v13"


def hash_password(username: str, password: str) -> str:
    raw = f"{APP_SALT}:{username.strip().lower()}:{password}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def seed_default_users() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if USERS_PATH.exists():
        return
    default = {
        "master": {
            "password_hash": hash_password("master", "master123!"),
            "role": "admin"
        },
        "wife": {
            "password_hash": hash_password("wife", "wife123!"),
            "role": "user"
        }
    }
    USERS_PATH.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")


def load_users() -> Dict[str, Any]:
    seed_default_users()
    return json.loads(USERS_PATH.read_text(encoding="utf-8"))


def verify_login(username: str, password: str) -> Tuple[bool, Dict[str, Any]]:
    users = load_users()
    info = users.get(username)
    if not info:
        return False, {}
    if info.get("password_hash") != hash_password(username, password):
        return False, {}
    return True, info

"""Two-step Telegram auth for non-interactive environments (Claude Code bash)."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from telethon.errors import SessionPasswordNeededError

from .config import DATA_DIR, load_settings
from .telegram_client import make_client

STATE_FILE = DATA_DIR / "auth_state.json"


async def _request() -> None:
    settings = load_settings()
    client = make_client(settings)
    await client.connect()
    try:
        if await client.is_user_authorized():
            print("Уже авторизован. Сессия готова, можно запускать sync.")
            return
        sent = await client.send_code_request(settings.phone)
        STATE_FILE.write_text(
            json.dumps({"phone": settings.phone, "phone_code_hash": sent.phone_code_hash})
        )
        print(
            f"Код отправлен на {settings.phone}. "
            f"Проверь Telegram и передай код через `auth submit <code>` "
            f"(или с --password, если включена 2FA)."
        )
    finally:
        await client.disconnect()


async def _submit(code: str, password: str | None) -> None:
    settings = load_settings()
    if not STATE_FILE.exists():
        raise SystemExit("Нет auth_state.json — сначала запусти `auth request`.")
    state = json.loads(STATE_FILE.read_text())

    client = make_client(settings)
    await client.connect()
    try:
        if await client.is_user_authorized():
            print("Уже авторизован. Ничего не делаю.")
            return
        try:
            await client.sign_in(
                phone=state["phone"],
                code=code,
                phone_code_hash=state["phone_code_hash"],
            )
        except SessionPasswordNeededError:
            if not password:
                raise SystemExit("Включена 2FA. Перезапусти с --password <your_2fa_password>.")
            await client.sign_in(password=password)

        me = await client.get_me()
        print(f"Успешно вошли как {me.first_name} (@{me.username}), id={me.id}")
        STATE_FILE.unlink(missing_ok=True)
    finally:
        await client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Topic Race — two-step Telegram auth")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("request", help="Send a login code to your phone")
    p_submit = sub.add_parser("submit", help="Submit the login code (and optional 2FA password)")
    p_submit.add_argument("code", help="Login code received in Telegram")
    p_submit.add_argument("--password", help="Cloud password if 2FA is enabled", default=None)
    args = parser.parse_args()

    if args.cmd == "request":
        asyncio.run(_request())
    elif args.cmd == "submit":
        asyncio.run(_submit(args.code, args.password))


if __name__ == "__main__":
    main()

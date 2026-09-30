"""Secure Apple login and session storage for the isolated modern FindMy runtime."""
import getpass
import json
import os
from pathlib import Path

from findmy.reports import AsyncAppleAccount, LoginState
from findmy.reports.anisette import LocalAnisetteProvider
from findmy.reports.twofactor import SmsSecondFactorMethod, TrustedDeviceSecondFactorMethod

import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / 'backend'))
from settings import data_path
FINDMY_DATA = data_path(PROJECT_ROOT) / 'findmy'
ACCOUNT_STORE = FINDMY_DATA / 'account.json'
ANISETTE_LIBS = FINDMY_DATA / 'ani_libs.bin'


def _save_account(account, path: Path = ACCOUNT_STORE) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as session_file:
        json.dump(account.to_json(), session_file)
    os.chmod(path, 0o600)


async def _login_async(account: AsyncAppleAccount) -> None:
    email = input("Apple account email: ")
    password = getpass.getpass("Apple password: ")
    state = await account.login(email, password)

    if state == LoginState.REQUIRE_2FA:
        methods = await account.get_2fa_methods()
        for index, method in enumerate(methods):
            if isinstance(method, TrustedDeviceSecondFactorMethod):
                print(f"{index} - Trusted device")
            elif isinstance(method, SmsSecondFactorMethod):
                print(f"{index} - SMS ({method.phone_number})")
        choice = int(input("Verification method number: "))
        if choice < 0 or choice >= len(methods):
            raise ValueError("Invalid verification method")
        method = methods[choice]
        await method.request()
        code = getpass.getpass("Verification code: ")
        state = await method.submit(code)

    if state != LoginState.LOGGED_IN:
        raise RuntimeError("Apple login did not complete")


async def get_account_async() -> AsyncAppleAccount:
    """Restore the local-Anisette session or create one interactively."""
    if ACCOUNT_STORE.exists():
        os.chmod(ACCOUNT_STORE, 0o600)
        account = AsyncAppleAccount.from_json(
            ACCOUNT_STORE, anisette_libs_path=ANISETTE_LIBS
        )
        return account

    ANISETTE_LIBS.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(ANISETTE_LIBS.parent, 0o700)
    account = AsyncAppleAccount(LocalAnisetteProvider(libs_path=ANISETTE_LIBS))
    try:
        # Generate Anisette locally before asking for any Apple credentials.
        await account.get_anisette_headers()
        await _login_async(account)
        _save_account(account)
        return account
    except BaseException:
        await account.close()
        raise

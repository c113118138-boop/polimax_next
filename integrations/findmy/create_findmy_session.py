"""Interactively create the Apple session used by the FindMy importer."""
import asyncio
from pathlib import Path
import sys

from _login import get_account_async, ACCOUNT_STORE
from findmy.errors import InvalidCredentialsError


async def main():
    account = await get_account_async()
    try:
        print(f"Apple session ready: {ACCOUNT_STORE}")
    finally:
        await account.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except InvalidCredentialsError:
        print(
            "Apple rejected password authentication. Verify the account and password "
            "with Apple directly; no session was saved.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    except RuntimeError as error:
        print(f"Session setup stopped: {error}", file=sys.stderr)
        raise SystemExit(1) from None

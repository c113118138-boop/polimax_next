# FindMy PostgreSQL import

`findmyupdate.py` now reads enabled device keys from PostgreSQL `BeaconList` and
appends each fetched location to both `FindMy` and `new_reports` in the same
PostgreSQL transaction. This keeps the existing FindMy endpoint and history
retention/archive rules working without using the legacy MySQL connection.

This host has the isolated FindMy 0.10.2 runtime installed at
`/home/c113118138/.venvs/polimax-findmy`. To recreate it on a fresh host:

```sh
python3 -m venv /home/c113118138/.venvs/polimax-findmy
/home/c113118138/.venvs/polimax-findmy/bin/python -m pip install -r /home/c113118138/polimax_carAPI_on/requirements-findmy.txt
```

Create the Apple session interactively on the host. The password and 2FA code
are hidden while typed, and the resulting `account.json` is restricted to the
service account (`0600`):

```sh
cd /home/c113118138/polimax_carAPI_on
/home/c113118138/.venvs/polimax-findmy/bin/python create_findmy_session.py
```

Complete any Apple 2FA prompt on the trusted device or by SMS. Keep
`account.json` private; it contains session credentials and must not be
committed, copied into logs, or sent in chat. FindMy 0.10 generates Anisette
data locally, so this flow no longer depends on the unavailable remote
Anisette server. The library downloads its Apple support bundle on first use
and caches it under `/home/c113118138/.local/share/polimax-findmy/`. The
scheduled importer runs once per hour. This host already has its user-level
timer enabled; it skips the import until `account.json` exists. Once the session
is ready, start an immediate import with:

```sh
systemctl --user start polimax-findmy-import.service
```

The service uses `/home/c113118138/.venvs/polimax-findmy` and requires the
session file in its working directory; it will not prompt for credentials.

Run a one-time import manually with:

```sh
cd /home/c113118138/polimax_carAPI_on
/home/c113118138/.venvs/polimax-findmy/bin/python findmyupdate.py
```

The importer refuses any configured database other than PostgreSQL
`polimax_PostgreSQL`. It does not log private keys, coordinates, or report
contents.

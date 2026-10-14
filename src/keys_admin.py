"""Manage the hosted service's API keys from the command line.

Usage, on the server:

    python -m src.keys_admin list [EMAIL OR PREFIX]
    python -m src.keys_admin issue EMAIL
    python -m src.keys_admin revoke ID

The key database comes from --database or API_KEY_DATABASE. Keys are stored
only as hashes, so `list` shows each key's prefix; `issue` prints a new key
once, and replaces any key that address had.
"""

from __future__ import annotations

import argparse
import os
import sys

from src.core.api_keys import KeyStore, normalize_email


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.keys_admin", description="Manage API keys.")
    parser.add_argument("--database", default=os.environ.get("API_KEY_DATABASE"), help="SQLite key database")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="List keys, newest first")
    listing.add_argument("query", nargs="?", default="", help="Part of an email address or key prefix")
    issuing = commands.add_parser("issue", help="Issue a key for an email address, replacing its current key")
    issuing.add_argument("email")
    revoking = commands.add_parser("revoke", help="Revoke a key by id")
    revoking.add_argument("id", type=int)
    args = parser.parse_args(argv)

    if not args.database:
        parser.error("Set API_KEY_DATABASE or pass --database.")
    store = KeyStore(args.database)

    if args.command == "list":
        keys = store.find(args.query)
        print(f"{'ID':>5}  {'PREFIX':<12}  {'STATUS':<7}  {'CREATED':<25}  {'LAST USED':<25}  EMAIL")
        for key in keys:
            status = "active" if key.active else "revoked"
            print(
                f"{key.id:>5}  {key.prefix:<12}  {status:<7}  {key.created_at:<25}  {key.last_used_at or '-':<25}  {key.email}"
            )
        print(f"{len(keys)} key(s)")
        return 0

    if args.command == "issue":
        email = normalize_email(args.email)
        if email is None:
            parser.error(f"{args.email!r} is not a valid email address.")
        new_key, record = store.issue(email)
        print(f"Key {record.id} for {email} (any earlier key for this address is revoked):")
        print(new_key)
        return 0

    if store.revoke(args.id):
        print(f"Revoked key {args.id}.")
        return 0
    print(f"No active key with id {args.id}.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

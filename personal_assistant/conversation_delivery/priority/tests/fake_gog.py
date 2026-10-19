#!/usr/bin/env python3
"""Deterministic fake gog executable used only by the offline CLI tests.

The fixture is selected with FAKE_GOG_FIXTURE.  It deliberately accepts the
same global flag placement as the collector and records argv when requested.
It never opens a network connection; DENY_NETWORK is an explicit test guard.
"""
from __future__ import annotations

import json
import os
import pathlib
import socket
import sys


def main() -> int:
    if os.environ.get("DENY_NETWORK") == "1":
        original = socket.socket
        class DeniedSocket(original):
            def connect(self, *args, **kwargs):
                raise AssertionError("network is denied in the fake provider")
        socket.socket = DeniedSocket
    fixture = json.loads(pathlib.Path(os.environ["FAKE_GOG_FIXTURE"]).read_text(encoding="utf-8"))
    if os.environ.get("FAKE_GOG_ARGV_LOG"):
        log_path = pathlib.Path(os.environ["FAKE_GOG_ARGV_LOG"])
        with log_path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\n")
    args = sys.argv[1:]
    if "gmail" not in args:
        return 41
    gmail_index = args.index("gmail")
    if gmail_index + 2 < len(args) and args[gmail_index + 1:gmail_index + 3] == ["messages", "search"]:
        operation = "search"
        operation_index = gmail_index + 2
    elif gmail_index + 1 < len(args) and args[gmail_index + 1] == "get":
        operation = "get"
        operation_index = gmail_index + 1
    else:
        return 43
    account = args[args.index("-a") + 1] if "-a" in args else ""
    query = args[operation_index + 1] if operation == "search" else ""
    page = next((item.split("=", 1)[1] for item in args if item.startswith("--page=")), "")
    target = args[operation_index + 1] if operation == "get" else ""
    key = f"{account}|{operation}|{query}|{page}" if operation == "search" else f"{account}|{operation}|{target}"
    response = fixture.get(key, fixture.get(f"{account}|{operation}|{page}", fixture.get(f"{account}|{operation}")))
    if isinstance(response, dict) and response.get("__exit__"):
        return int(response["__exit__"])
    if response is None:
        return 42
    print(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

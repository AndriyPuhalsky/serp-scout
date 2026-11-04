#!/usr/bin/env python3
"""Локальний статичний сервер для site/ (перегляд сайту-звіту без Netlify). Лише stdlib.

  python3 tools/serve.py [--port 8765] [--dir site]

Віддає файли без кешу (щоб правки CSS/JS і report.json було видно одразу), з правильними
MIME для .mjs і .json. Слухає лише 127.0.0.1. Зупинка — Ctrl+C.
"""
import argparse
import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = "127.0.0.1"
PORT = 8765


class NoCacheHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".mjs": "text/javascript",
        ".js": "text/javascript",
        ".json": "application/json",
        ".svg": "image/svg+xml",
        ".webmanifest": "application/manifest+json",
    }

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write(f"{self.address_string()} — {fmt % args}\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--dir", default=os.path.join(ROOT_DIR, "site"), help="тека сайту (типово site/)")
    args = ap.parse_args(argv)
    directory = os.path.abspath(args.dir)
    if not os.path.isdir(directory):
        sys.stderr.write(f"Теки {directory} немає — спершу зберіть сайт (`uv run serp-scout build-site`).\n")
        return 1
    handler = partial(NoCacheHandler, directory=directory)
    try:
        server = ThreadingHTTPServer((HOST, args.port), handler)
    except OSError as e:
        sys.stderr.write(f"Не вдалося зайняти {HOST}:{args.port}: {e}\n")
        return 1
    print(f"Сайт: http://{HOST}:{args.port}/  (тека {directory}; зупинка — Ctrl+C)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nЗупинено.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Small static file server for Simple Dash.

Like `python -m http.server`, but suppresses noisy BrokenPipe/ConnectionReset
tracebacks that happen when browsers cancel requests during reloads.
"""

from __future__ import annotations

import argparse
import errno
import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class QuietStaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        # Keep logs useful but compact.
        print(f"{self.address_string()} - {fmt % args}", flush=True)

    def copyfile(self, source, outputfile) -> None:  # type: ignore[override]
        try:
            super().copyfile(source, outputfile)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # Browser navigated away / refreshed / cancelled asset request.
            pass
        except OSError as exc:
            if exc.errno in {errno.EPIPE, errno.ECONNRESET, errno.ECONNABORTED}:
                pass
            else:
                raise


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve Simple Dash static files")
    parser.add_argument("--port", "-p", type=int, default=int(os.environ.get("PORT", "8080")))
    parser.add_argument("--directory", "-d", default=os.environ.get("DIRECTORY", "."))
    parser.add_argument("--bind", default=os.environ.get("BIND", "0.0.0.0"))
    parser.add_argument("--pid-file", default=os.environ.get("PID_FILE", ""))
    args = parser.parse_args()

    directory = Path(args.directory).resolve()
    handler = partial(QuietStaticHandler, directory=str(directory))
    try:
        server = QuietThreadingHTTPServer((args.bind, args.port), handler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(
                f"Port {args.port} is already in use. Stop the old server with `just stop-local` "
                f"or choose another port: HTTP_PORT={args.port + 1} just dev",
                file=sys.stderr,
                flush=True,
            )
            raise SystemExit(98) from None
        raise
    pid_path = Path(args.pid_file) if args.pid_file else None
    if pid_path:
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
    print(f"Serving {directory} on http://{args.bind}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if pid_path:
            try:
                if pid_path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                    pid_path.unlink()
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    main()

"""A stand-in for llama-server.exe used by tests/test_llama_server_supervisor.py.

Accepts the arguments the supervisor passes, serves /health (503 while
"loading", then 200) and /v1/models (the alias). Environment knobs:
FAKE_LOAD_SECONDS, FAKE_WRONG_MODEL=1, FAKE_EXIT_AFTER (seconds, then exits 3).
"""

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def arg(name, default=""):
    argv = sys.argv[1:]
    return argv[argv.index(name) + 1] if name in argv else default


PORT = int(arg("--port", "8090"))
ALIAS = arg("--alias", "model")
READY_AT = time.time() + float(os.environ.get("FAKE_LOAD_SECONDS", "0.3"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            if time.time() < READY_AT:
                self._send(503, {"error": {"message": "Loading model"}})
            else:
                self._send(200, {"status": "ok"})
        elif self.path == "/v1/models":
            model = "something-else" if os.environ.get("FAKE_WRONG_MODEL") else ALIAS
            self._send(200, {"data": [{"id": model}]})
        else:
            self._send(404, {})


exit_after = os.environ.get("FAKE_EXIT_AFTER")
if exit_after:
    threading.Timer(float(exit_after), lambda: os._exit(3)).start()

print(f"fake llama-server on {PORT} serving {ALIAS}", flush=True)
ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

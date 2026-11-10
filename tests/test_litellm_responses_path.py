"""LiteLLM's Responses API works with the installed packages.

v1.6.1 shipped LiteLLM 1.108, which needs mcp 2.x, next to mcp 1.27: every
Responses API call (A0W uses it for some providers, LM Studio included)
failed with `cannot import name 'CacheableResult' from 'mcp.types'` while
plain completion calls worked, so nothing noticed. This makes a real
Responses API call through the LM Studio provider against a local stand-in
server, so a package combination that breaks that path fails here.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

litellm = pytest.importorskip("litellm")


def _chat_completion() -> dict:
    return {
        "id": "chatcmpl-test", "object": "chat.completion", "created": int(time.time()), "model": "stand-in",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
    }


def _response() -> dict:
    return {
        "id": "resp-test", "object": "response", "created_at": int(time.time()), "model": "stand-in", "status": "completed",
        "output": [{"type": "message", "id": "msg-test", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": "ok", "annotations": []}]}],
        "usage": {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
    }


class _StandIn(BaseHTTPRequestHandler):
    paths: list = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        self.rfile.read(length)
        type(self).paths.append(self.path)
        body = json.dumps(_response() if self.path.rstrip("/").endswith("/responses") else _chat_completion()).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def stand_in():
    _StandIn.paths = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StandIn)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()
    server.server_close()


def test_a_responses_call_through_lm_studio_works(stand_in):
    result = litellm.responses(model="lm_studio/stand-in", api_base=stand_in, api_key="test", input="Reply with: ok")
    assert "ok" in (getattr(result, "output_text", "") or json.dumps(result.model_dump(), default=str))
    assert _StandIn.paths, "the call never reached the server"


def test_a_completion_call_through_lm_studio_works(stand_in):
    result = litellm.completion(model="lm_studio/stand-in", api_base=stand_in, api_key="test",
                                messages=[{"role": "user", "content": "Reply with: ok"}])
    assert result.choices[0].message.content == "ok"

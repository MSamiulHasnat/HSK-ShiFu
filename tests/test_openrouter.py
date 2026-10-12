"""OpenRouter model chain, against a local fake of its chat-completions endpoint."""

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from agent.providers import FallbackProvider, OpenRouterProvider

REQUESTS: list[str] = []


class FakeOpenRouter(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        model = body["model"]
        REQUESTS.append(model)
        if model == "paid/model":  # account can't afford it
            self.send_response(402)
            self.end_headers()
            self.wfile.write(b'{"error":{"code":402,"message":"requires more credits"}}')
            return
        if model == "busy/model:free":
            self.send_response(429)
            self.end_headers()
            self.wfile.write(b'{"error":{"code":429,"message":"rate-limited upstream"}}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for piece in ("你好", "！"):
            self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {'content': piece}}]})}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")

    def log_message(self, *args):
        pass


class OpenRouterChain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeOpenRouter)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.env = {k: os.environ.get(k) for k in ("OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "OPENROUTER_MODEL")}
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        os.environ["OPENROUTER_BASE_URL"] = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        for k, v in cls.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def setUp(self):
        REQUESTS.clear()

    def test_unaffordable_and_rate_limited_models_fall_through(self):
        os.environ["OPENROUTER_MODEL"] = "paid/model,busy/model:free,good/model:free"
        p = OpenRouterProvider()
        self.assertEqual(p.chat("system", [{"role": "user", "content": "hi"}]), "你好！")
        self.assertEqual(REQUESTS, ["paid/model", "busy/model:free", "good/model:free"])
        self.assertEqual(p.label, "openrouter · good/model:free")

    def test_all_failing_raises_so_the_next_provider_runs(self):
        os.environ["OPENROUTER_MODEL"] = "paid/model,busy/model:free"
        with self.assertRaisesRegex(RuntimeError, "no credits.*rate-limited"):
            OpenRouterProvider().chat("system", [{"role": "user", "content": "hi"}])

    def test_fallback_provider_reports_the_model_that_answered(self):
        os.environ["OPENROUTER_MODEL"] = "paid/model,good/model:free"
        chain = FallbackProvider([OpenRouterProvider()])
        chain.chat("system", [{"role": "user", "content": "hi"}])
        self.assertEqual(chain.used, "openrouter · good/model:free")


if __name__ == "__main__":
    unittest.main()

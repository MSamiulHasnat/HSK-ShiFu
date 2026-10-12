"""The HTTP API, against a real server on a random local port (stdlib client, no extra packages)."""

import json
import socket
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

import uvicorn

from agent.server import app
from tests.helpers import ScriptedProvider, install_provider, use_temp_databases


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        use_temp_databases()
        cls.port = _free_port()
        cls.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=cls.port, log_level="error"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        while not cls.server.started:
            time.sleep(0.05)
        cls.provider = install_provider(ScriptedProvider(["好的！(Hǎo de!) 生日快乐！这是送给你的！(Shēngrì kuàilè! Zhè shì sòng gěi nǐ de!)"]))

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path):
        with urllib.request.urlopen(self.url(path)) as r:
            return json.loads(r.read())

    def assert_get_fails(self, path, code):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get(path)
        with cm.exception as e:
            self.assertEqual(e.code, code)

    def post(self, path, body):
        req = urllib.request.Request(self.url(path), data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def test_course_and_lesson(self):
        self.assertEqual([len(l["lessons"]) for l in self.get("/api/course")["levels"]], [15, 15, 20])
        lesson = self.get("/api/course/2/4")
        self.assertEqual(lesson["title_zh"], "这个工作是他帮我介绍的")
        self.assertEqual(self.post("/api/review/add", {"word_id": "nope"})[0], 404)
        self.assert_get_fails("/api/course/2/99", 404)

    def test_dictionary(self):
        hits = self.get("/api/words/search?q=" + urllib.parse.quote("已经"))["results"]
        self.assertEqual(hits[0]["id"], "2:已经")
        w = self.get("/api/words/" + urllib.parse.quote("2:已经"))
        self.assertEqual(w["citation"], "(HSK Level 2, page 47)")
        self.assertTrue(w["sentences"])

    def test_flashcard_round_trip(self):
        q = self.get("/api/review/queue?limit=3")
        word_id = q["cards"][0]["word"]["id"]
        status, body = self.post("/api/review/answer", {"word_id": word_id, "grade": 3})
        self.assertEqual((status, body["status"]), (200, "learning"))
        self.assertEqual(self.post("/api/review/answer", {"word_id": word_id, "grade": 7})[0], 422)

    def test_drill_test_and_progress(self):
        qs = self.get("/api/drill?level=3&count=6&types=cloze,order")["questions"]
        self.assertEqual({q["type"] for q in qs}, {"cloze", "order"})
        self.assertEqual(self.post("/api/drill/answer", {"word_id": qs[0]["word"]["id"], "correct": False})[0], 200)
        test = self.get("/api/test/1")
        self.assertEqual(sum(len(s["questions"]) for s in test["sections"]), 30)
        self.assertEqual(self.post("/api/test/result", {"level": 1, "score": 31, "total": 30})[0], 400)
        self.assertEqual(self.post("/api/test/result", {"level": 1, "score": 20, "total": 30})[0], 200)
        stats = self.get("/api/progress")
        self.assertEqual(stats["tests"][0]["score"], 20)

    def test_settings_and_reset_guard(self):
        self.assertEqual(self.post("/api/settings", {"target_level": 3})[1]["target_level"], 3)
        self.assertEqual(self.post("/api/settings", {"target_level": 4})[0], 422)
        self.assertEqual(self.post("/api/progress/reset", {})[0], 422)
        self.assertEqual(self.post("/api/progress/reset", {"confirm": "RESET"})[0], 200)

    def test_textbook_page(self):
        p = self.get("/api/page/2/47")
        self.assertEqual((p["printed_page"], p["lesson"]["number"]), (27, 4))
        self.assertIn("已经", p["transcript"])
        self.assert_get_fails("/api/page/4/1", 404)

    def test_chat_stream(self):
        body = json.dumps({"message": "Teach me HSK 2 lesson 4", "provider": self.provider,
                           "focus": {"type": "lesson", "level": 2, "lesson": 4}}).encode()
        req = urllib.request.Request(self.url("/chat/stream"), data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        events = []
        with urllib.request.urlopen(req) as r:
            self.assertEqual(r.headers["content-type"].split(";")[0], "text/event-stream")
            for raw in r:
                line = raw.decode("utf-8").strip()
                if line.startswith("data:"):
                    events.append(json.loads(line[5:]))
        self.assertEqual([e["event"] for e in events], ["meta", "delta", "done"])
        done = events[-1]
        self.assertTrue(any(c["found"] and c["citation"] == "(HSK Level 2, page 46)" for c in done["checks"]))
        history = self.get("/chat/sessions/" + done["session_id"])
        self.assertEqual(history["topic"], events[0]["topic"])

    def test_chat_validation(self):
        self.assertEqual(self.post("/chat", {"message": "  "})[0], 400)
        self.assertEqual(self.post("/chat", {"message": "hi", "focus": {"type": "nonsense"}})[0], 422)

    def test_app_shell(self):
        with urllib.request.urlopen(self.url("/")) as r:
            self.assertIn(b'/static/js/app.js', r.read())
        with urllib.request.urlopen(self.url("/static/js/app.js")) as r:
            self.assertEqual(r.status, 200)


if __name__ == "__main__":
    unittest.main()

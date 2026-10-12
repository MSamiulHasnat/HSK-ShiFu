"""The tutor pipeline (topic pinning, grounding, fact checks, streaming) with a scripted model."""

import unittest

from agent import tutor, verify
from tests.helpers import ScriptedProvider, install_provider, use_temp_databases


class Topics(unittest.TestCase):
    def setUp(self):
        use_temp_databases()
        tutor.SESSIONS.clear()
        self.model = ScriptedProvider(["我每天六点起床。(Wǒ měi tiān liù diǎn qǐ chuáng.) (HSK Level 2, page 30) Your turn!"])
        self.name = install_provider(self.model)

    def system(self):
        return self.model.requests[-1][0]

    def test_lesson_focus_pins_pages_and_word_list(self):
        r = tutor.turn(None, "Teach me this lesson", provider_name=self.name, focus={"type": "lesson", "level": 2, "lesson": 2})
        self.assertTrue(r["topic"].startswith("HSK 2 · Lesson 2 ·"))
        self.assertIn("(HSK Level 2, page 30)", r["sources"])
        self.assertIn("- 起床 (qǐ chuáng) v. to get up, to get out of bed — HSK Level 2, Lesson 2", self.system())
        self.assertNotIn("⚠️", r["reply"])  # the cited example really is on p30

    def test_lesson_reference_in_text(self):
        r = tutor.turn(None, "Let's do HSK 3 lesson 11", provider_name=self.name)
        self.assertTrue(r["topic"].startswith("HSK 3 · Lesson 11 ·"))

    def test_word_focus_includes_exact_entry(self):
        tutor.turn(None, "Teach me this word", provider_name=self.name, focus={"type": "word", "id": "2:已经"})
        self.assertIn("已经 (yǐjīng) adv. already — HSK Level 2, Lesson 4 (HSK Level 2, page 47)", self.system())

    def test_practice_answer_does_not_switch_topic(self):
        r1 = tutor.turn(None, "Teach me HSK 2 lesson 2", provider_name=self.name)
        r2 = tutor.turn(r1["session_id"], "我每天七点起床", provider_name=self.name)
        self.assertFalse(r2["topic_changed"])
        self.assertEqual(r2["topic"], r1["topic"])

    def test_system_prompt_is_stable_within_a_topic(self):
        r1 = tutor.turn(None, "Teach me HSK 2 lesson 2", provider_name=self.name)
        first = self.system()
        tutor.turn(r1["session_id"], "我每天七点起床", provider_name=self.name)
        self.assertEqual(first, self.system())  # cacheable prefix

    def test_target_level_reaches_the_prompt(self):
        from agent import progress
        progress.update_settings({"target_level": 3})
        tutor.turn(None, "Teach me HSK 2 lesson 2", provider_name=self.name)
        self.assertIn("preparing for the HSK 3 exam", self.system())


class FactChecks(unittest.TestCase):
    def test_wrong_page_is_flagged(self):
        out = tutor._format_reply("我每天六点起床。(Wǒ měi tiān liù diǎn qǐ chuáng.) (HSK Level 1, page 20)",
                                  ["(HSK Level 2, page 30)"])
        self.assertIn("⚠️ Fact check", out)

    def test_example_sentences_are_looked_up_in_the_books(self):
        checks = verify.check_examples("Here: 我已经回家了。(Wǒ yǐjīng huí jiā le.)\n王老师已经回家了。(Wáng lǎoshī yǐjīng huí jiā le.)")
        self.assertEqual([(c["text"], c["found"]) for c in checks], [("我已经回家了。", False), ("王老师已经回家了。", True)])
        self.assertEqual(checks[1]["citation"], "(HSK Level 2, page 49)")

    def test_contradicting_a_correct_answer_is_flagged(self):
        reply = ("That's a good try! However, there's a small mistake.\n"
                 "The correct sentence is: 我把书放在桌子上了。(Wǒ bǎ shū fàng zài zhuōzi shàng le.)")
        out = tutor._format_reply(reply, ["(HSK Level 3, page 109)"], "我把书放在桌子上了。")
        self.assertIn("identical to yours", out)
        fine = "Not quite. The correct sentence is: 我把书放在桌子上了。(Wǒ bǎ shū fàng zài zhuōzi shàng le.)"
        self.assertNotIn("identical", tutor._format_reply(fine, [], "我把书在桌子上放了。"))

    def test_quoting_the_student_is_not_an_example(self):
        self.assertEqual(verify.check_examples("你说：我把书放在桌子上了 (wǒ bǎ shū)", exclude="我把书放在桌子上了"), [])


class Fallback(unittest.TestCase):
    def test_second_provider_answers_only_when_the_first_fails(self):
        from agent.providers import FallbackProvider
        down = ScriptedProvider(fail="llama-server not reachable")
        down.name = "llamacpp"
        backup = ScriptedProvider(["好的"])
        backup.name = "ollama"
        p = FallbackProvider([down, backup])
        self.assertEqual(p.chat("s", [{"role": "user", "content": "hi"}]), "好的")
        self.assertEqual(p.used, "ollama")
        up = ScriptedProvider(["第一"])
        up.name = "llamacpp"
        p = FallbackProvider([up, backup])
        self.assertEqual(p.chat("s", [{"role": "user", "content": "hi"}]), "第一")
        self.assertEqual((p.used, len(backup.requests)), ("llamacpp", 1))  # backup not called again

    def test_all_failing_is_one_clear_error(self):
        from agent.providers import FallbackProvider
        a, b = ScriptedProvider(fail="a down"), ScriptedProvider(fail="b down")
        with self.assertRaisesRegex(RuntimeError, "a down.*b down"):
            FallbackProvider([a, b]).chat("s", [{"role": "user", "content": "hi"}])


class Streaming(unittest.TestCase):
    def setUp(self):
        use_temp_databases()
        tutor.SESSIONS.clear()

    def test_event_sequence(self):
        name = install_provider(ScriptedProvider(["你叫什么名字？(Nǐ jiào shénme míngzi?) Let's begin."]))
        events = list(tutor.turn_stream(None, "Teach me HSK 1 lesson 1", provider_name=name))
        self.assertEqual([e["event"] for e in events], ["meta", "delta", "done"])
        self.assertEqual(events[-1]["checks"][0]["found"], True)
        saved = tutor.get_history_for_display(events[0]["session_id"])
        self.assertEqual(len(saved["history"]), 2)

    def test_model_error_leaves_no_dangling_message(self):
        name = install_provider(ScriptedProvider(fail="model offline"))
        events = list(tutor.turn_stream(None, "Teach me HSK 1 lesson 1", provider_name=name))
        self.assertEqual(events[-1], {"event": "error", "detail": "model offline"})
        self.assertEqual(tutor.SESSIONS[events[0]["session_id"]].history, [])

    def test_missing_provider_is_an_error_event(self):
        events = list(tutor.turn_stream(None, "hi", provider_name="no-such-provider"))
        self.assertEqual(events[0]["event"], "error")


if __name__ == "__main__":
    unittest.main()

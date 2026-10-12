"""Spaced repetition, the learning record, and the question generator."""

import random
import re
import unittest

from agent import course, progress, quiz, srs
from agent.course_text import hanzi_forms, pages
from tests.helpers import use_temp_databases

NOW = 1_800_000_000.0


class Scheduler(unittest.TestCase):
    def test_new_card_learning_steps_then_graduates(self):
        c = srs.schedule(srs.Card(), srs.GOOD, NOW)
        self.assertEqual((c.state, c.step, c.due - NOW), ("learning", 1, 600))
        c = srs.schedule(c, srs.GOOD, NOW)
        self.assertEqual((c.state, c.interval), ("review", 1.0))
        self.assertEqual(srs.status(c), "young")

    def test_easy_graduates_immediately(self):
        c = srs.schedule(srs.Card(), srs.EASY, NOW)
        self.assertEqual((c.state, c.interval), ("review", srs.EASY_INTERVAL))

    def test_intervals_grow_and_lapses_relearn(self):
        c = srs.Card(state="review", interval=10, ease=2.5, due=NOW)
        good = srs.schedule(c, srs.GOOD, NOW)
        self.assertAlmostEqual(good.interval, 25)
        lapse = srs.schedule(c, srs.AGAIN, NOW)
        self.assertEqual((lapse.state, lapse.lapses, lapse.interval), ("relearning", 1, 5))
        self.assertLess(lapse.ease, c.ease)
        back = srs.schedule(lapse, srs.GOOD, NOW)
        self.assertEqual((back.state, back.interval), ("review", 5))

    def test_preview_is_ordered(self):
        p = srs.preview(srs.Card(state="review", interval=4, due=NOW), NOW)
        self.assertLess(p[1], p[2])
        self.assertLess(p[2], p[3])
        self.assertLess(p[3], p[4])

    def test_bad_grade(self):
        with self.assertRaises(ValueError):
            srs.schedule(srs.Card(), 5, NOW)

    def test_drill_answers_never_count_as_early_reviews(self):
        not_due = srs.Card(state="review", interval=10, due=NOW + 86400)
        self.assertIsNone(srs.quiz_grade(not_due, True, NOW))
        self.assertEqual(srs.quiz_grade(not_due, False, NOW), srs.AGAIN)
        self.assertEqual(srs.quiz_grade(None, True, NOW), srs.GOOD)


class LearningRecord(unittest.TestCase):
    def setUp(self):
        use_temp_databases()

    def test_queue_respects_the_daily_new_limit(self):
        progress.update_settings({"daily_new": 5, "target_level": 1})
        q = progress.review_queue(limit=50, now=NOW)
        self.assertEqual(len(q["words"]), 5)
        self.assertEqual(q["words"][0].id, "1:你")  # textbook order
        for w in q["words"]:
            progress.answer_card(w.id, srs.GOOD, now=NOW)
        self.assertEqual(progress.review_queue(limit=50, now=NOW + 1)["counts"]["new"], 0)

    def test_lesson_queue_is_not_capped(self):
        progress.update_settings({"daily_new": 1})
        q = progress.review_queue(limit=50, level=2, lesson=4, now=NOW)
        self.assertEqual(len(q["words"]), len(course.load().lesson(2, 4).word_ids))

    def test_learning_card_comes_back_when_due(self):
        progress.answer_card("1:你", srs.AGAIN, now=NOW)
        q = progress.review_queue(limit=50, now=NOW + 120)
        self.assertEqual(q["words"][0].id, "1:你")

    def test_stats_and_weak_words(self):
        for _ in range(3):
            progress.record_drill("1:岁", False, "drill", now=NOW)
        progress.record_drill("1:你", True, "drill", now=NOW)
        s = progress.stats(now=NOW)
        self.assertEqual(s["answers_today"], 4)
        self.assertEqual(s["weak_words"][0]["hanzi"], "岁")
        self.assertEqual(s["streak"], 1)
        self.assertEqual(s["accuracy_7d"], 0.25)

    def test_unknown_word_rejected(self):
        with self.assertRaises(KeyError):
            progress.answer_card("9:不存在", 3)

    def test_introduce_and_reset(self):
        progress.introduce("3:伞", now=NOW)
        self.assertEqual(progress.word_status(["3:伞"])["3:伞"], "learning")
        progress.reset_all()
        self.assertEqual(progress.word_status(["3:伞"])["3:伞"], "new")


class Questions(unittest.TestCase):
    def check(self, q):
        w = course.load().words[q["word"]["id"]]
        if q["type"] == "order":
            self.assertEqual("".join(q["answer_tiles"]) + q["ending"], q["sentence"]["text"])
            self.assertEqual(sorted(q["tiles"]), sorted(q["answer_tiles"]))
            return
        labels = [o["label"] for o in q["options"]]
        self.assertEqual(len(set(labels)), 4, labels)
        answer = labels[q["answer"]]
        expected = {"meaning": w.meaning, "hanzi": w.hanzi, "pinyin": w.pinyin,
                    "listen": w.hanzi, "cloze": hanzi_forms(w.hanzi)[0]}[q["type"]]
        self.assertEqual(answer, expected)
        if q["type"] == "cloze":
            s = q["sentence"]
            self.assertEqual(q["prompt"]["before"] + answer + q["prompt"]["after"], s["text"])
            body = re.sub(r"[^一-鿿]", "", pages(s["level"])[s["page"]])
            self.assertIn(re.sub(r"[^一-鿿]", "", s["text"]), body)

    def test_every_type_at_every_level(self):
        for level in course.LEVELS:
            qs = quiz.drill(level, types=list(quiz.TYPES), count=30, seed=level)
            self.assertGreaterEqual(len(qs), 25)
            self.assertEqual({q["type"] for q in qs}, set(quiz.TYPES))
            for q in qs:
                self.check(q)

    def test_distractors_cannot_also_be_right(self):
        rng = random.Random(1)
        for w in course.load().words_for(level=1):
            q = quiz.meaning_question(w, rng)
            if q:
                for i, o in enumerate(q["options"]):
                    if i != q["answer"]:
                        self.assertFalse(quiz._meaning_tokens(o["label"]) & quiz._meaning_tokens(w.meaning), (w.hanzi, o))

    def test_practice_test_shape(self):
        for level in course.LEVELS:
            t = quiz.practice_test(level, seed=7)
            sizes = [len(s["questions"]) for s in t["sections"]]
            self.assertEqual(sum(sizes), 30, sizes)
            ids = [q["word"]["id"] for s in t["sections"] for q in s["questions"]]
            self.assertEqual(len(ids), len(set(ids)))  # no word asked twice


if __name__ == "__main__":
    unittest.main()

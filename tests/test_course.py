"""The textbook parser, checked against facts printed in the books."""

import unittest

from agent import course, lexicon
from agent.course_text import hanzi_forms, pages, pinyin_syllables, strip_tones


class CourseStructure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = course.load()

    def test_lesson_counts(self):
        self.assertEqual([len(self.c.lessons_for(l)) for l in course.LEVELS], [15, 15, 20])

    def test_syllabus_word_counts_match_the_vocabulary_index(self):
        counts = [len(self.c.words_for(level=l)) for l in course.LEVELS]
        self.assertEqual(counts, [148, 147, 301])

    def test_every_word_has_a_lesson_and_a_page_inside_it(self):
        for w in self.c.words.values():
            lesson = self.c.lesson(w.level, w.lesson)
            self.assertIsNotNone(lesson, w.id)
            self.assertTrue(lesson.start_page <= w.page <= lesson.end_page, f"{w.id} p{w.page} outside {lesson.key}")

    def test_lesson_ranges_are_contiguous(self):
        for level in course.LEVELS:
            lessons = self.c.lessons_for(level)
            for a, b in zip(lessons, lessons[1:]):
                self.assertEqual(a.end_page + 1, b.start_page)

    def test_known_entries(self):
        w = self.c.words["2:已经"]
        self.assertEqual((w.pinyin, w.pos, w.meaning, w.lesson, w.page), ("yǐjīng", "adv.", "already", 4, 47))
        self.assertIn("已经", pages(2)[47])  # the page really lists it
        self.assertEqual(self.c.words["3:秘书"].kind, "extra")
        self.assertEqual(self.c.words["3:秘书"].hsk_level, 5)

    def test_titles(self):
        self.assertEqual(self.c.lesson(2, 14).title_zh, "你看过那个电影吗")
        self.assertEqual(self.c.lesson(2, 12).title_zh, "你穿得太少了")
        self.assertEqual(self.c.lesson(3, 13).title_pinyin, "Wǒ shì zǒu huilai de")

    def test_grammar_points(self):
        titles = [g.title for g in self.c.lesson(3, 11).grammar]
        self.assertTrue(any("把" in t for t in titles), titles)
        self.assertEqual(self.c.lesson(3, 11).grammar[0].page, 109)
        self.assertEqual(sum(len(l.grammar) for l in self.c.lessons.values()), 136)


class Sentences(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = course.load()

    def test_sentences_are_verbatim_from_their_page(self):
        import re
        for s in self.c.sentences:
            body = re.sub(r"[^一-鿿]", "", pages(s.level)[s.page])
            self.assertIn(re.sub(r"[^一-鿿]", "", s.text), body, s.citation)

    def test_two_line_turn_gets_no_translation(self):
        # HSK 2 p63: speaker B's turn spans two lines; its English covers both, so neither gets it.
        s = next(s for s in self.c.sentences if s.text.startswith("因为昨天下雨"))
        self.assertIsNone(s.english)
        s = next(s for s in self.c.sentences if s.text.startswith("你经常游泳"))
        self.assertEqual(s.english, "Do you often swim?")

    def test_mismatched_pinyin_is_dropped(self):
        s = next(s for s in self.c.sentences if s.text == "现在小丽要做什么？")
        self.assertIsNone(s.pinyin)

    def test_exercise_instructions_are_not_sentences(self):
        self.assertFalse(any("一组" in s.text for s in self.c.sentences))


class TextHelpers(unittest.TestCase):
    def test_strip_tones(self):
        self.assertEqual(strip_tones("Nǐ hǎo"), "nihao")
        self.assertEqual(strip_tones("nǚ'ér"), "nver")

    def test_hanzi_forms(self):
        self.assertEqual(hanzi_forms("秋（天）"), ["秋天", "秋"])
        self.assertEqual(hanzi_forms("打篮球"), ["打篮球"])

    def test_pinyin_syllables(self):
        self.assertEqual(pinyin_syllables("Bēizi zài nǎr?"), 4)
        self.assertIsNone(pinyin_syllables("example:"))


class Lexicon(unittest.TestCase):
    def test_search_by_each_script(self):
        self.assertEqual(lexicon.search("已经")[0].id, "2:已经")
        self.assertEqual(lexicon.search("yi jing")[0].id, "2:已经")
        self.assertEqual(lexicon.search("umbrella")[0].hanzi, "伞")

    def test_segment(self):
        chunks = [c for c, _ in lexicon.segment("我把书放在桌子上了。")]
        self.assertEqual(chunks, ["我", "把", "书", "放", "在", "桌子", "上", "了", "。"])

    def test_lesson_references(self):
        self.assertEqual(lexicon.find_lesson_reference("Teach me HSK 2 lesson 5"), (2, 5))
        self.assertEqual(lexicon.find_lesson_reference("lesson 4 of HSK 1"), (1, 4))
        self.assertIsNone(lexicon.find_lesson_reference("HSK 1 lesson 30"))
        self.assertIsNone(lexicon.find_lesson_reference("teach me 了"))


if __name__ == "__main__":
    unittest.main()

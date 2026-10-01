import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent_board as ab


class TopicTests(unittest.TestCase):
    def load(self, raw):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "topics.json"
            f.write_text(raw if isinstance(raw, str) else json.dumps(raw))
            with mock.patch.object(ab, "TOPICS_FILE", f), mock.patch.object(ab, "_topics_cache", (None, [], [])):
                return ab.load_topics()

    def test_most_hits_wins_and_first_topic_wins_a_tie(self):
        topics, folders = self.load({"topics": [{"label": "A", "match_any": ["kb", "router"]},
                                                {"label": "B", "match_any": ["codex", "kb router"]}]})
        self.assertEqual(ab.topic_for("KB router from Codex", None, topics, folders), "A")
        self.assertEqual(ab.topic_for("Codex only", None, topics, folders), "B")
        self.assertIsNone(ab.topic_for("Nothing here", None, topics, folders))

    def test_keywords_match_whole_words(self):
        topics, folders = self.load({"topics": [{"label": "Ops", "match_any": ["uat", "pl"]}]})
        self.assertIsNone(ab.topic_for("Evaluate the plan", None, topics, folders))
        self.assertEqual(ab.topic_for("Resume PL point 1", None, topics, folders), "Ops")

    def test_empty_keywords_use_the_label_and_folder_is_the_fallback(self):
        topics, folders = self.load({"topics": [{"label": "Tooling", "match_any": []}, {"label": "Billing"}],
                                     "folders": [{"match": "billing-service", "label": "Billing"}]})
        self.assertEqual(ab.topic_for("New tooling idea", "/x/billing-service", topics, folders), "Tooling")
        self.assertEqual(ab.topic_for("Untitled", "/x/billing-service", topics, folders), "Billing")

    def test_missing_or_broken_file_means_no_topics(self):
        self.assertEqual(self.load("not json"), ([], []))
        with mock.patch.object(ab, "TOPICS_FILE", Path("/nonexistent/topics.json")):
            self.assertEqual(ab.load_topics(), ([], []))

    def test_hand_picked_group_is_saved_per_scope_and_cleared(self):
        sid = "12345678-1234-1234-1234-123456789abc"
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "topic_choices.json"
            with mock.patch.object(ab, "DATA_DIR", Path(d)), mock.patch.object(ab, "TOPIC_CHOICES_FILE", f):
                self.assertEqual(ab.load_topic_choices(), {"session": {}, "workstream": {}})
                ab.save_topic_choice(sid, "session", "  AI Tools  &  Automation ")
                ab.save_topic_choice(sid, "workstream", "Parcel Library")
                self.assertEqual(ab.load_topic_choices(), {"session": {sid: "AI Tools & Automation"},
                                                           "workstream": {sid: "Parcel Library"}})
                ab.save_topic_choice(sid, "session", "")
                self.assertEqual(ab.load_topic_choices()["session"], {})
                for bad in (("not-an-id", "session", "A"), (sid, "everything", "A"), (sid, "session", "x" * 81)):
                    with self.assertRaises(ValueError):
                        ab.save_topic_choice(*bad)
                f.write_text("not json")
                self.assertEqual(ab.load_topic_choices(), {"session": {}, "workstream": {}})


if __name__ == "__main__":
    unittest.main()

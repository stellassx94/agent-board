import json
import os
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import agent_board as board


def line(value):
    return json.dumps(value, separators=(',', ':')).encode() + b'\n'


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'session.jsonl'
        board._cache.clear()
        board._claude_metadata_cache.clear()
        board._codex_prompt_cache.clear()
        board.cached_sidecar_json.cache_clear()
        board.cached_topic_for.cache_clear()

    def test_claude_metadata_survives_tail_window_and_appends(self):
        user = {'type': 'user', 'cwd': '/tmp/project', 'entrypoint': 'claude-vscode',
                'message': {'content': 'Original request'}}
        title = {'type': 'ai-title', 'aiTitle': 'Keep this title'}
        self.path.write_bytes(line(user) + line(title) + line({'type': 'cost-state', 'padding': 'x' * 4096}))
        first = board.claude_metadata(self.path, self.path.stat())
        self.assertEqual(first['title'], 'Keep this title')
        self.assertEqual(first['prompt'], 'Original request')
        with self.path.open('ab') as handle:
            handle.write(line({'type': 'ai-title', 'aiTitle': 'New title'}))
        with mock.patch.object(board, 'first_claude_prompt', side_effect=AssertionError('rescanned opening prompt')):
            second = board.claude_metadata(self.path, self.path.stat())
        self.assertEqual(second['title'], 'New title')
        self.assertEqual(second['cwd'], '/tmp/project')
        self.assertEqual(second['offset'], self.path.stat().st_size)

    def test_rewritten_transcript_invalidates_metadata(self):
        self.path.write_bytes(line({'type': 'user', 'message': {'content': 'Old request'}}))
        board.claude_metadata(self.path, self.path.stat())
        self.path.write_bytes(line({'type': 'user', 'message': {'content': 'New request'}}))
        current = self.path.stat()
        os.utime(self.path, ns=(current.st_atime_ns, current.st_mtime_ns + 1000000))
        result = board.claude_metadata(self.path, self.path.stat())
        self.assertEqual(result['prompt'], 'New request')

    def test_partial_append_is_retried(self):
        self.path.write_bytes(b'{"type":"ai-title","aiTitle":"New')
        board.claude_metadata(self.path, self.path.stat())
        with self.path.open('ab') as handle:
            handle.write(b' title"}\n')
        result = board.claude_metadata(self.path, self.path.stat())
        self.assertEqual(result['title'], 'New title')

    def test_complete_metadata_without_trailing_newline_is_read(self):
        self.path.write_bytes(line({'type': 'ai-title', 'aiTitle': 'Final title'}).rstrip(b'\n'))
        result = board.claude_metadata(self.path, self.path.stat())
        self.assertEqual(result['title'], 'Final title')

    def test_session_cache_does_not_grow_without_limit(self):
        with mock.patch.object(board, 'MAX_SESSION_CACHE', 2):
            for i in range(3):
                board.remember_session(i, i, {'title': str(i)})
        self.assertEqual(set(board._cache), {1, 2})

    def test_simultaneous_refreshes_do_not_build_in_parallel(self):
        active = 0
        peak = 0
        def build(hours):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            time.sleep(0.01)
            active -= 1
            return {}
        with mock.patch.object(board, '_build_status', side_effect=build):
            threads = [threading.Thread(target=board.status, args=(168,)) for _ in range(5)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(peak, 1)

    def test_tail_read_is_bounded_and_discards_partial_record(self):
        self.path.write_bytes(b'x' * 4096 + b'\n' + line({'type': 'assistant', 'answer': 'Done'}))
        with mock.patch.object(board, 'TAIL_BYTES', 128):
            result = board.transcript_tail(self.path, self.path.stat().st_size)
        self.assertEqual(json.loads(result[0])['answer'], 'Done')
        self.assertLessEqual(sum(map(len, result)), 128)

    def test_codex_opening_prompt_is_retained_when_tail_moves(self):
        self.path.write_bytes(line({'type': 'event_msg', 'payload': {'type': 'user_message', 'message': 'Actual request'}})
                              + line({'type': 'event_msg', 'payload': {'type': 'padding', 'text': 'x' * 4096}}))
        self.assertEqual(board.codex_opening_prompt(self.path, self.path.stat()), 'Actual request')
        with self.path.open('ab') as handle:
            handle.write(line({'type': 'event_msg', 'payload': {'type': 'task_complete'}}))
        with mock.patch.object(board, 'codex_first_user_message', side_effect=AssertionError('rescanned prompt')):
            self.assertEqual(board.codex_opening_prompt(self.path, self.path.stat()), 'Actual request')

    def test_sidecar_cache_keeps_only_metadata_and_observes_renames(self):
        self.path.write_text(json.dumps({'cliSessionId': 'a', 'title': 'First', 'messages': ['private content']}))
        self.assertEqual(board.sidecar_json(self.path)['title'], 'First')
        self.assertNotIn('messages', board.sidecar_json(self.path))
        self.assertEqual(board.cached_sidecar_json.cache_info().hits, 1)
        self.path.write_text(json.dumps({'cliSessionId': 'a', 'title': 'Second title'}))
        self.assertEqual(board.sidecar_json(self.path)['title'], 'Second title')
        self.path.write_text('[]')
        self.assertEqual(board.sidecar_json(self.path), {})

    def test_topic_cache_observes_rule_changes(self):
        rules = [('First', [re.compile('parcel')])]
        self.assertEqual(board.topic_for('parcel', None, rules, []), 'First')
        self.assertEqual(board.topic_for('parcel', None, rules, []), 'First')
        self.assertEqual(board.cached_topic_for.cache_info().hits, 1)
        self.assertEqual(board.topic_for('parcel', None, [('Second', [re.compile('parcel')])], []), 'Second')

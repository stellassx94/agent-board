import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agent_board as board
import agent_board_workstreams as ws

ONE = '00000000-0000-4000-8000-000000000001'
TWO = '00000000-0000-4000-8000-000000000002'
THREE = '00000000-0000-4000-8000-000000000003'


class BulkCompleteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(ws, 'DATA_FILE', Path(self.tmp.name) / 'lineage.json')
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def post(self, ids, buckets):
        payload = json.dumps({'ids': ids}).encode()
        handler = board.Handler.__new__(board.Handler)
        handler.path = '/api/bulk-complete'
        handler.headers = {'Content-Length': str(len(payload))}
        handler.rfile = io.BytesIO(payload)
        handler.local_request = lambda: True
        handler.send_response = mock.Mock()
        handler.send_error = mock.Mock()
        handler.end_headers = mock.Mock()
        with mock.patch.object(board, 'status', return_value={'workstreams': buckets}), \
             mock.patch.object(board, 'invalidate_status'):
            handler.do_POST()
        return handler

    def test_selected_waiting_and_check_complete_and_can_be_undone(self):
        h = self.post([ONE, TWO], [{'id': ONE, 'bucket': 'yourturn'}, {'id': TWO, 'bucket': 'check'}])
        h.send_response.assert_called_once_with(204)
        self.assertEqual(set(ws.load()['completed']), {ONE, TWO})
        ws.complete(ONE, False)
        self.assertEqual(set(ws.load()['completed']), {TWO})

    def test_changed_or_active_selection_rejects_entire_batch(self):
        h = self.post([ONE, TWO], [{'id': ONE, 'bucket': 'yourturn'}, {'id': TWO, 'bucket': 'active'}])
        h.send_error.assert_called_once_with(400)
        self.assertEqual(ws.load()['completed'], {})

    def test_invalid_duplicate_or_missing_selection_is_rejected(self):
        for ids in ([ONE, ONE], [ONE, 'bad'], [], [THREE]):
            with self.subTest(ids=ids):
                h = self.post(ids, [{'id': ONE, 'bucket': 'yourturn'}])
                h.send_error.assert_called_once_with(400)
                self.assertEqual(ws.load()['completed'], {})

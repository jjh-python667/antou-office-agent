"""UX-facing API contracts: selected materials and recent file metadata."""
import json
import os
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch

import app
from office_tools import OfficeTools


class UXTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = app.OFFICE
        app.OFFICE = OfficeTools(self.temp.name)
        app.OFFICE.resolve('inputs/material.txt').write_text('meeting data', encoding='utf-8')
        self.server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        app.OFFICE = self.previous
        self.temp.cleanup()

    def chat(self, **extra):
        body = {'provider': 'custom', 'base_url': 'http://127.0.0.1:11434/v1', 'model': 'test-model', 'mode': 'agent', 'text': 'summarize', **extra}
        req = urllib.request.Request('http://127.0.0.1:%d/api/chat' % self.server.server_port,
            data=json.dumps(body).encode(), headers={'Content-Type': 'application/json', 'X-Office-Token': app.TOKEN})
        with urllib.request.urlopen(req) as response:
            return [json.loads(line) for line in response.read().decode().splitlines()]

    def test_selected_materials_reach_model(self):
        received = []
        def complete(messages, settings, tools=None):
            received.append(messages[-1]['content'])
            return {'role': 'assistant', 'content': 'done'}
        with patch('app.completion', side_effect=complete):
            events = self.chat(attachments=['inputs/material.txt'])
        self.assertEqual(events[-1]['type'], 'done')
        self.assertIn('inputs/material.txt', received[0])

    def test_role_mode_cannot_claim_to_read_attachments(self):
        with patch('app.completion') as complete:
            events = self.chat(mode='role', attachments=['inputs/material.txt'])
        self.assertIn('执行 Agent', events[-1]['text'])
        complete.assert_not_called()

    def test_invalid_materials_are_rejected_before_model_call(self):
        for attachments in (['inputs/missing.txt'], ['../../outside.txt'], ['inputs/material.txt'] * 11, 'not-a-list'):
            with patch('app.completion') as complete:
                events = self.chat(attachments=attachments)
                self.assertEqual(events[-1]['type'], 'error')
                complete.assert_not_called()

    def test_recent_files_and_metadata(self):
        a = app.OFFICE.resolve('inputs/material.txt')
        b = app.OFFICE.resolve('inputs/recent.txt'); b.write_text('new', encoding='utf-8')
        os.utime(a, (100, 100)); os.utime(b, (200, 200))
        files = app.OFFICE.list_files()
        self.assertEqual(files[0]['path'], 'inputs/recent.txt')
        self.assertEqual(files[0]['modified_at'], 200)


if __name__ == '__main__':
    unittest.main()

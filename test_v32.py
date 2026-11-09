"""P1 regression tests. All upstreams are local fixtures; no real provider keys."""
import copy
import json
import tempfile
import threading
import time
import unittest
import urllib.request
import os
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import app
import providers
from context_budget import estimate_tokens, fit_context
from local_state import LocalState
from office_tools import OfficeTools


def upstream(frames, gate=None, requests=None, json_response=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if requests is not None:
                requests.append(body)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json' if json_response else 'text/event-stream')
            self.end_headers()
            try:
                if json_response:
                    self.wfile.write(json.dumps(json_response).encode()); return
                for index, data in enumerate(frames):
                    wire = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
                    self.wfile.write(('data: ' + wire + '\n\n').encode()); self.wfile.flush()
                    if index == 0 and gate:
                        gate.wait(8)
            except OSError:
                pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def chunk(content=None, finish=None, **delta):
    if content is not None:
        delta['content'] = content
    return {'choices': [{'delta': delta, 'finish_reason': finish}]}


def settings(server, **extra):
    return providers.config({'provider': 'custom', 'base_url': 'http://127.0.0.1:%d/v1' % server.server_port,
        'model': 'local-chat', **extra})


class StreamingTests(unittest.TestCase):
    def test_content_arrives_before_generation_finishes(self):
        gate, first, finished = threading.Event(), threading.Event(), threading.Event()
        server = upstream([chunk('你好'), chunk('世界', finish='stop'), '[DONE]'], gate=gate)
        pieces, result = [], []
        def worker():
            result.append(providers.stream_completion([], settings(server), on_delta=lambda text: (pieces.append(text), first.set())))
            finished.set()
        thread = threading.Thread(target=worker)
        try:
            thread.start(); self.assertTrue(first.wait(3)); self.assertFalse(finished.is_set())
            gate.set(); thread.join(3)
            self.assertEqual(pieces, ['你好', '世界']); self.assertEqual(result[0]['content'], '你好世界')
        finally:
            gate.set(); thread.join(3); server.shutdown(); server.server_close()

    def test_fragmented_tool_calls_and_reasoning_are_reassembled(self):
        frames = [chunk(reasoning_content='private reasoning'),
            chunk(tool_calls=[{'index': 0, 'id': 'c1', 'function': {'name': 'read_', 'arguments': '{"path":'}}]),
            chunk(tool_calls=[{'index': 0, 'function': {'name': 'file', 'arguments': '"inputs/a.txt"}'}}]),
            chunk(finish='tool_calls'), '[DONE]']
        server = upstream(frames); visible = []
        try:
            value = providers.stream_completion([], settings(server), app.TOOLS, visible.append)
            self.assertEqual(value['tool_calls'][0]['function'], {'name': 'read_file', 'arguments': '{"path":"inputs/a.txt"}'})
            self.assertEqual(value['reasoning_content'], 'private reasoning'); self.assertEqual(visible, [])
        finally:
            server.shutdown(); server.server_close()

    def test_early_end_is_not_accepted_as_success(self):
        server = upstream([chunk('partial')])
        try:
            with self.assertRaisesRegex(RuntimeError, '提前中断'):
                providers.stream_completion([], settings(server))
        finally:
            server.shutdown(); server.server_close()

    def test_length_limit_keeps_run_incomplete(self):
        server = upstream([chunk('partial'), chunk(finish='length'), '[DONE]'])
        try:
            with self.assertRaisesRegex(RuntimeError, '上限'):
                providers.stream_completion([], settings(server))
        finally:
            server.shutdown(); server.server_close()

    def test_json_fallback_for_compatible_gateway(self):
        server = upstream([], json_response={'choices': [{'message': {'role': 'assistant', 'content': 'fallback'}, 'finish_reason': 'stop'}]})
        try:
            self.assertEqual(providers.stream_completion([], settings(server))['content'], 'fallback')
        finally:
            server.shutdown(); server.server_close()

    def test_qwen_and_deepseek_thinking_parameters(self):
        for provider in ('qwen', 'deepseek', 'openai', 'kimi', 'siliconflow', 'ollama', 'custom'):
            config = providers.config({'provider': provider, 'base_url': 'https://fixture.example/v1', 'api_key': 'test-key', 'model': 'fixture', 'thinking': True, 'max_output_tokens': 900})
            body = providers.build_payload([], config, stream=True)
            self.assertTrue(body['stream'])
            self.assertEqual('enable_thinking' in body, provider == 'qwen')
            self.assertEqual('thinking' in body, provider == 'deepseek')
            self.assertEqual(body.get('max_completion_tokens', body.get('max_tokens')), 900)
        config['provider'] = 'qwen'; config['thinking'] = False
        self.assertFalse(providers.build_payload([], config)['enable_thinking'])

    def test_invalid_generation_limits_are_rejected(self):
        for extra in ({'thinking': 'yes'}, {'max_output_tokens': 0}, {'max_output_tokens': True}, {'context_window': 100}, {'context_window': 4096, 'max_output_tokens': 6000}):
            with self.assertRaises(ValueError):
                providers.config({'provider': 'custom', 'base_url': 'http://localhost:1/v1', **extra})

    def test_streaming_upstream_error_keeps_v31_key_redaction(self):
        class Failure(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(400); self.end_headers()
                self.wfile.write(json.dumps({'error': {'message': 'context length exceeded; key sk-do-not-leak-123'}}).encode())
        server = ThreadingHTTPServer(('127.0.0.1', 0), Failure)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with self.assertRaisesRegex(RuntimeError, '上下文长度') as caught:
                providers.stream_completion([], settings(server, api_key='sk-do-not-leak-123'))
            self.assertNotIn('sk-do-not-leak-123', str(caught.exception))
        finally:
            server.shutdown(); server.server_close()


class ContextTests(unittest.TestCase):
    def test_only_old_complete_turns_are_removed(self):
        system = {'role': 'system', 'content': 'policy'}
        current = [{'role': 'user', 'content': 'latest'}, {'role': 'assistant', 'tool_calls': [{'id': 'c', 'function': {'name': 'f'}}]}, {'role': 'tool', 'tool_call_id': 'c', 'content': 'result'}]
        messages = [system, {'role': 'user', 'content': 'old' * 1000}, {'role': 'assistant', 'content': 'old answer'}] + copy.deepcopy(current)
        budget = estimate_tokens([system] + current) + 256 + 512 + 20
        result = fit_context(messages, {'context_window': budget, 'max_output_tokens': 256})
        self.assertEqual(result['dropped_turns'], 1); self.assertEqual(messages, [system] + current)

    def test_current_task_is_never_silently_truncated(self):
        messages = [{'role': 'system', 'content': 'policy'}, {'role': 'user', 'content': '当前任务' * 2000}]
        before = copy.deepcopy(messages)
        with self.assertRaisesRegex(ValueError, '最新任务未被裁剪'):
            fit_context(messages, {'context_window': 4096, 'max_output_tokens': 1000})
        self.assertEqual(messages, before)

    def test_tool_schema_cost_is_included(self):
        messages = [{'role': 'user', 'content': 'hi'}]
        with self.assertRaises(ValueError):
            fit_context(messages, {'context_window': 4096, 'max_output_tokens': 256}, [{'description': '工具' * 2000}])


class PersistenceTests(unittest.TestCase):
    def test_successful_session_survives_new_store_instance(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'state.sqlite3'; store = LocalState(file)
            session = {'mode': 'role', 'custom': '', 'messages': [{'role': 'user', 'content': 'hi'}], 'connection': ('custom', 'http://localhost/v1', 'm'), 'transcript': [{'role': 'user', 'content': 'hi'}], 'settings': {'provider': 'custom', 'api_key': 'DO_NOT_SAVE', 'model': 'm'}}
            task = {'id': 'task', 'started': time.time(), 'status': 'completed', 'title': 'hello', 'api_key': 'DO_NOT_SAVE'}
            store.save_success('sid', session, task)
            again = LocalState(file); self.assertEqual(again.get_session('sid')['connection'], session['connection'])
            self.assertNotIn('DO_NOT_SAVE', file.read_bytes().decode('utf-8', 'ignore'))
            self.assertNotIn('api_key', json.dumps(again.get_task('task')))

    def test_unfinished_task_is_marked_interrupted_on_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'state.sqlite3'; store = LocalState(file)
            store.save_task({'id': 'pending', 'started': time.time(), 'status': 'running', 'title': 'pending'})
            self.assertEqual(LocalState(file).get_task('pending')['status'], 'interrupted')

    def test_history_pagination_and_cancelled_record(self):
        with tempfile.TemporaryDirectory() as folder:
            store = LocalState(Path(folder) / 'state.sqlite3')
            for i in range(3):
                store.save_task({'id': str(i), 'started': i + 1, 'title': str(i), 'status': 'cancelled', 'partial_answer': 'not committed'})
            first = store.list_tasks(2); self.assertEqual([x['id'] for x in first['items']], ['2', '1']); self.assertEqual(first['next_offset'], 2)
            self.assertEqual(store.list_tasks(2, 2)['items'][0]['id'], '0')

    def test_session_survives_actual_application_process_restart(self):
        requests = []; model = upstream([chunk('persistent', finish='stop'), '[DONE]'], requests=requests)
        process = None
        def stop():
            nonlocal process
            if process:
                process.terminate(); process.wait(timeout=8); process.stdout.close(); process.stderr.close(); process = None
        try:
            with tempfile.TemporaryDirectory() as folder:
                env = {**os.environ, 'OFFICE_WORKSPACE': folder, 'OFFICE_PORT': '0', 'PYTHONIOENCODING': 'utf-8'}
                def start():
                    nonlocal process
                    process = subprocess.Popen([sys.executable, '-u', str(app.BASE / 'app.py'), '--no-browser'], cwd=str(app.BASE), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    line = process.stdout.readline().decode('utf-8')
                    base = re.search(r'http://127\.0\.0\.1:\d+', line).group(0)
                    with urllib.request.urlopen(base) as response:
                        token = re.search(r"OFFICE_TOKEN='([^']+)'", response.read().decode()).group(1)
                    return base, token
                def chat(base, token, sid=''):
                    body = {**settings(model), 'text': 'persistent turn', 'mode': 'role', 'stream': True, 'session_id': sid}
                    req = urllib.request.Request(base + '/api/chat', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json', 'X-Office-Token': token})
                    with urllib.request.urlopen(req) as response:
                        return [json.loads(line) for line in response.read().decode().splitlines()]
                base, token = start(); first = chat(base, token)
                sid = next(e['session_id'] for e in first if e['type'] == 'session')
                stop(); base, token = start(); again = chat(base, token, sid)
                self.assertEqual(again[-1]['type'], 'done'); self.assertEqual(len(requests[-1]['messages']), 4)
                stop()
        finally:
            stop(); model.shutdown(); model.server_close()


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.old = app.OFFICE
        app.OFFICE = OfficeTools(self.temp.name); app.SESSIONS.clear()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = 'http://127.0.0.1:%d' % self.server.server_port

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); app.OFFICE = self.old; self.temp.cleanup()

    def post(self, path, data):
        return urllib.request.urlopen(urllib.request.Request(self.base + path, data=json.dumps(data).encode(), headers={'Content-Type': 'application/json', 'X-Office-Token': app.TOKEN}), timeout=10)

    def test_streaming_round_trip_history_and_disk_resume(self):
        calls = []; model = upstream([chunk('hello'), chunk(' world', finish='stop'), '[DONE]'], requests=calls)
        profile = settings(model); profile.pop('name'); profile.pop('key_source')
        try:
            with self.post('/api/chat', {**profile, 'stream': True, 'text': 'test stream', 'mode': 'role'}) as r:
                events = [json.loads(line) for line in r.read().decode().splitlines()]
            self.assertEqual(events[-1]['type'], 'done'); self.assertEqual(sum(e['type'] == 'answer_delta' for e in events), 2)
            sid = next(e['session_id'] for e in events if e['type'] == 'session'); task = events[0]['task_id']
            app.SESSIONS.clear(); app.STORES.pop(str(app.OFFICE.root), None)
            with self.post('/api/chat', {**profile, 'stream': True, 'text': 'continue', 'mode': 'role', 'session_id': sid}) as r:
                again = [json.loads(line) for line in r.read().decode().splitlines()]
            self.assertEqual(again[-1]['type'], 'done'); self.assertEqual(len(calls[-1]['messages']), 4)
            with urllib.request.urlopen(self.base + '/api/history/' + task) as r:
                self.assertEqual(json.load(r)['answer'], 'hello world')
            with urllib.request.urlopen(self.base + '/api/sessions/' + sid) as r:
                self.assertEqual(len(json.load(r)['transcript']), 4)
        finally:
            model.shutdown(); model.server_close()

    def test_cancelling_stream_does_not_commit_partial_session(self):
        gate = threading.Event(); model = upstream([chunk('partial'), chunk(' done', finish='stop'), '[DONE]'], gate=gate)
        try:
            with self.post('/api/chat', {**settings(model), 'stream': True, 'mode': 'role', 'text': 'cancel streaming'}) as r:
                events = []
                while not any(e['type'] == 'answer_delta' for e in events):
                    events.append(json.loads(r.readline()))
                task_id = events[0]['task_id']; sid = next(e['session_id'] for e in events if e['type'] == 'session')
                with self.post('/api/cancel', {'task_id': task_id}) as c:
                    self.assertTrue(json.load(c)['ok'])
                rest = [json.loads(line) for line in r.read().decode().splitlines()]
            self.assertEqual(rest[-1]['type'], 'cancelled')
            self.assertIsNone(app.local_state().get_session(sid)); self.assertNotIn(sid, app.SESSIONS)
            record = app.local_state().get_task(task_id)
            self.assertEqual(record['status'], 'cancelled'); self.assertEqual(record['partial_answer'], 'partial')
        finally:
            gate.set(); model.shutdown(); model.server_close()


if __name__ == '__main__':
    unittest.main()

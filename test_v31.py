"""v3.1 fixes: cancel, session expiry, env-key scope, Excel numbers, upstream errors, read caps.
Only local fake upstreams; run with provider keys unset. No paid API calls."""
import json
import os
import socket
import tempfile
import threading
import time
import unittest
import urllib.request
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from openpyxl import Workbook, load_workbook

import app
import providers
from office_tools import OfficeTools, PRECISION_NOTE, UNCACHED_LABEL, READ_CHAR_CAP


def slow_upstream(release, calls):
    """Chat Completions fixture that blocks until `release` is set (or 20 s)."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body)
            release.wait(20)
            message = {"role": "assistant", "content": "late answer"}
            if body.get("tools") and body["messages"][-1]["role"] != "tool":
                message = {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "list_files", "arguments": "{}"}}]}
            try:
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps({"choices": [{"message": message}]}).encode())
            except OSError:
                pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = app.OFFICE
        app.OFFICE = OfficeTools(self.temp.name)
        app.SESSIONS.clear()
        self.server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%d" % self.server.server_port

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        app.OFFICE = self.previous
        self.temp.cleanup()

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "X-Office-Token": app.TOKEN})
        return urllib.request.urlopen(req, timeout=15)

    def wait_lock_free(self, seconds):
        """Poll /api/demo until it is accepted (not 409). Returns elapsed seconds or None."""
        start = time.time()
        while time.time() - start < seconds:
            try:
                with self.post("/api/demo", {}) as response:
                    events = [json.loads(x) for x in response.read().decode().splitlines()]
                    if events[-1]["type"] == "done":
                        return time.time() - start
            except urllib.error.HTTPError as error:
                error.close()
                if error.code != 409:
                    raise
            time.sleep(0.1)
        return None


class CancelTests(ServerCase):
    def test_run_agent_checks_cancel_between_steps(self):
        cancel, calls = threading.Event(), []
        def complete(messages, tools):
            calls.append(1)
            cancel.set()  # user pressed stop while the model was answering
            return {"role": "assistant", "content": None, "tool_calls": [
                {"id": "1", "type": "function", "function": {"name": "list_files", "arguments": "{}"}}]}
        events = []
        with self.assertRaises(app.TaskCancelled):
            app.run_agent([{"role": "user", "content": "x"}], complete, events.append, cancel=cancel)
        self.assertEqual(len(calls), 1)
        self.assertFalse(any(e["type"] == "tool_start" for e in events))

    def test_cancel_endpoint_stops_task_and_releases_lock(self):
        release, calls = threading.Event(), []
        upstream = slow_upstream(release, calls)
        try:
            profile = {"provider": "custom", "base_url": "http://127.0.0.1:%d/v1" % upstream.server_port, "model": "m"}
            response = self.post("/api/chat", {**profile, "mode": "agent", "text": "go"})
            first = json.loads(response.readline())
            self.assertEqual(first["type"], "task")
            while not calls:
                time.sleep(0.05)
            started = time.time()
            with self.post("/api/cancel", {"task_id": first["task_id"]}) as r:
                self.assertTrue(json.load(r)["ok"])
            rest = [json.loads(x) for x in response.read().decode().splitlines()]
            response.close()
            self.assertEqual(rest[-1]["type"], "cancelled")
            self.assertLess(time.time() - started, 3)
            self.assertIsNotNone(self.wait_lock_free(3))
            self.assertEqual(len(calls), 1)  # no further model step after cancel
            with self.post("/api/cancel", {"task_id": first["task_id"]}) as r:
                self.assertFalse(json.load(r)["ok"])
        finally:
            release.set(); upstream.shutdown(); upstream.server_close()

    def test_client_disconnect_releases_lock_before_upstream_returns(self):
        release, calls = threading.Event(), []
        upstream = slow_upstream(release, calls)
        try:
            body = json.dumps({"provider": "custom", "base_url": "http://127.0.0.1:%d/v1" % upstream.server_port,
                               "model": "m", "mode": "role", "text": "go"}).encode()
            sock = socket.create_connection(("127.0.0.1", self.server.server_port))
            sock.sendall(("POST /api/chat HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nX-Office-Token: %s\r\n"
                          "Content-Type: application/json\r\nContent-Length: %d\r\n\r\n"
                          % (self.server.server_port, app.TOKEN, len(body))).encode() + body)
            while not calls:
                time.sleep(0.05)
            sock.close()  # browser refresh / tab closed
            elapsed = self.wait_lock_free(5)
            self.assertIsNotNone(elapsed, "lock still held after client disconnect")
            self.assertFalse(release.is_set())  # upstream had not answered yet
            self.assertFalse(app.SESSIONS)  # cancelled run is never committed
        finally:
            release.set(); upstream.shutdown(); upstream.server_close()


class SessionTests(ServerCase):
    def chat(self, **extra):
        body = {"provider": "custom", "base_url": "http://127.0.0.1:11434/v1", "model": "m", "mode": "role", "text": "hi", **extra}
        with self.post("/api/chat", body) as response:
            return [json.loads(x) for x in response.read().decode().splitlines()]

    def test_unknown_session_returns_expired_without_model_call(self):
        with patch("app.completion") as complete:
            events = self.chat(session_id="from-before-restart")
        complete.assert_not_called()
        expired = [e for e in events if e["type"] == "session_expired"]
        self.assertEqual(len(expired), 1)
        self.assertIn("失效", expired[0]["text"])
        self.assertFalse(any(e["type"] == "session" for e in events))

    def test_new_and_continued_sessions_and_settings_reset(self):
        with patch("app.completion", return_value={"role": "assistant", "content": "ok"}):
            first = self.chat()
            sid = next(e["session_id"] for e in first if e["type"] == "session")
            self.assertFalse(any(e.get("reset") for e in first))
            again = self.chat(session_id=sid)
            self.assertEqual(next(e for e in again if e["type"] == "session")["session_id"], sid)
            changed = self.chat(session_id=sid, model="other")
        event = next(e for e in changed if e["type"] == "session")
        self.assertTrue(event["reset"])
        self.assertEqual(event["reason"], "settings_changed")

    def test_eviction_is_least_recently_used(self):
        with patch("app.completion", return_value={"role": "assistant", "content": "ok"}):
            sid = next(e["session_id"] for e in self.chat() if e["type"] == "session")
            for i in range(49):
                app.SESSIONS["filler%d" % i] = {"mode": "role", "custom": "", "messages": [], "connection": None}
            self.chat(session_id=sid)  # touching it makes it most recent
            self.chat()  # a 51st session evicts the oldest filler, not the active one
        self.assertIn(sid, app.SESSIONS)
        self.assertNotIn("filler0", app.SESSIONS)
        self.assertLessEqual(len(app.SESSIONS), 50)


class KeyScopeTests(unittest.TestCase):
    def test_env_key_only_for_official_host(self):
        env = {"DEEPSEEK_API_KEY": "sk-env-secret-123", "CUSTOM_API_KEY": "sk-custom-env-456", "OLLAMA_API_KEY": "olk"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(providers.config({})["api_key"], "sk-env-secret-123")
            self.assertEqual(providers.config({"base_url": "https://api.deepseek.com/v1"})["key_source"], "env")
            for url in ("https://attacker.example/v1", "https://api.deepseek.com.evil.example", "https://api.deepseek.com:8443"):
                with self.assertRaisesRegex(ValueError, "官方地址"):
                    providers.config({"base_url": url})
            explicit = providers.config({"base_url": "https://proxy.example/v1", "api_key": "typed-in-ui"})
            self.assertEqual((explicit["api_key"], explicit["key_source"]), ("typed-in-ui", "ui"))
            custom = providers.config({"provider": "custom", "base_url": "https://my.example/v1"})
            self.assertEqual(custom["api_key"], "")
            moved = providers.config({"provider": "ollama", "base_url": "http://localhost:9999/v1"})
            self.assertEqual(moved["api_key"], "")
            self.assertEqual(providers.config({"provider": "ollama"})["api_key"], "olk")
            public = {p["id"]: p for p in providers.public_providers()}
            self.assertFalse(public["custom"]["has_key"])
            self.assertNotIn("sk-env", json.dumps(public))

    def test_redirect_and_error_text_never_leak_key(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(400); self.send_header("Content-Type", "application/json"); self.end_headers()
                self.wfile.write(json.dumps({"error": {"message": "This model's maximum context length is 65536 tokens. key sk-typed-secret-999 Bearer abcdefghij"}}).encode())
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            settings = providers.config({"provider": "custom", "base_url": "http://127.0.0.1:%d/v1" % server.server_port,
                                         "model": "m", "api_key": "sk-typed-secret-999"})
            with self.assertRaises(RuntimeError) as caught:
                providers.completion([{"role": "user", "content": "x"}], settings)
            text = str(caught.exception)
            self.assertIn("上下文长度", text)
            self.assertIn("maximum context length is 65536", text)
            self.assertNotIn("sk-typed-secret-999", text)
            self.assertNotIn("abcdefghij", text)
        finally:
            server.shutdown(); server.server_close()

    def test_plain_text_error_is_capped(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                self.send_response(500); self.end_headers(); self.wfile.write(b"upstream exploded " * 100)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            settings = providers.config({"provider": "custom", "base_url": "http://127.0.0.1:%d/v1" % server.server_port})
            with self.assertRaisesRegex(RuntimeError, "HTTP 500.*upstream exploded") as caught:
                providers.list_models(settings)
            self.assertLess(len(str(caught.exception)), 400)
        finally:
            server.shutdown(); server.server_close()


class ExcelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.tools = OfficeTools(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_detail_amounts_are_numbers_and_text_stays_text(self):
        self.tools.resolve("inputs/a.csv").write_text("编号,部门,金额,备注\n00123,行政,100.10,=1+1\n00124,研发,200,ok\n", encoding="utf-8")
        result = self.tools.summarize_table("inputs/a.csv", ["部门"], "金额")
        wb = load_workbook(self.tools.resolve(result["file"]))
        detail = wb["原始数据与检查"]
        self.assertEqual((detail["C2"].value, detail["C2"].data_type, detail["C2"].number_format), (100.1, "n", "#,##0.00"))
        self.assertEqual((detail["A2"].value, detail["A2"].data_type), ("00123", "s"))  # IDs keep leading zeros
        self.assertEqual((detail["D2"].value, detail["D2"].data_type), ("=1+1", "s"))  # no formula injection
        summary = wb["汇总"]
        self.assertEqual([c.value for c in summary[1]], ["部门", "有效记录数", "金额合计", "备注"])
        self.assertEqual(summary.cell(summary.max_row, 3).value, 300.1)
        self.assertEqual(summary.cell(summary.max_row, 3).number_format, "#,##0.00")
        wb.close()

    def test_values_beyond_excel_precision_are_exact_text_with_note(self):
        self.tools.resolve("inputs/b.csv").write_text("部门,金额\n行政,12345678901234567.89\n行政,0.1\n行政,0.2\n", encoding="utf-8")
        result = self.tools.summarize_table("inputs/b.csv", ["部门"], "金额")
        self.assertEqual(result["total"], "12345678901234568.19")
        wb = load_workbook(self.tools.resolve(result["file"]))
        summary, detail = wb["汇总"], wb["原始数据与检查"]
        self.assertEqual((summary["C2"].value, summary["C2"].data_type), ("12345678901234568.19", "s"))
        self.assertEqual(summary["D2"].value, PRECISION_NOTE)
        self.assertEqual(Decimal(detail["B2"].value), Decimal("12345678901234567.89"))
        self.assertIn(PRECISION_NOTE, detail["D2"].value)
        self.assertEqual(detail["B3"].value, 0.1)
        wb.close()

    def test_uncached_formula_is_labelled_not_missing(self):
        wb = Workbook(); ws = wb.active
        ws.append(["部门", "金额"]); ws.append(["行政", 100]); ws.append(["研发", "=50+50"]); ws.append(["市场", None])
        wb.save(self.tools.resolve("inputs/f.xlsx"))
        result = self.tools.summarize_table("inputs/f.xlsx", ["部门"], "金额")
        self.assertEqual(result["total"], "100")
        self.assertEqual(result["uncached_formula_rows"], 1)
        issues = {x["source_row"]: x["issues"] for x in result["issues"]}
        self.assertEqual(issues[3], [UNCACHED_LABEL])
        self.assertEqual(issues[4], ["金额缺失或非数字（未计入）"])
        self.assertEqual(self.tools.read_file("inputs/f.xlsx")["uncached_formula_cells"], 1)


class ReadCapTests(unittest.TestCase):
    def test_spreadsheet_read_is_character_capped(self):
        with tempfile.TemporaryDirectory() as folder:
            tools = OfficeTools(folder)
            tools.resolve("inputs/big.csv").write_text("a,b\n" + "\n".join(("x" * 5000) + ",1" for _ in range(300)), encoding="utf-8")
            out = tools.read_file("inputs/big.csv", limit=200)
            self.assertLessEqual(len(json.dumps(out["rows"], ensure_ascii=False)), READ_CHAR_CAP + 200)
            self.assertTrue(out["truncated"])
            self.assertTrue(out["has_more"])
            self.assertEqual(out["next_start_row"], out["start_row"] + len(out["rows"]))
            self.assertTrue(out["rows"][0][0].endswith("…[已截断]"))
            small = tools.read_file("inputs/big.csv", start_row=out["next_start_row"], limit=1)
            self.assertEqual(small["start_row"], out["next_start_row"])


if __name__ == "__main__":
    unittest.main()

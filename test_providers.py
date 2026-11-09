"""Provider protocol tests use a real local HTTP fixture, never paid APIs."""
import json
import os
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import app
import providers
from office_tools import OfficeTools


class ProviderTests(unittest.TestCase):
    def test_seven_profiles_and_no_public_secrets(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "SECRET_NOT_PUBLIC"}, clear=True):
            data = providers.public_providers()
        self.assertEqual(len(data), 7)
        self.assertTrue(next(p for p in data if p["id"] == "openai")["has_key"])
        self.assertNotIn("SECRET_NOT_PUBLIC", json.dumps(data))

    def test_endpoint_validation_and_independent_credentials(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "deep-only"}, clear=True):
            self.assertEqual(providers.config({})["api_key"], "deep-only")
            with self.assertRaisesRegex(ValueError, "OpenAI"):
                providers.config({"provider": "openai"})
            self.assertEqual(providers.config({"provider": "ollama"})["api_key"], "")
            for url in ("http://example.com/v1", "https://user:key@example.com", "https://example.com?key=secret", "file:///etc/passwd"):
                with self.assertRaises(ValueError):
                    providers.config({"provider": "custom", "base_url": url})

    def test_provider_specific_payloads(self):
        for preset in providers.PROVIDERS:
            settings = providers.config({"provider": preset["id"], "api_key": "test-key", "model": "test-chat", "base_url": "https://example.com/v1"})
            with patch("providers.request_json", return_value={"choices": [{"message": {"role": "assistant", "content": "OK"}}]}) as send:
                providers.completion([{"role": "user", "content": "hello"}], settings, app.TOOLS)
                payload = send.call_args.args[2]
                self.assertTrue(payload["tools"])
                self.assertEqual("thinking" in payload, preset["id"] == "deepseek")
                self.assertEqual("max_completion_tokens" in payload, preset["id"] == "openai")

    def test_live_local_models_chat_tools_and_session_isolation(self):
        seen = []
        class ModelHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps({"data": [{"id": "local-chat"}, {"id": "local-tools"}]}).encode())

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append(body)
                if body.get("tools") and body["messages"][-1]["role"] != "tool":
                    message = {"role": "assistant", "content": None, "tool_calls": [{"id": "local-call", "type": "function", "function": {"name": "list_files", "arguments": "{}"}}]}
                else:
                    message = {"role": "assistant", "content": "OK: local protocol verified"}
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps({"choices": [{"message": message}]}).encode())
        upstream = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
        ui = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        for server in (upstream, ui):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        old = app.OFFICE
        temp = tempfile.TemporaryDirectory()
        app.OFFICE = OfficeTools(temp.name)
        profile = {"provider": "custom", "base_url": "http://127.0.0.1:%d/v1" % upstream.server_port, "model": "local-tools"}
        def post(path, body):
            req = urllib.request.Request("http://127.0.0.1:%d%s" % (ui.server_port, path), data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "X-Office-Token": app.TOKEN})
            with urllib.request.urlopen(req) as response:
                return response.read().decode()
        try:
            result = json.loads(post("/api/models", profile))
            self.assertEqual(result["count"], 2)
            self.assertTrue(json.loads(post("/api/test", profile))["ok"])
            events = [json.loads(line) for line in post("/api/chat", {**profile, "mode": "agent", "text": "list files"}).splitlines()]
            self.assertEqual(events[-1]["type"], "done")
            self.assertTrue(any(e["type"] == "tool_end" for e in events))
            self.assertTrue(any(m["messages"][-1]["role"] == "tool" for m in seen))
            first_id = next(e["session_id"] for e in events if e["type"] == "session")
            events2 = [json.loads(line) for line in post("/api/chat", {**profile, "model": "another-model", "mode": "agent", "text": "again", "session_id": first_id}).splitlines()]
            second_id = next(e["session_id"] for e in events2 if e["type"] == "session")
            self.assertNotEqual(first_id, second_id)
        finally:
            app.OFFICE = old
            for server in (ui, upstream):
                server.shutdown(); server.server_close()
            temp.cleanup()

    def test_redirect_is_not_followed_with_credentials(self):
        visited = []
        class RedirectHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                visited.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/should-not-receive-secret")
                self.end_headers()
        server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            settings = providers.config({"provider": "custom", "base_url": "http://127.0.0.1:%d/v1" % server.server_port, "api_key": "secret"})
            with self.assertRaisesRegex(RuntimeError, "重定向"):
                providers.list_models(settings)
            self.assertEqual(visited, ["/v1/models"])
        finally:
            server.shutdown(); server.server_close()


if __name__ == "__main__":
    unittest.main()

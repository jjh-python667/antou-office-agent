"""Run: python -m unittest -v. No API key or external model requests."""
import base64
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from openpyxl import load_workbook
from docx import Document

import app
from office_tools import OfficeTools


class OfficeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.tools = OfficeTools(self.temp.name)
        self.old = app.OFFICE
        app.OFFICE = self.tools

    def tearDown(self):
        app.OFFICE = self.old
        self.temp.cleanup()

    def source(self):
        self.tools.resolve("inputs/cost.csv").write_text(
            "部门,金额,备注\n行政,0.1,=1+1\n行政,0.2,正常\n行政,0.2,正常\n研发,,缺失\n研发,NaN,无效\n,2,分组缺失\n", encoding="utf-8-sig")
        return "inputs/cost.csv"

    def test_summary_reconciliation_and_input_preservation(self):
        source = self.source()
        before = self.tools.resolve(source).read_bytes()
        out = self.tools.summarize_table(source, ["部门"], "金额")
        self.assertEqual(out["total"], "2.5")
        self.assertEqual(out["valid_amount_rows"], 4)
        self.assertEqual(out["issue_count"], 4)
        self.assertTrue(out["reconciled"])
        self.assertEqual(before, self.tools.resolve(source).read_bytes())
        wb = load_workbook(self.tools.resolve(out["file"]))
        self.assertEqual(wb["汇总"].cell(wb["汇总"].max_row, 3).value, 2.5)
        cell = wb["原始数据与检查"]["C2"]
        self.assertEqual(cell.value, "=1+1")
        self.assertEqual(cell.data_type, "s")
        wb.close()

    def test_scope_and_schema_rejection(self):
        for path in ("../outside.txt", "inputs/../../outside.txt", ".", "app.py"):
            with self.assertRaises(ValueError):
                self.tools.resolve(path)
        with self.assertRaises(ValueError):
            self.tools.execute("__class__", {})
        with self.assertRaises(ValueError):
            self.tools.execute("read_file", {"path": "x", "limit": "80"})
        with self.assertRaises(ValueError):
            self.tools.execute("list_files", {"unexpected": 1})

    def test_blank_rows_preserve_source_row_numbers(self):
        self.tools.resolve("inputs/blank.csv").write_text("部门,金额\n行政,1\n\n研发,坏值\n", encoding="utf-8")
        result = self.tools.summarize_table("inputs/blank.csv", ["部门"], "金额")
        self.assertEqual(result["source_rows"], 3)
        self.assertEqual([x["source_row"] for x in result["issues"]], [3, 4])

    def test_pagination_document_and_no_overwrite(self):
        source = self.source()
        self.assertTrue(self.tools.read_file(source, limit=2)["has_more"])
        args = {"filename": "report.docx", "title": "统计说明", "sections": [{"heading": "结果", "body": "金额 2.5\n重复数据保留。"}]}
        a = self.tools.write_document(**args)
        b = self.tools.write_document(**args)
        self.assertNotEqual(a["file"], b["file"])
        self.assertIn("金额 2.5", "\n".join(p.text for p in Document(self.tools.resolve(a["file"])).paragraphs))

    def test_agent_real_tools_two_rounds(self):
        source = self.source()
        events, requests = [], []
        def complete(messages, tools):
            requests.append(json.loads(json.dumps(messages)))
            if len(requests) == 1:
                return {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "summarize_table", "arguments": json.dumps({"path": source, "group_by": ["部门"], "amount_column": "金额"})}}]}
            self.assertEqual(messages[-1]["role"], "tool")
            result = json.loads(messages[-1]["content"])
            self.assertEqual(result["total"], "2.5")
            return {"role": "assistant", "content": "汇总完成：2.5"}
        app.run_agent([{"role": "user", "content": "汇总"}], complete, events.append)
        self.assertEqual(len(requests), 2)
        self.assertEqual(events[-1]["type"], "answer")
        self.assertTrue(any(e["type"] == "tool_end" and e["result"].get("verified") for e in events))

    def test_agent_error_feedback_and_round_limit(self):
        requests = []
        def complete(messages, tools):
            requests.append(json.loads(json.dumps(messages)))
            return {"role": "assistant", "tool_calls": [{"id": str(len(requests)), "function": {"name": "read_file", "arguments": "invalid json"}}]}
        with self.assertRaisesRegex(RuntimeError, "上限"):
            app.run_agent([], complete, lambda event: None, max_rounds=2)
        self.assertIn("error", json.loads(requests[1][-1]["content"]))

    def test_demo_end_to_end(self):
        events = []
        app.demo(events.append)
        outputs = [e["result"] for e in events if e["type"] == "tool_end" and "file" in e["result"]]
        self.assertEqual(len(outputs), 2)
        self.assertEqual(outputs[0]["total"], "780")
        for result in outputs:
            self.assertTrue(self.tools.resolve(result["file"]).is_file())

    def test_http_upload_demo_download_and_origin(self):
        server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:" + str(server.server_port)
        def post(path, body, token=app.TOKEN, origin=None):
            headers = {"Content-Type": "application/json", "X-Office-Token": token}
            if origin:
                headers["Origin"] = origin
            req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers=headers)
            return urllib.request.urlopen(req)
        try:
            with post("/api/upload", {"name": "data.csv", "data": base64.b64encode(b"a,b\n1,2").decode()}) as response:
                uploaded = json.load(response)
            self.assertTrue(self.tools.resolve(uploaded["file"]).exists())
            for token, origin in (("bad", None), (app.TOKEN, "https://evil.example")):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    post("/api/demo", {}, token, origin)
                self.assertEqual(error.exception.code, 403)
            with post("/api/demo", {}) as response:
                events = [json.loads(line) for line in response.read().decode().splitlines()]
            self.assertEqual(events[-1]["type"], "done")
            result = next(e["result"] for e in events if e["type"] == "tool_end" and e["name"] == "summarize_table")
            with urllib.request.urlopen(base + "/download?path=" + urllib.parse.quote(result["file"])) as response:
                self.assertTrue(response.read().startswith(b"PK"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()

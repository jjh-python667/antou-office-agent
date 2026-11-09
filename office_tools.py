"""Bounded office tools. No shell, eval, or arbitrary filesystem access."""
import csv
import io
import json
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def json_text(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def spec(name, description, properties, required):
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties,
                           "required": required, "additionalProperties": False}}}


S = {"type": "string"}
READ_CHAR_CAP = 20000      # one read_file page sent back to the model
CELL_CHAR_CAP = 2000       # one cell inside that page
EXCEL_DIGITS = 15          # Excel stores IEEE doubles: 15 significant digits are exact
AMOUNT_FORMAT = "#,##0.00"
UNCACHED_LABEL = "公式未计算（未计入）"
PRECISION_NOTE = "金额超过 Excel 15 位有效数字，按文本保存精确值，请勿直接参与 Excel 计算"


def excel_amount(amount):
    """Decimal -> (cell value, note). Numbers stay numeric unless Excel would silently round them."""
    digits = amount.normalize().as_tuple().digits
    if len(digits) <= EXCEL_DIGITS:
        return float(amount), ""
    return str(amount), PRECISION_NOTE


def is_formula(value):
    return (isinstance(value, str) and value.startswith("=")) or type(value).__name__ == "ArrayFormula"

TOOLS = [
    spec("list_files", "列出可读取的输入文件和已生成文件。", {}, []),
    spec("read_file", "读取 txt/md/csv/xlsx/docx；表格按 start_row/limit 分页，返回总行数。", {
        "path": S, "sheet": S, "start_row": {"type": "integer"}, "limit": {"type": "integer"}}, ["path"]),
    spec("summarize_table", "精确统计表格：按指定列分组，汇总金额列，标记缺失金额/分组和重复行。保留全部原始行，不擅自去重。生成 Excel，并返回核对结果。", {
        "path": S, "group_by": {"type": "array", "items": S}, "amount_column": S,
        "sheet": S, "output_name": S}, ["path", "group_by", "amount_column"]),
    spec("create_spreadsheet", "从明确的数据生成 Excel；所有文本按文本写入，暂不执行模型生成公式。", {
        "filename": S, "sheets": {"type": "array", "items": {"type": "object", "properties": {
            "name": S, "headers": {"type": "array", "items": S},
            "rows": {"type": "array", "items": {"type": "array", "items": {}}}},
            "required": ["name", "headers", "rows"], "additionalProperties": False}}}, ["filename", "sheets"]),
    spec("write_document", "生成 Word 报告/纪要。sections 为标题和正文，来源、口径和局限应在正文中说明。", {
        "filename": S, "title": S, "sections": {"type": "array", "items": {"type": "object",
            "properties": {"heading": S, "body": S}, "required": ["heading", "body"], "additionalProperties": False}}},
        ["filename", "title", "sections"]),
]


class OfficeTools:
    def __init__(self, workspace):
        self.root = Path(workspace).resolve()
        for folder in ("inputs", "outputs"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)

    def resolve(self, relative):
        path = (self.root / relative).resolve()
        if self.root not in path.parents or path.parts[len(self.root.parts)] not in ("inputs", "outputs"):
            raise ValueError("只能访问工作目录中的 inputs 和 outputs。")
        return path

    def output_path(self, filename, extension):
        name = Path(filename).name
        if name != filename or not name.lower().endswith(extension) or any(c in name for c in ':\\/\x00'):
            raise ValueError("输出名称必须是合法的 " + extension + " 文件名。")
        path = self.resolve("outputs/" + name)
        # Avoid overwriting a previous task's output.
        if path.exists():
            path = path.with_name(path.stem + "-" + uuid4().hex[:8] + path.suffix)
        return path

    def result(self, path, **extra):
        return {"file": path.relative_to(self.root).as_posix(), "bytes": path.stat().st_size, **extra}

    def list_files(self):
        files = [p for folder in ("inputs", "outputs") for p in (self.root / folder).iterdir()
                 if p.is_file() and self.root in p.resolve().parents]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [{"path": p.relative_to(self.root).as_posix(), "bytes": p.stat().st_size,
                 "modified_at": p.stat().st_mtime} for p in files[:300]]

    def table(self, path, sheet=""):
        headers, data, _ = self.table_ex(path, sheet)
        return headers, data

    def table_ex(self, path, sheet=""):
        """Returns headers, rows and {(row_index, col_index)} of formulas without a cached value."""
        p = self.resolve(path)
        formulas = set()
        if p.suffix.lower() == ".csv":
            raw = p.read_bytes()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("gb18030")
            rows = list(csv.reader(io.StringIO(text)))
        elif p.suffix.lower() == ".xlsx":
            wb = load_workbook(p, read_only=True, data_only=True)
            try:
                ws = wb[sheet] if sheet else wb.active
                if ws.max_row and ws.max_row > 50001:
                    raise ValueError("首版最多处理 50000 行。")
                rows = [list(row) for row in ws.iter_rows(values_only=True)]
            finally:
                wb.close()
            # Second pass reads formulas, so an uncached formula is not mistaken for a blank cell.
            wb = load_workbook(p, read_only=True, data_only=False)
            try:
                ws = wb[sheet] if sheet else wb.active
                for r, row in enumerate(ws.iter_rows(min_row=2, values_only=True)):
                    for c, value in enumerate(row):
                        if is_formula(value):
                            formulas.add((r, c))
            finally:
                wb.close()
        else:
            raise ValueError("统计支持 CSV 和 XLSX。")
        if not rows or not rows[0]:
            raise ValueError("表格为空，或没有表头。")
        if len(rows) > 50001 or len(rows[0]) > 200:
            raise ValueError("首版最多处理 50000 行、200 列。")
        headers = [str(x).strip() if x is not None else "" for x in rows[0]]
        if "" in headers or len(set(headers)) != len(headers):
            raise ValueError("首行必须是非空且不重复的表头。")
        # Preserve blank rows so source row numbers remain faithful to the file.
        data = [list(row) + [None] * max(0, len(headers) - len(row)) for row in rows[1:]]
        if any(len(row) > len(headers) for row in data):
            raise ValueError("数据行列数超过表头，请修正源文件。")
        uncached = {(r, c) for r, c in formulas if r < len(data) and c < len(data[r]) and data[r][c] is None}
        return headers, data, uncached

    def read_file(self, path, sheet="", start_row=0, limit=80):
        p = self.resolve(path)
        start_row, limit = max(0, start_row), min(200, max(1, limit))
        if p.suffix.lower() in (".xlsx", ".csv"):
            headers, rows, uncached = self.table_ex(path, sheet)
            # Cap characters, not only rows: one wide sheet must not flood the model context.
            cell_cap = max(50, min(CELL_CHAR_CAP, READ_CHAR_CAP // max(1, len(headers))))
            def clip(value):
                if isinstance(value, str) and len(value) > cell_cap:
                    return value[:cell_cap] + "…[已截断]"
                return value
            headers_out = [clip(h) for h in headers]
            page, used, clipped = [], len(json_text(headers_out)), False
            for row in rows[start_row:start_row + limit]:
                clean = [clip(v) for v in row]
                clipped = clipped or clean != row
                size = len(json_text(clean))
                if page and used + size > READ_CHAR_CAP:
                    break
                page.append(clean)
                used += size
            next_row = start_row + len(page)
            has_more = next_row < len(rows)
            return {"headers": headers_out, "total_rows": len(rows), "start_row": start_row,
                    "rows": page, "has_more": has_more, "next_start_row": next_row if has_more else None,
                    "truncated": clipped or len(page) < len(rows[start_row:start_row + limit]),
                    "char_cap": READ_CHAR_CAP, "uncached_formula_cells": len(uncached),
                    "note": "xlsx 公式读取缓存值；未计算的公式为空，汇总时标记为“公式未计算”。本页按字符上限截断，金额汇总使用完整文件，而非本页样本。"}
        if p.suffix.lower() == ".docx":
            doc = Document(p)
            lines = [x.text for x in doc.paragraphs]
            lines += [" | ".join(c.text for c in row.cells) for t in doc.tables for row in t.rows]
        elif p.suffix.lower() in (".txt", ".md"):
            lines = p.read_text(encoding="utf-8-sig").splitlines()
        else:
            raise ValueError("首版支持 txt、md、csv、xlsx、docx。")
        return {"text": "\n".join(lines[start_row:start_row + limit])[:20000],
                "total_lines": len(lines), "has_more": start_row + limit < len(lines)}

    @staticmethod
    def style_sheet(ws):
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for cell in ws[1]:
            cell.fill = PatternFill("solid", fgColor="173B36")
            cell.font = Font(color="FFFFFF", bold=True)
        for row in ws:
            for c in row:
                c.alignment = Alignment(vertical="top", wrap_text=True)
                if isinstance(c.value, (date, datetime)):
                    c.number_format = "yyyy-mm-dd"
        for col in range(1, ws.max_column + 1):
            width = max(len(str(ws.cell(r, col).value or "")) for r in range(1, min(ws.max_row, 60) + 1))
            ws.column_dimensions[get_column_letter(col)].width = min(40, max(14, width * 1.4))
        ws.sheet_view.showGridLines = False

    @staticmethod
    def append_safe(ws, row):
        ws.append(row)
        for c in ws[ws.max_row]:
            # Input values remain text, including strings beginning with =, +, -, @.
            if isinstance(c.value, str):
                c.data_type = "s"

    def create_spreadsheet(self, filename, sheets, number_formats=None):
        """number_formats is internal only (not in the tool schema): {sheet name: {column index: format}}."""
        if not 1 <= len(sheets) <= 20:
            raise ValueError("工作表数量应为 1–20。")
        path = self.output_path(filename, ".xlsx")
        wb = Workbook()
        wb.remove(wb.active)
        names = set()
        for s in sheets:
            name = s["name"]
            if not name or len(name) > 31 or any(c in name for c in '[]:*?/\\') or name.casefold() in names:
                raise ValueError("工作表名称不合法或重复。")
            names.add(name.casefold())
            if not s["headers"] or len(s["headers"]) > 200 or len(s["rows"]) > 50000:
                raise ValueError("表格应有表头，且不超过 50000 行、200 列。")
            ws = wb.create_sheet(name)
            self.append_safe(ws, s["headers"])
            for row in s["rows"]:
                if len(row) != len(s["headers"]):
                    raise ValueError("数据行列数必须与表头一致。")
                self.append_safe(ws, row)
            self.style_sheet(ws)
            for col, fmt in (number_formats or {}).get(name, {}).items():
                for row in ws.iter_rows(min_row=2, min_col=col + 1, max_col=col + 1):
                    for cell in row:
                        if isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
                            cell.number_format = fmt
        wb.save(path)
        # Verify the actual serialized file, not only the in-memory workbook.
        check = load_workbook(path, read_only=True)
        actual = [{"name": s.title, "rows": s.max_row - 1} for s in check]
        check.close()
        return self.result(path, sheets=actual, verified=True)

    def summarize_table(self, path, group_by, amount_column, sheet="", output_name="费用汇总.xlsx"):
        headers, rows, uncached = self.table_ex(path, sheet)
        if not group_by or len(set(group_by)) != len(group_by):
            raise ValueError("至少选择一个不重复的分组列。")
        for col in group_by + [amount_column]:
            if col not in headers:
                raise ValueError("不存在列：" + col + "；实际列：" + ", ".join(headers))
        indexes = [headers.index(c) for c in group_by]
        amount_idx = headers.index(amount_column)
        grouped = defaultdict(lambda: {"amount": Decimal("0"), "count": 0})
        total = Decimal("0")
        issues, seen, detail = [], set(), []
        valid = uncached_rows = 0
        for n, row in enumerate(rows, 2):
            labels = []
            identity = json_text(row)
            if identity in seen:
                labels.append("重复行（保留计入）")
            seen.add(identity)
            key = tuple(str(row[i]).strip() if row[i] is not None else "" for i in indexes)
            if any(not x for x in key):
                labels.append("分组字段缺失")
            raw = row[amount_idx]
            out = list(row)
            try:
                if raw is None and (n - 2, amount_idx) in uncached:
                    raise LookupError
                # Do not silently infer currency/locale or strip ambiguous separators.
                amount = Decimal(str(raw).strip())
                if not amount.is_finite() or isinstance(raw, bool):
                    raise InvalidOperation
            except LookupError:
                labels.append(UNCACHED_LABEL)
                uncached_rows += 1
            except (InvalidOperation, ValueError):
                labels.append("金额缺失或非数字（未计入）")
            else:
                total += amount
                valid += 1
                grouped[key]["amount"] += amount
                grouped[key]["count"] += 1
                # Detail amounts become real numbers (text stays text for every other column).
                out[amount_idx], note = excel_amount(amount)
                if note:
                    labels.append(note)
            if labels:
                issues.append({"source_row": n, "issues": labels})
            detail.append(out + [n, "；".join(labels)])
        summary = [list(k) + [v["count"], *excel_amount(v["amount"])] for k, v in sorted(grouped.items())]
        check_total = sum((v["amount"] for v in grouped.values()), Decimal("0"))
        summary.append(["合计"] + [""] * (len(group_by) - 1) + [valid, *excel_amount(total)])
        result = self.create_spreadsheet(output_name, [
            {"name": "汇总", "headers": group_by + ["有效记录数", "金额合计", "备注"], "rows": summary},
            {"name": "原始数据与检查", "headers": headers + ["源行号", "检查说明"], "rows": detail},
        ], number_formats={"汇总": {len(group_by) + 1: AMOUNT_FORMAT}, "原始数据与检查": {amount_idx: AMOUNT_FORMAT}})
        return {**result, "source": path, "source_rows": len(rows), "valid_amount_rows": valid,
                "total": str(total), "reconciled": total == check_total,
                "groups": [{"values": list(k), "count": v["count"], "amount": str(v["amount"])}
                           for k, v in sorted(grouped.items())][:100],
                "group_count": len(grouped), "issue_count": len(issues), "issues": issues[:100],
                "uncached_formula_rows": uncached_rows,
                "policy": "重复行保留并计入；无效金额不计入；公式未计算的金额不计入并单独标记；缺少分组的有效金额保留在空分组；"
                          "Excel 金额列显示两位小数、单元格保存完整值；超过 15 位有效数字的金额按文本保存精确值；不同币种请先分开。"}

    def write_document(self, filename, title, sections):
        if len(sections) > 80 or sum(len(s["body"]) for s in sections) > 100000:
            raise ValueError("文档过长，请拆分。")
        path = self.output_path(filename, ".docx")
        doc = Document()
        page = doc.sections[0]
        page.page_width, page.page_height = Inches(8.27), Inches(11.69)
        page.top_margin = page.bottom_margin = Inches(0.8)
        page.left_margin = page.right_margin = Inches(0.9)
        for name in ("Normal", "Title", "Heading 1", "Heading 2"):
            style = doc.styles[name]
            style.font.name = "Microsoft YaHei"
            style.font.color.rgb = RGBColor(0, 0, 0)
            style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "微软雅黑")
        doc.styles["Normal"].font.size = Pt(11)
        doc.styles["Normal"].paragraph_format.space_after = Pt(7)
        doc.styles["Normal"].paragraph_format.line_spacing = 1.25
        doc.add_heading(title, 0)
        for s in sections:
            if s["heading"]:
                doc.add_heading(s["heading"], 1)
            for paragraph in s["body"].split("\n"):
                doc.add_paragraph(paragraph)
        footer = page.footer.paragraphs[0]
        footer.alignment = 2
        footer.add_run("办公助手 · ")
        field = OxmlElement("w:fldSimple")
        field.set(qn("w:instr"), "PAGE")
        footer._p.append(field)
        doc.save(path)
        check = Document(path)
        return self.result(path, paragraphs=len(check.paragraphs), verified=True,
                           verification="已检查文件可重新读取；未进行 Word 页面渲染。")

    def execute(self, name, args):
        definition = next((t["function"] for t in TOOLS if t["function"]["name"] == name), None)
        if not definition:
            raise ValueError("未知工具：" + name)
        self.validate(args, definition["parameters"])
        return getattr(self, name)(**args)

    @classmethod
    def validate(cls, value, schema):
        kind = schema.get("type")
        expected = {"object": dict, "array": list, "string": str, "integer": int}.get(kind)
        if expected and (not isinstance(value, expected) or (kind == "integer" and isinstance(value, bool))):
            raise ValueError("工具参数类型错误：" + str(kind))
        if kind == "object":
            props = schema.get("properties", {})
            if any(k not in value for k in schema.get("required", [])) or any(k not in props for k in value):
                raise ValueError("工具参数缺失或包含未知字段。")
            for key, item in value.items():
                cls.validate(item, props[key])
        if kind == "array":
            for item in value:
                cls.validate(item, schema["items"])

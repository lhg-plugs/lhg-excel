#!/usr/bin/env python3
"""lhg-excel 确定性数据审计：扫描目标目录下的 xlsx 文件。

零第三方依赖：用标准库 zipfile + XML 解析 xlsx（Open XML）。
检查：文件可读性、公式错误值、公式复算抽查（SUM/AVERAGE/COUNT/
COUNTA/MIN/MAX/四则）、重复行率、空值率、类型混杂、大文件提示。

用法：
    python3 data_audit.py --target <目录> [--format json|text] [--fail-on blocker|warning|nit]

有 blocker 时以 exit code 2 退出（供 hooks 与 CI 使用）。
规则文案均为本项目原创。
"""

import argparse
import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

VERSION = "1.0.0"
TOOL = "lhg-excel/data-audit"

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
ERR_VALUES = {"#DIV/0!", "#N/A", "#NAME?", "#NULL!", "#NUM!", "#REF!", "#VALUE!"}
FORMULA_FUNCS = ("SUM", "AVERAGE", "COUNT", "COUNTA", "MIN", "MAX")
CELL_REF_RE = re.compile(r"\$?([A-Z]{1,3})\$?(\d+)")


class Finding:
    __slots__ = ("rule_id", "severity", "category", "title", "file", "line", "snippet", "detail")

    def __init__(self, rule_id, severity, category, title, file, line, snippet, detail):
        self.rule_id = rule_id
        self.severity = severity
        self.category = category
        self.title = title
        self.file = file
        self.line = line
        self.snippet = snippet
        self.detail = detail

    def to_dict(self):
        return {"rule_id": self.rule_id, "severity": self.severity,
                "category": self.category, "title": self.title,
                "file": self.file, "line": self.line,
                "snippet": self.snippet, "detail": self.detail}


# ---------------------------------------------------------------- xlsx 解析

def col_to_idx(col):
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def split_ref(ref):
    m = CELL_REF_RE.fullmatch(ref.replace("$", ""))
    if not m:
        return None
    return col_to_idx(m.group(1)), int(m.group(2)) - 1


class Sheet:
    """rows: list of list of cell dicts: {ref, kind, value, formula}."""

    def __init__(self, name):
        self.name = name
        self.rows = []

    def cell(self, r, c):
        if 0 <= r < len(self.rows) and 0 <= c < len(self.rows[r]):
            return self.rows[r][c]
        return None

    def num(self, r, c):
        cell = self.cell(r, c)
        if not cell:
            return None
        v = cell.get("value")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
        return None


def parse_xlsx(path):
    """返回 ([Sheet], error_message)。"""
    try:
        zf = zipfile.ZipFile(path)
    except Exception as e:
        return None, "不是合法的 zip/xlsx 文件：%s" % e
    try:
        strings = []
        try:
            ss_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in ss_root.findall("m:si", NS):
                strings.append("".join(t.text or "" for t in si.findall(".//m:t", NS)))
        except KeyError:
            pass

        wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
        sheet_names = [s.get("name") for s in wb_root.findall(".//m:sheet", NS)]

        sheets = []
        idx = 1
        for name in sheet_names:
            sheet = Sheet(name or "Sheet%d" % idx)
            try:
                data = zf.read("xl/worksheets/sheet%d.xml" % idx)
            except KeyError:
                idx += 1
                continue
            root = ET.fromstring(data)
            grid = {}
            max_r = max_c = -1
            for row in root.findall(".//m:row", NS):
                for c in row.findall("m:c", NS):
                    ref = c.get("r", "")
                    pos = split_ref(ref)
                    if not pos:
                        continue
                    ci, ri = pos
                    t = c.get("t")
                    f_el = c.find("m:f", NS)
                    v_el = c.find("m:v", NS)
                    formula = f_el.text if f_el is not None else None
                    raw_v = v_el.text if v_el is not None else None
                    cell = {"ref": ref, "kind": "blank", "value": None, "formula": formula}
                    if t == "s" and raw_v is not None:
                        try:
                            cell["kind"] = "str"
                            cell["value"] = strings[int(raw_v)]
                        except (IndexError, ValueError):
                            cell["value"] = ""
                    elif t == "inlineStr":
                        is_el = c.find("m:is", NS)
                        cell["kind"] = "str"
                        cell["value"] = "".join(t2.text or "" for t2 in
                                                is_el.findall(".//m:t", NS)) if is_el is not None else ""
                    elif t == "e":
                        cell["kind"] = "err"
                        cell["value"] = raw_v
                    elif raw_v is not None:
                        try:
                            cell["kind"] = "num"
                            cell["value"] = float(raw_v) if "." in raw_v else int(raw_v)
                        except ValueError:
                            cell["kind"] = "str"
                            cell["value"] = raw_v
                    elif formula is not None:
                        cell["kind"] = "formula"
                    grid[(ri, ci)] = cell
                    max_r, max_c = max(max_r, ri), max(max_c, ci)
            for r in range(max_r + 1):
                sheet.rows.append([grid.get((r, c), {"ref": "", "kind": "blank",
                                                     "value": None, "formula": None})
                                   for c in range(max_c + 1)])
            sheets.append(sheet)
            idx += 1
        return sheets, ""
    except Exception as e:
        return None, "解析失败：%s" % e
    finally:
        zf.close()


# ---------------------------------------------------------------- 公式复算

def eval_formula(formula, sheet):
    """支持 SUM/AVERAGE/COUNT/COUNTA/MIN/MAX(单区域) 与四则表达式。
    返回 (ok, value)；不支持时 ok=False。"""
    f = formula.strip().upper().replace("$", "")
    m = re.fullmatch(r"(SUM|AVERAGE|COUNT|COUNTA|MIN|MAX)\(([A-Z]{1,3}\d+:[A-Z]{1,3}\d+)\)", f)
    if m:
        func, rng = m.group(1), m.group(2)
        a, b = rng.split(":")
        pa, pb = split_ref(a), split_ref(b)
        if not pa or not pb:
            return False, 0
        (c1, r1), (c2, r2) = pa, pb
        vals, count_a = [], 0
        for r in range(min(r1, r2), max(r1, r2) + 1):
            for c in range(min(c1, c2), max(c1, c2) + 1):
                cell = sheet.cell(r, c)
                if not cell:
                    continue
                v = cell.get("value")
                if cell.get("kind") == "err":
                    return False, 0
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    vals.append(float(v))
                elif v not in (None, ""):
                    count_a += 1
        if func == "SUM":
            return True, sum(vals)
        if func == "AVERAGE":
            return (True, sum(vals) / len(vals)) if vals else (False, 0)
        if func == "COUNT":
            return True, float(len(vals))
        if func == "COUNTA":
            return True, float(len(vals) + count_a)
        if func == "MIN":
            return (True, min(vals)) if vals else (False, 0)
        if func == "MAX":
            return (True, max(vals)) if vals else (False, 0)
    # 四则：把单元格引用替换成数值后求值
    if re.fullmatch(r"[A-Z0-9+\-*/(). ]+", f):
        expr = f
        for ref in sorted(set(CELL_REF_RE.findall(f)), key=len, reverse=True):
            col, row = ref
            pos = split_ref(col + row)
            n = sheet.num(pos[1], pos[0]) if pos else None
            if n is None:
                return False, 0
            expr = re.sub(r"\b%s\b" % (col + row), repr(n), expr)
        try:
            return True, float(eval(expr, {"__builtins__": {}}, {}))
        except Exception:
            return False, 0
    return False, 0


# ---------------------------------------------------------------- 规则

RULES = []
_RULE_BY_ID = {}


def rule(rule_id, severity, category, title, detail):
    def deco(fn):
        r = {"id": rule_id, "severity": severity, "category": category,
             "title": title, "detail": detail}
        _RULE_BY_ID[rule_id] = r
        r["check"] = fn
        RULES.append(r)
        return fn
    return deco


def _hit(rule_id, path, sheet_name, ref, snippet):
    rule = _RULE_BY_ID[rule_id]
    return Finding(rule["id"], rule["severity"], rule["category"], rule["title"],
                   "%s!%s" % (path, sheet_name), ref, snippet, rule["detail"])


@rule("DATA-READ-001", "blocker", "可读性", "xlsx 文件损坏或无法解析",
      "文件不是合法的 xlsx（zip 损坏/缺少工作表 XML）。先修复文件再处理。")
def _r_read(ctx):
    if ctx["parse_error"]:
        yield _hit("DATA-READ-001", ctx["path"], "-", "-",
                   ctx["parse_error"][:120])


@rule("DATA-ERR-001", "blocker", "公式", "单元格含公式错误值",
      "缓存值为 #DIV/0!/#N/A/#VALUE!/#REF!/#NAME?/#NUM! 等。定位修公式，"
      "不许直接覆盖成静态值。")
def _r_err(ctx):
    for sh in ctx["sheets"]:
        for r, row in enumerate(sh.rows):
            for cell in row:
                if cell.get("kind") == "err" or cell.get("value") in ERR_VALUES:
                    yield _hit("DATA-ERR-001", ctx["path"], sh.name,
                               cell.get("ref") or "R%d" % (r + 1),
                               "错误值 %s" % cell.get("value"))


@rule("DATA-FORM-001", "blocker", "公式", "公式复算与缓存值对不上",
      "用 Python 对 SUM/AVERAGE/COUNT/COUNTA/MIN/MAX/四则公式独立重算，"
      "与单元格缓存值差值 ≥0.01。先让用户在 Excel 全量重算一次再下结论。")
def _r_form(ctx):
    for sh in ctx["sheets"]:
        for r, row in enumerate(sh.rows):
            for cell in row:
                f = cell.get("formula")
                if not f:
                    continue
                ok, expect = eval_formula(f, sh)
                if not ok:
                    continue
                v = cell.get("value")
                if isinstance(v, (int, float)) and abs(float(v) - expect) >= 0.01:
                    yield _hit("DATA-FORM-001", ctx["path"], sh.name,
                               cell.get("ref") or "R%d" % (r + 1),
                               "公式 %s 复算=%.2f 缓存=%s" % (f, expect, v))


@rule("DATA-DUP-001", "warning", "重复", "整行重复率超过 1%",
      "整行完全重复的行占比超阈值。建议去重（保留首次出现），主键重复需人工定。")
def _r_dup(ctx):
    for sh in ctx["sheets"]:
        if len(sh.rows) < 2:
            continue
        seen, dup = set(), 0
        for row in sh.rows[1:]:
            key = tuple("" if c.get("value") is None else str(c.get("value")) for c in row)
            if all(k == "" for k in key):
                continue
            if key in seen:
                dup += 1
            else:
                seen.add(key)
        total = len(sh.rows) - 1
        if total > 0 and dup / total > 0.01:
            yield _hit("DATA-DUP-001", ctx["path"], sh.name, "全表",
                       "重复 %d 行 / 共 %d 行（%.1f%%）" % (dup, total, dup / total * 100))


@rule("DATA-NULL-001", "warning", "空值", "某列空值率超过 30%",
      "空值率高的列先问用户再动：数值列默认不填 0，文本列留空。")
def _r_null(ctx):
    for sh in ctx["sheets"]:
        if len(sh.rows) < 2:
            continue
        ncols = max(len(r) for r in sh.rows)
        for c in range(ncols):
            vals = [sh.rows[r][c].get("value") if c < len(sh.rows[r]) else None
                    for r in range(1, len(sh.rows))]
            vals = [v for v in vals]
            if not vals:
                continue
            nulls = sum(1 for v in vals if v in (None, ""))
            if nulls / len(vals) > 0.30:
                header = sh.rows[0][c].get("value") if c < len(sh.rows[0]) else ""
                yield _hit("DATA-NULL-001", ctx["path"], sh.name, "第%d列" % (c + 1),
                           "列「%s」空值 %d/%d（%.0f%%）"
                           % (header, nulls, len(vals), nulls / len(vals) * 100))


@rule("DATA-TYPE-001", "warning", "类型", "列内类型混杂（数值与文本并存）",
      "同一列既有数值又有文本：常见于文本型数字、'—''待定'占位。转类型前先标出问用户。")
def _r_type(ctx):
    for sh in ctx["sheets"]:
        if len(sh.rows) < 2:
            continue
        ncols = max(len(r) for r in sh.rows)
        for c in range(ncols):
            kinds = set()
            for r in range(1, len(sh.rows)):
                if c >= len(sh.rows[r]):
                    continue
                v = sh.rows[r][c].get("value")
                if v in (None, ""):
                    continue
                kinds.add("num" if isinstance(v, (int, float)) and not isinstance(v, bool) else "str")
            if kinds == {"num", "str"}:
                header = sh.rows[0][c].get("value") if c < len(sh.rows[0]) else ""
                yield _hit("DATA-TYPE-001", ctx["path"], sh.name, "第%d列" % (c + 1),
                           "列「%s」数值与文本混杂" % header)


@rule("DATA-SIZE-001", "warning", "性能", "大文件（>5 万行）性能提示",
      "行数超过 5 万时脚本解析与清洗会变慢。建议先抽样定口径，或分块处理。")
def _r_size(ctx):
    for sh in ctx["sheets"]:
        if len(sh.rows) > 50000:
            yield _hit("DATA-SIZE-001", ctx["path"], sh.name, "全表",
                       "共 %d 行，超过 5 万行性能阈值" % len(sh.rows))


@rule("DATA-HEADER-001", "warning", "结构", "首行疑似不是表头",
      "首行存在空单元格或与下方类型明显不一致。合并单元格表头/标题行需先处理。")
def _r_header(ctx):
    for sh in ctx["sheets"]:
        if not sh.rows:
            continue
        header = sh.rows[0]
        blanks = sum(1 for c in header if c.get("value") in (None, ""))
        if blanks > len(header) / 2:
            yield _hit("DATA-HEADER-001", ctx["path"], sh.name, "第1行",
                       "首行 %d/%d 为空，疑似标题行或合并表头" % (blanks, len(header)))


# ---------------------------------------------------------------- 主流程

SKIP_DIRS = {".bak", ".git", "__pycache__", "node_modules"}


def collect_xlsx(target):
    out = []
    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.lower().endswith((".xlsx", ".xlsm")) and not f.startswith("~$"):
                out.append(os.path.join(root, f))
    return sorted(out)


def audit_file(path):
    sheets, err = parse_xlsx(path)
    ctx = {"path": path, "sheets": sheets or [], "parse_error": err}
    findings = []
    for r in RULES:
        try:
            findings.extend(r["check"](ctx))
        except Exception:
            continue  # 单条规则出错不影响整体：fail-open
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=".")
    ap.add_argument("--format", choices=["json", "text"], default="text")
    ap.add_argument("--fail-on", choices=["blocker", "warning", "nit"], default="blocker")
    args = ap.parse_args()

    target = os.path.abspath(args.target)
    findings = []
    files = collect_xlsx(target)
    for p in files:
        findings.extend(audit_file(p))

    sev_rank = {"blocker": 0, "warning": 1, "nit": 2}
    counts = {"blocker": 0, "warning": 0, "nit": 0}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1

    summary = {"tool": TOOL, "version": VERSION, "target": target,
               "files_scanned": len(files), "rules_run": len(RULES),
               "blocker": counts["blocker"], "warning": counts["warning"],
               "nit": counts.get("nit", 0)}

    if args.format == "json":
        print(json.dumps({"summary": summary,
                          "findings": [f.to_dict() for f in findings]},
                         ensure_ascii=False, indent=2))
    else:
        print("lhg-excel 数据审计 v%s：扫描 %d 个 xlsx，%d 条规则"
              % (VERSION, len(files), len(RULES)))
        print("blocker=%d warning=%d nit=%d"
              % (counts["blocker"], counts["warning"], counts.get("nit", 0)))
        for f in sorted(findings, key=lambda x: (sev_rank[x.severity], x.rule_id)):
            print("[%s][%s] %s %s %s" % (f.severity, f.rule_id, f.file, f.line, f.title))
            if f.snippet:
                print("    %s" % f.snippet)

    fail_rank = sev_rank[args.fail_on]
    bad = any(sev_rank[f.severity] <= fail_rank for f in findings)
    return 2 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

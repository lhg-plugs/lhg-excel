#!/usr/bin/env python3
"""lhg-excel 操作日志审计：校验 opslog.json 完整性与回滚可用性。

扫描目标目录（含子目录）下的 opslog.json：
- JSON 合法性、record 必填字段
- 每条改数操作是否有对应备份（路径真实存在）
- 同目录是否有 rollback.sh / ROLLBACK.md（回滚可用性）

用法：
    python3 log_audit.py --target <目录> [--format json|text] [--fail-on blocker|warning|nit]

有 blocker 时以 exit code 2 退出。零第三方依赖。
规则文案均为本项目原创。
"""

import argparse
import json
import os
import sys

VERSION = "1.0.0"
TOOL = "lhg-excel/log-audit"

REQUIRED_FIELDS = ("ts", "op", "file", "before", "after", "detail")
MUTATING_OPS = {"dedupe", "type_convert", "fill_na", "delete_rows",
                "formula_edit", "rollback"}
SKIP_DIRS = {".bak", ".git", "__pycache__", "node_modules"}


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


def _hit(rule_id, path, line, snippet):
    rule = _RULE_BY_ID[rule_id]
    return Finding(rule["id"], rule["severity"], rule["category"], rule["title"],
                   path, line, snippet, rule["detail"])


@rule("LOG-JSON-001", "blocker", "日志", "opslog.json 不是合法 JSON",
      "日志文件损坏或手工改坏了。修复 JSON 格式后再继续，缺失的记录按记忆补并标注。")
def _r_json(ctx):
    if ctx["json_error"]:
        yield _hit("LOG-JSON-001", ctx["path"], "-", ctx["json_error"][:120])


@rule("LOG-SCHEMA-001", "blocker", "日志", "日志记录缺必填字段",
      "必填：ts/op/file/before/after/detail。缺字段的记录补齐后再交付。")
def _r_schema(ctx):
    for i, rec in enumerate(ctx["records"]):
        missing = [k for k in REQUIRED_FIELDS if not rec.get(k)]
        if missing:
            yield _hit("LOG-SCHEMA-001", ctx["path"], "record#%d" % i,
                       "op=%s 缺字段：%s" % (rec.get("op", "?"), ",".join(missing)))


@rule("LOG-BACKUP-001", "blocker", "日志", "改数操作无对应备份",
      "op 为 dedupe/type_convert/fill_na/delete_rows/formula_edit 的记录，"
      "必须有 backup 字段且路径真实存在。无备份的变更不可回滚，必须补备份或重做。")
def _r_backup(ctx):
    d = os.path.dirname(ctx["path"])
    for i, rec in enumerate(ctx["records"]):
        if rec.get("op") not in MUTATING_OPS:
            continue
        bak = rec.get("backup")
        if not bak:
            yield _hit("LOG-BACKUP-001", ctx["path"], "record#%d" % i,
                       "op=%s 未记录备份路径" % rec.get("op"))
            continue
        full = bak if os.path.isabs(bak) else os.path.normpath(os.path.join(d, bak))
        if not os.path.isfile(full):
            yield _hit("LOG-BACKUP-001", ctx["path"], "record#%d" % i,
                       "op=%s 备份文件不存在：%s" % (rec.get("op"), bak))


@rule("LOG-ORDER-001", "warning", "日志", "backup 记录晚于改数记录",
      "备份应该在改数之前。顺序反了说明可能是先改后补备份，抽查备份内容是否真是改前版本。")
def _r_order(ctx):
    first_backup = first_mutate = None
    for i, rec in enumerate(ctx["records"]):
        if rec.get("op") == "backup" and first_backup is None:
            first_backup = i
        if rec.get("op") in MUTATING_OPS and first_mutate is None:
            first_mutate = i
    if first_mutate is not None and (first_backup is None or first_backup > first_mutate):
        yield _hit("LOG-ORDER-001", ctx["path"], "record#%d" % first_mutate,
                   "首次改数记录出现在备份记录之前")


@rule("RBK-MISS-001", "blocker", "回滚", "有改数记录但无回滚脚本",
      "opslog 里有改数操作，同目录却没有 rollback.sh 或 ROLLBACK.md。"
      "按 lhg-ex-opslog 第 5 步生成并实测后再交付。")
def _r_rbkmiss(ctx):
    d = os.path.dirname(ctx["path"])
    has_mutate = any(r.get("op") in MUTATING_OPS for r in ctx["records"])
    if not has_mutate:
        return
    sh = os.path.join(d, "rollback.sh")
    md = os.path.join(d, "ROLLBACK.md")
    if not (os.path.isfile(sh) or os.path.isfile(md)):
        yield _hit("RBK-MISS-001", ctx["path"], "-",
                   "共 %d 条改数记录，但目录下无 rollback.sh/ROLLBACK.md"
                   % sum(1 for r in ctx["records"] if r.get("op") in MUTATING_OPS))


@rule("RBK-EMPTY-001", "warning", "回滚", "回滚脚本存在但内容为空",
      "rollback.sh/ROLLBACK.md 是空文件。按 lhg-ex-opslog 第 5 步模板补全并实测。")
def _r_rbkempty(ctx):
    d = os.path.dirname(ctx["path"])
    for name in ("rollback.sh", "ROLLBACK.md"):
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.path.getsize(p) == 0:
            yield _hit("RBK-EMPTY-001", p, "-", "空文件")


@rule("LOG-IRREVERSIBLE-001", "warning", "日志", "存在不可逆操作记录",
      "有 record 的 reversible=false。确认用户知情，并在交付报告里单独列出。")
def _r_irrev(ctx):
    for i, rec in enumerate(ctx["records"]):
        if rec.get("reversible") is False:
            yield _hit("LOG-IRREVERSIBLE-001", ctx["path"], "record#%d" % i,
                       "op=%s 标记为不可逆" % rec.get("op"))


@rule("LOG-EMPTY-001", "nit", "日志", "opslog.json 存在但无有效记录",
      "records 为空。只读任务可以没有改数记录，但建议至少记一条 backup/诊断记录。")
def _r_empty(ctx):
    if not ctx["json_error"] and not ctx["records"]:
        yield _hit("LOG-EMPTY-001", ctx["path"], "-", "records 为空")


def collect_logs(target):
    out = []
    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f == "opslog.json" or f.endswith("_opslog.json"):
                out.append(os.path.join(root, f))
    return sorted(out)


def audit_log(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        records = data.get("records", []) if isinstance(data, dict) else []
        err = ""
        if not isinstance(data, dict) or not isinstance(records, list):
            err = "顶层结构应为 {\"records\": [...]}"
            records = []
    except Exception as e:
        data, records, err = None, [], "JSON 解析失败：%s" % e
    ctx = {"path": path, "records": records, "json_error": err}
    findings = []
    for r in RULES:
        try:
            findings.extend(r["check"](ctx))
        except Exception:
            continue
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=".")
    ap.add_argument("--format", choices=["json", "text"], default="text")
    ap.add_argument("--fail-on", choices=["blocker", "warning", "nit"], default="blocker")
    args = ap.parse_args()

    target = os.path.abspath(args.target)
    findings = []
    logs = collect_logs(target)
    for p in logs:
        findings.extend(audit_log(p))
    if not logs:
        # 没有日志文件本身记一条 nit（不影响 exit）
        findings.append(Finding("LOG-EMPTY-001", "nit", "日志",
                                "目标目录下未发现 opslog.json",
                                target, "-",
                                "尚未记录任何操作；开始改数前先建日志",
                                _RULE_BY_ID["LOG-EMPTY-001"]["detail"]))

    sev_rank = {"blocker": 0, "warning": 1, "nit": 2}
    counts = {"blocker": 0, "warning": 0, "nit": 0}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1

    summary = {"tool": TOOL, "version": VERSION, "target": target,
               "logs_scanned": len(logs), "rules_run": len(RULES),
               "blocker": counts["blocker"], "warning": counts["warning"],
               "nit": counts.get("nit", 0)}

    if args.format == "json":
        print(json.dumps({"summary": summary,
                          "findings": [f.to_dict() for f in findings]},
                         ensure_ascii=False, indent=2))
    else:
        print("lhg-excel 日志审计 v%s：扫描 %d 个 opslog，%d 条规则"
              % (VERSION, len(logs), len(RULES)))
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

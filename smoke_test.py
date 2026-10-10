#!/usr/bin/env python3
"""lhg-excel 插件冒烟测试：全部绿才算过。

检查项：
 1. 三个 JSON 合法（plugin.json / marketplace.json / hooks.json）
 2. 4 个 SKILL.md 都有 name/description frontmatter，且 150~320 行
 3. 3 个 commands 都有 description frontmatter
 4. 2 个 agents 都有 name/description/tools/model frontmatter
 5. skills 平台中立：不含 Claude Code 专有工具名
 6. fixtures：坏 fixture 的埋点规则必须全部命中且脚本 exit!=0；
    好 fixture 零 blocker 且 exit==0
 7. hooks 脚本：xlsx 自动备份 / 去重 / 逃生开关 / fail-open

用法：python3 smoke_test.py [--repo <插件根目录>]
退出码：0=全绿，1=有失败。
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, cond, detail=""):
    results.append((PASS if cond else FAIL, name, detail))
    return cond


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def frontmatter(path):
    text = read(path)
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    fm = {}
    for ln in text[3:end].split("\n"):
        m = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", ln)
        if m:
            fm[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return fm


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, **kw)


XLSX_BAD_MUST = {"DATA-ERR-001", "DATA-FORM-001", "DATA-DUP-001",
                 "DATA-NULL-001", "DATA-TYPE-001"}
LOG_BAD_MUST = {"LOG-SCHEMA-001", "LOG-BACKUP-001", "RBK-MISS-001"}
NEUTRAL_DENY = ["Task tool", "Bash tool", "Edit tool", "Write tool", "Read tool",
                "AskUserQuestion", "subagent_type", "PreToolUse", "PostToolUse",
                "${CLAUDE_", "CLAUDE_PLUGIN_ROOT", "CLAUDE_PROJECT_DIR"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.dirname(os.path.abspath(__file__)))
    args = ap.parse_args()
    repo = os.path.abspath(args.repo)
    AUDIT = os.path.join(repo, "scripts", "audit")

    # 1. JSON 合法
    for rel in [".claude-plugin/plugin.json", ".claude-plugin/marketplace.json",
                "hooks/hooks.json"]:
        p = os.path.join(repo, rel)
        try:
            d = json.loads(read(p))
            check("JSON 合法: " + rel, True)
            if rel.endswith("plugin.json"):
                check("plugin.json name==lhg-excel", d.get("name") == "lhg-excel",
                      str(d.get("name")))
                check("plugin.json 有 version/description/author",
                      all(d.get(k) for k in ("version", "description", "author")))
            if rel.endswith("marketplace.json"):
                ps = d.get("plugins", [])
                check("marketplace.json source==./",
                      len(ps) == 1 and ps[0].get("source") == "./" and
                      ps[0].get("name") == "lhg-excel", str(ps))
            if rel.endswith("hooks.json"):
                check("hooks.json 顶层有 hooks 包装", "hooks" in d)
                check("hooks.json 有 PreToolUse", "PreToolUse" in d["hooks"],
                      str(list(d["hooks"].keys())))
        except Exception as e:
            check("JSON 合法: " + rel, False, str(e))

    # 2. SKILL.md
    for skill in ["lhg-ex-clean", "lhg-ex-pivot", "lhg-ex-recalc", "lhg-ex-opslog"]:
        p = os.path.join(repo, "skills", skill, "SKILL.md")
        fm = frontmatter(p)
        check("skill frontmatter: " + skill,
              bool(fm.get("name")) and bool(fm.get("description")),
              "name=%s" % fm.get("name"))
        nlines = len(read(p).split("\n"))
        check("skill 行数 150~320: %s (%d 行)" % (skill, nlines),
              150 <= nlines <= 320, str(nlines))
        body = read(p)
        bad_words = [w for w in NEUTRAL_DENY if w in body]
        check("skill 平台中立: " + skill, not bad_words, "命中: %s" % bad_words)
        check("skill 有出品区: " + skill,
              "出品：刘洪光" in body and "https://github.com/lhg-skills" in body)
        check("skill 有自检与反馈: " + skill, "自检与反馈" in body)

    # 3. commands
    for cmd in ["excel", "excel-clean", "excel-audit"]:
        p = os.path.join(repo, "commands", cmd + ".md")
        fm = frontmatter(p)
        check("command description: " + cmd, bool(fm.get("description")),
              str(fm.get("description"))[:60])

    # 4. agents
    for ag in ["cleaner", "auditor"]:
        p = os.path.join(repo, "agents", ag + ".md")
        fm = frontmatter(p)
        check("agent frontmatter: " + ag,
              all(fm.get(k) for k in ("name", "description", "tools", "model")),
              str({k: fm.get(k) for k in ("name", "model")}))

    # 5. 审计脚本冒烟
    def audit_hits(script, target):
        r = run([sys.executable, os.path.join(AUDIT, script),
                 "--target", os.path.join(repo, target), "--format", "json"])
        try:
            d = json.loads(r.stdout)
        except Exception:
            return None, r.returncode, []
        return d["summary"], r.returncode, [f["rule_id"] for f in d["findings"]]

    s, code, ids = audit_hits("data_audit.py", "fixtures/xlsx-bad")
    check("data 坏 fixture exit!=0", code != 0, "exit=%d" % code)
    check("data 坏 fixture blocker>0", s and s["blocker"] > 0, str(s))
    missing = XLSX_BAD_MUST - set(ids)
    check("data 埋点全命中 (%d/%d)" % (len(XLSX_BAD_MUST - missing), len(XLSX_BAD_MUST)),
          not missing, "缺失: %s" % sorted(missing))

    s, code, _ = audit_hits("data_audit.py", "fixtures/xlsx-good")
    check("data 好 fixture 零 blocker", s and s["blocker"] == 0, str(s))
    check("data 好 fixture exit==0", code == 0, "exit=%d" % code)

    s, code, ids = audit_hits("log_audit.py", "fixtures/log-bad")
    check("log 坏 fixture exit!=0", code != 0, "exit=%d" % code)
    check("log 坏 fixture blocker>0", s and s["blocker"] > 0, str(s))
    missing = LOG_BAD_MUST - set(ids)
    check("log 埋点全命中 (%d/%d)" % (len(LOG_BAD_MUST - missing), len(LOG_BAD_MUST)),
          not missing, "缺失: %s" % sorted(missing))

    s, code, _ = audit_hits("log_audit.py", "fixtures/log-good")
    check("log 好 fixture 零 blocker", s and s["blocker"] == 0, str(s))
    check("log 好 fixture exit==0", code == 0, "exit=%d" % code)

    # 6. hooks：xlsx 自动备份
    def hook(payload, env=None):
        e = dict(os.environ)
        e.update(env or {})
        return run([sys.executable, os.path.join(repo, "hooks", "pre_xlsx_backup.py")],
                   input=payload, env=e)

    with tempfile.TemporaryDirectory() as td:
        xlsx = os.path.join(td, "sales.xlsx")
        with open(xlsx, "wb") as fh:
            fh.write(b"PK-fake-xlsx")
        base_env = {"CLAUDE_PROJECT_DIR": td}

        r = hook('{"tool_input":{"command":"ls -la"}}', base_env)
        check("hook: 无 xlsx 命令不备份", r.returncode == 0 and not r.stdout.strip()
              and not os.path.isdir(os.path.join(td, ".bak")), r.stdout[:80])

        r = hook('{"tool_input":{"command":"python3 clean.py sales.xlsx"}}', base_env)
        bak_dir = os.path.join(td, ".bak")
        baks = os.listdir(bak_dir) if os.path.isdir(bak_dir) else []
        check("hook: 引用 xlsx 自动备份", r.returncode == 0 and len(baks) == 1
              and baks[0].startswith("sales.xlsx.bak-"), str(baks))
        check("hook: 备份后有提示", "additionalContext" in r.stdout, r.stdout[:80])

        r = hook('{"tool_input":{"command":"python3 clean.py sales.xlsx"}}', base_env)
        baks2 = os.listdir(bak_dir)
        check("hook: 重复命令不重复备份（去重）", len(baks2) == 1, str(baks2))

        with open(xlsx, "wb") as fh:  # 改动源文件 → 应再备一份
            fh.write(b"PK-fake-xlsx-v2")
        import time as _t
        _t.sleep(0.05)
        os.utime(xlsx, None)
        r = hook('{"tool_input":{"command":"python3 clean.py sales.xlsx"}}', base_env)
        baks3 = os.listdir(bak_dir)
        check("hook: 源文件变化后重新备份", len(baks3) == 2, str(baks3))

        r = hook('{"tool_input":{"command":"python3 clean.py sales.xlsx"}}',
                 dict(base_env, LHG_EXCEL_BACKUP_OFF="1"))
        check("hook: 逃生开关生效", r.returncode == 0 and not r.stdout.strip(),
              r.stdout[:80])

        r = hook("not-json{{{", base_env)
        check("hook: 非法输入 fail-open", r.returncode == 0, r.stdout[:80])

    # 报告
    print("=" * 60)
    print("lhg-excel 冒烟测试报告")
    print("=" * 60)
    fails = 0
    for st, name, detail in results:
        mark = "✓" if st == PASS else "✗"
        print("%s %s %s" % (mark, st, name))
        if detail and st == FAIL:
            print("    → %s" % detail)
        if st == FAIL:
            fails += 1
    print("=" * 60)
    print("共 %d 项，通过 %d，失败 %d" % (len(results), len(results) - fails, fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

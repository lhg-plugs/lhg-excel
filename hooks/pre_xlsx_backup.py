#!/usr/bin/env python3
"""lhg-excel 硬门：处理 xlsx 前自动备份原文件到 .bak/。

触发：PreToolUse / Bash。脚本从本次 Bash 命令中找出引用的、
本地已存在的 .xlsx/.xlsm/.xls 文件，在命令执行前各复制一份
带时间戳的备份到文件同目录的 .bak/ 下。

备份去重：若该文件已有一份备份新于源文件 mtime（即源文件上次
备份后没再被改过），则跳过，避免重复命令产生一堆备份。

逃生方式（按推荐度排序）：
  1. 这是信息型 hook，不拦截命令，只做备份；想关掉自动备份：
     LHG_EXCEL_BACKUP_OFF=1（环境变量，当前会话有效）。
  2. /plugin disable lhg-excel（整个插件停用，hooks 不再触发）。

设计原则：内部出错一律 fail-open（直接放行，不备份也不报错）；
零第三方依赖。
"""

import json
import os
import re
import shutil
import sys
import time

XLSX_RE = re.compile(
    r"""(?:"([^"]+\.xls[xm]?)")|(?:'([^']+\.xls[xm]?)')|([^\s"'`$()|;&<>]+\.xls[xm]?)""",
    re.IGNORECASE,
)
TS_FMT = "%Y%m%d-%H%M%S"


def iter_xlsx_paths(command):
    seen = set()
    for m in XLSX_RE.finditer(command):
        p = m.group(1) or m.group(2) or m.group(3)
        if p and p not in seen:
            seen.add(p)
            yield p


def newest_backup(bak_dir, base):
    """返回该文件最新的备份路径与 mtime，没有则 (None, 0)。"""
    if not os.path.isdir(bak_dir):
        return None, 0
    prefix = base + ".bak-"
    best, best_mt = None, 0
    for fn in os.listdir(bak_dir):
        if fn.startswith(prefix):
            fp = os.path.join(bak_dir, fn)
            try:
                mt = os.path.getmtime(fp)
            except OSError:
                continue
            if mt > best_mt:
                best, best_mt = fp, mt
    return best, best_mt


def main() -> int:
    # 逃生开关
    if os.environ.get("LHG_EXCEL_BACKUP_OFF") == "1":
        return 0

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0  # 输入解析失败：fail-open

    tool_input = payload.get("tool_input", {}) or {}
    command = tool_input.get("command", "") or ""
    if not command:
        return 0

    try:
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        backed = []
        for p in iter_xlsx_paths(command):
            # 只处理本地已存在的文件；URL/通配符/不存在的路径跳过
            src = p if os.path.isabs(p) else os.path.join(project_dir, p)
            src = os.path.normpath(src)
            if not os.path.isfile(src):
                continue
            try:
                src_mt = os.path.getmtime(src)
            except OSError:
                continue
            d = os.path.dirname(src) or "."
            base = os.path.basename(src)
            bak_dir = os.path.join(d, ".bak")
            _, bak_mt = newest_backup(bak_dir, base)
            if bak_mt >= src_mt:
                continue  # 已有新鲜备份，跳过
            os.makedirs(bak_dir, exist_ok=True)
            ts = time.strftime(TS_FMT, time.localtime())
            dest = os.path.join(bak_dir, "%s.bak-%s%s" % (base, ts, os.path.splitext(base)[1]))
            # 同一秒重复触发时加序号，避免覆盖
            n = 1
            stem_dest = dest
            while os.path.exists(dest):
                n += 1
                root, ext = os.path.splitext(stem_dest)
                dest = "%s-%d%s" % (root, n, ext)
            shutil.copy2(src, dest)
            backed.append(dest)
    except Exception:
        return 0  # 任何内部错误：fail-open

    if not backed:
        return 0
    msg = (
        "自动备份（lhg-excel）：本次命令引用了 %d 个表格文件，已备份到 .bak/：\n%s\n"
        "关闭自动备份：export LHG_EXCEL_BACKUP_OFF=1（当前会话有效）。"
        % (len(backed), "\n".join("- " + b for b in backed))
    )
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": msg}}
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

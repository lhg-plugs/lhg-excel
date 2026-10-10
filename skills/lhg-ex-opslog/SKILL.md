---
name: lhg-ex-opslog
description: 表格操作日志规范：opslog.json 字段格式、备份命名、rollback.sh 生成规范。任何数据变更前先加载。
license: MIT
compatibility: 适用于任何支持 Markdown 指令的 AI 助手（Claude Code、豆包、Workbuddy 等）
metadata:
  version: 1.0.0
  author: 刘洪光
---

# lhg-ex-opslog：操作日志与回滚规范

> 目标：让"AI 改了我的数"可查证、可回滚。核心纪律：**无日志的变更 = 没发生过；无备份的变更 = 不许发生**。

## 1. 何时使用

- 任何要改表格数据的任务开始前 → 先读第 2、3 步（备份规范）
- 每次执行清洗/改数动作时 → 按第 4 步记日志
- 任务结束交付前 → 按第 5 步生成回滚脚本，第 6 步自查

## 2. 备份规范（改前必做）

1. 插件 hook 会在处理 xlsx 前自动把原文件复制到同目录 `.bak/` 下（文件名：`<原名>.bak-<YYYYMMDD-HHMMSS>.xlsx`）。可用环境变量 `LHG_EXCEL_BACKUP_OFF=1` 关闭自动备份。
2. hook 没触发时（如平台不支持 hooks），**手动复制一份**再动手，路径记下来告诉用户。
3. 备份文件不许覆盖：每次备份带时间戳，保留最近 5 份，旧的可以删但要在日志里记。
4. `.bak/` 目录建议加入版本控制忽略名单（它只是安全网，不是交付物）。

## 3. opslog.json 格式

日志文件放在表格同目录，命名 `opslog.json`（一个目录一份，追加写）。每条记录字段：

```json
{
  "records": [
    {
      "ts": "2026-10-11T14:02:11+08:00",
      "op": "dedupe",
      "file": "销售明细.xlsx",
      "sheet": "Sheet1",
      "range": "A2:R12001",
      "before": "12000 行",
      "after": "11963 行",
      "detail": "删除 37 行整行重复，保留首次出现",
      "backup": ".bak/销售明细.xlsx.bak-20261011-140200.xlsx",
      "reversible": true
    }
  ]
}
```

字段说明：

| 字段 | 必填 | 说明 |
|---|---|---|
| ts | 是 | ISO 8601 时间，带时区 |
| op | 是 | 操作类型：`backup` / `dedupe` / `type_convert` / `fill_na` / `delete_rows` / `formula_edit` / `pivot` / `chart` / `other` |
| file | 是 | 被操作的文件名 |
| sheet | 否 | 涉及的 sheet |
| range | 否 | 涉及的单元格范围 |
| before / after | 是 | 变更前后摘要（一句话，有数字） |
| detail | 是 | 具体做了什么、口径是什么 |
| backup | 条件必填 | 凡是改了数据的 op，必须有对应备份路径 |
| reversible | 是 | true=可回滚（有备份/逆操作），false=不可逆（如删列未备份，要写理由） |

## 4. 记日志的时机

- 每做完**一个**清洗动作记一条，不许攒到最后一起写（中途断了就丢了）。
- 只读操作（诊断、审计、生成新文件）记 `op` 为 `other` 也可以不记；**凡是动了用户原文件或其副本数据的，必须记**。
- 批量脚本改表：脚本运行前记一条 `backup`，运行后记一条汇总。

## 5. 回滚脚本规范

任务结束时，在表格同目录生成 `rollback.sh`（Bash）和/或 `ROLLBACK.md`（说明）：

`rollback.sh` 模板：

```bash
#!/bin/bash
# 回滚：把本次变更全部撤销，恢复到备份状态
# 用法：bash rollback.sh
set -euo pipefail
cp ".bak/销售明细.xlsx.bak-20261011-140200.xlsx" "销售明细.xlsx"
echo "已回滚到备份：.bak/销售明细.xlsx.bak-20261011-140200.xlsx"
```

`ROLLBACK.md` 模板：

```markdown
# 回滚说明
- 备份文件：.bak/xxx.bak-<时间>.xlsx
- 回滚方式：bash rollback.sh（自动用备份覆盖当前文件）
- 变更清单：见 opslog.json（共 N 条记录）
- 不可逆操作：无 / 有（列出 op 与理由）
```

回滚脚本生成后要**实测一次**（复制到临时目录跑一遍，确认能恢复），再交付。

## 6. 完整性自查（交付前）

1. `opslog.json` 是合法 JSON，records 非空。
2. 每条改数据的记录都有 `backup` 字段，且路径真实存在。
3. `rollback.sh` 存在且实测可跑（插件审计脚本 `log_audit.py` 会自动查这三项）。
4. 告诉用户三件事：备份在哪、日志在哪、怎么回滚。

## 7. 多文件 / 多轮次场景

- 一个目录多个表：`opslog.json` 按文件分 record，共用一份即可（`file` 字段区分）。
- 多轮清洗：record 按时间追加，不许覆盖旧记录；回滚时按时间戳选最近一次备份。
- 用户中途改需求（如"刚才删的别删了"）：从 `.bak/` 恢复对应版本，记一条 `op: rollback` 的 record。

## 8. opslog 查询小抄

```bash
# 看一共做了多少次变更
python3 -c "import json;d=json.load(open('opslog.json'));print(len(d['records']))"
# 看有没有不可逆操作
python3 -c "import json;d=json.load(open('opslog.json'));print([r['op'] for r in d['records'] if not r.get('reversible',True)])"
```

## 9. 反模式（不许这么干）

- ❌ 改完才想起来记日志，凭记忆补
- ❌ backup 字段写了路径但文件不存在
- ❌ 多次备份互相覆盖，只剩最后一份
- ❌ rollback.sh 没实测就交付
- ❌ 把 `.bak/` 当交付物发给用户（发汇报版 xlsx，不是备份）

## 10. 常见问题

- **Q：用户嫌日志麻烦，不想记？** A：日志是信任机制，不是负担。跟用户说清楚：没有日志，出问题时谁都说不清数怎么变的。
- **Q：.bak 越积越多？** A：保留最近 5 份，旧的删之前在日志里记一笔。
- **Q：rollback.sh 在 Windows 上跑不了？** A：同时给 ROLLBACK.md 手工步骤（复制备份覆盖当前文件，两步）。

## 11. 自检与反馈

**质检门**：
- [ ] 备份存在且带时间戳？
- [ ] 每次数据变更都有日志？
- [ ] 日志字段齐全（ts/op/file/before/after/detail/backup）？
- [ ] rollback.sh 实测通过？
- [ ] 用户被告知了备份/日志/回滚位置？

**标准冒烟用例**：用插件 `fixtures/` 的 opslog 好/坏用例跑 `log_audit.py`，确认坏用例的缺失字段、无备份 modify、无回滚脚本都被命中。

**发现问题**：到本仓库提 issue（标题前缀 `[lhg-ex-opslog]`），描述：场景、日志现状、哪条规范卡住了。

## 出品：刘洪光

刘洪光（https://github.com/lhg-skills）出品，lhg-plugs「小白专家插件」系列之一。
本 skill 方法论文案为原创（操作日志的字段设计借鉴数据库审计日志的通用实践）。

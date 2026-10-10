<!-- About 简介（推送后填写到仓库 About 栏）：
表格数据专家：清洗透视图表一条龙 ｜ 一键安装：/plugin marketplace add lhg-plugs/lhg-excel
-->
<!-- topics（推送后打）：claude-code, claude-plugin, agent-skills, excel, data-analysis, openpyxl -->

# lhg-excel：表格数据专家，清洗透视图表一条龙

> **一句话介绍**：给 AI 编程助手装上"表格数据专家"——丢入杂乱表格，自动诊断→清洗（去重/类型/空值）→透视→图表→带格式的汇报版 xlsx；**所有数据变更保留操作日志+改前自动备份，可回滚**，再也不怕"AI 改了我的数"。
>
> **一键安装**：在 Claude Code 里运行
> ```
> /plugin marketplace add lhg-plugs/lhg-excel
> /plugin install lhg-excel@lhg-plugs
> ```

## 它是什么

`lhg-excel` 是一个 Claude Code 插件（plugin 为主、skill 为辅）：

- **3 个命令**（小白入口）：`excel` 杂乱表格一条龙，`excel-clean` 只做清洗，`excel-audit` 公式复算+结果抽查+日志体检
- **4 个平台中立 skill**（方法论，可移植到豆包/Workbuddy 等 agent 平台）：数据清洗五步法、透视与图表、公式复算抽查、操作日志与回滚规范
- **2 个专家 agent**：表格清洗专家、表格审计专家
- **1 个硬门 hook**：处理 xlsx 前自动备份原文件到 `.bak/`（可一键关闭）
- **16 条确定性审计规则**：纯 Python 标准库、零第三方依赖，xlsx 用 zipfile+XML 直接解析

## 信任机制：AI 改数，留痕可查、可回滚

这是本插件与"直接让 AI 改表"最大的区别：

1. **改前自动备份**：hook 在命令执行前把引用的 xlsx 复制到同目录 `.bak/`（带时间戳，不覆盖）；可用 `LHG_EXCEL_BACKUP_OFF=1` 关闭。
2. **操作日志**：每个数据变更记一条 `opslog.json`（时间/操作/范围/变更前后/备份路径），见 `lhg-ex-opslog` skill。
3. **回滚脚本**：交付时生成 `rollback.sh`（实测可用）+ `ROLLBACK.md` 说明，一键恢复。
4. **公式复算抽查**：审计脚本对 SUM/AVERAGE/COUNT 等基础公式独立重算，比对缓存值，对不上就报 blocker。

## 3 个命令用法

| 命令 | 作用 | 示例 |
|---|---|---|
| `/lhg-excel:excel` | 杂乱表格→诊断→清洗→透视→图表→汇报版 xlsx 一条龙 | `/lhg-excel:excel "销售明细.xlsx"` |
| `/lhg-excel:excel-clean` | 只做清洗（去重/类型/空值/junk 行） | `/lhg-excel:excel-clean "客户名单.xlsx"` |
| `/lhg-excel:excel-audit` | 体检：公式复算+空值/重复率+日志完整性+回滚可用性 | `/lhg-excel:excel-audit ./data` |

## 目录结构

```
lhg-excel/
├── .claude-plugin/          # plugin.json（插件清单）+ marketplace.json（本仓即市场）
├── commands/                # 3 个命令：excel / excel-clean / excel-audit
├── skills/                  # 4 个平台中立 skill（清洗/透视图表/复算抽查/操作日志）
├── agents/                  # 2 个专家 agent（cleaner / auditor）
├── hooks/                   # xlsx 自动备份 hook（fail-open，可一键关闭）
├── scripts/audit/           # 确定性审计：data_audit.py + log_audit.py（零第三方依赖）
├── fixtures/                # 好/坏对照用例 + 生成器
├── smoke_test.py            # 冒烟测试（50 项）
├── ATTRIBUTION.md           # 灵感来源声明
└── LICENSE                  # MIT
```

## 什么时候用 / 什么时候不用（FAQ）

**Q：大文件（几十万行）能处理吗？**
A：能，但要设对预期。审计脚本用流式思路解析 xlsx，5 万行以下秒级；超过 5 万行会报性能提示，建议先抽样定口径再全量跑。超大文件（百万行级）建议先转 CSV 或数据库处理——Excel 本身也不是为这个量级设计的。

**Q：支持 .xls 老格式吗？**
A：审计脚本只读 .xlsx/.xlsm（Open XML）。`.xls` 老格式先用 Excel/WPS 另存为 `.xlsx`，转完校验行列数一致再处理。命令流程里已包含这一步。

**Q：AI 会不会悄悄改我的数？**
A：这是本插件要解决的核心问题，四层防护：①改前自动备份到 `.bak/`；②每个变更记 `opslog.json`（变更前后数字）；③交付 `rollback.sh` 一键回滚；④审计脚本复算公式+校验日志完整性。交付报告里每个动作都有数字可查。

**Q：公式会被破坏吗？**
A：不会。清洗流程明确规定：公式列只修引用错误，不许把公式拍平成静态值；复算抽查会独立重算基础公式比对缓存值。

**Q：一定要用 Claude Code 吗？**
A：`skills/` 下的方法论是平台中立的纯 Markdown，可直接搬到豆包、Workbuddy 等 agent 平台用。只有 commands/agents/hooks 需要 Claude Code。

**Q：和直接问 AI"帮我整理表格"有什么区别？**
A：区别在"流程"和"证据"：诊断卡先确认口径、每步记日志、交付带复算抽查记录。直接问 AI 没有这些，出问题时说不清数怎么变的。

## 自迭代

- 每个 skill 末尾有「自检与反馈」节：质检门 + 标准冒烟用例 + 一键提 issue。
- 发现规则误报/漏报、方法论不合理：到本仓库提 issue（标题带对应 skill 前缀，如 `[lhg-ex-clean]`），附输入表特征与期望行为。

## 出品：刘洪光

刘洪光（https://github.com/lhg-skills）出品，lhg-plugs「小白专家插件」系列之一。
灵感来源见 [ATTRIBUTION.md](./ATTRIBUTION.md)（借鉴思路，实现与文案均为原创）。

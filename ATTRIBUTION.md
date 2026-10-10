# 灵感来源与致谢（Attribution）

本插件的**方法论灵感**来自以下项目，**所有实现代码、检测规则与文案均为原创**，未复制任何第三方的原文案或代码。

| 项目 | 作者 / 组织 | 许可（2026-10-11 核实） | 链接 | 借鉴了什么思路 |
|---|---|---|---|---|
| xlsx skill（官方文档技能） | Anthropic | **Proprietary 专有许可**（源码可看、不可复制/衍生/分发） | https://github.com/anthropics/skills/tree/main/skills/xlsx | 仅借鉴"按场景路由（读 / 建 / 分析 / 重算）划分工作流"的高层思路；**该 skill 的原文案、提示词、代码一律未复制** |
| claude-office-skills（xlsx 技能表思路的传播者） | 社区整理 | 见上（底层为上述专有 skill） | https://github.com/claude-office-skills/skills | 仅借鉴"用技能表把表格操作分类编目"的组织思路；文案与实现均为原创 |
| pandas | pandas 开发团队 | BSD-3-Clause | https://pandas.pydata.org | "读入→清洗→透视→输出"的数据处理操作模式（本插件的 skill 方法论按此模式组织，文案原创） |
| openpyxl | openpyxl 团队 | MIT | https://openpyxl.readthedocs.io | "保留公式与格式、最小改动编辑工作簿"的操作原则；本插件**不内置** openpyxl 依赖，审计脚本用标准库 zipfile+XML 解析 xlsx |

## 声明

1. **借鉴思路，实现与文案均为原创**：以上项目的具体文案、提示词原文、代码实现均未被复制。本插件的 skill 方法论文案、审计规则、命令流程均为独立撰写。特别说明：Anthropic 官方 xlsx skill 为专有许可，本插件与其无任何代码或文案上的派生关系。
2. **许可合规**：pandas（BSD-3）与 openpyxl（MIT）均为宽松开源许可；本插件审计脚本仅使用 Python 标准库，未捆绑任何第三方包。
3. **商标与归属**：各项目名称与作者署名归其各自所有者所有。

## 本插件自身的许可

本插件原创部分采用 MIT 许可（见 `LICENSE` 文件），版权所有：刘洪光（https://github.com/lhg-skills）。

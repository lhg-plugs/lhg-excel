#!/usr/bin/env python3
"""生成 lhg-excel 插件的 fixtures：好/坏 xlsx 与好/坏 opslog。

只用标准库（zipfile）手搓最小合法 xlsx，不依赖 openpyxl。
用法：python3 gen_fixtures.py（在 fixtures/ 目录下运行）
"""

import json
import os
import zipfile
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def col_letter(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def write_xlsx(path, sheets):
    """sheets: [(name, rows)]；cell 为 ("s",文本)/("n",数字)/("f",公式,缓存值)。"""
    strings = []
    sidx = {}

    def s_id(text):
        if text not in sidx:
            sidx[text] = len(strings)
            strings.append(text)
        return sidx[text]

    parts = {}
    for si, (name, rows) in enumerate(sheets, start=1):
        row_xml = []
        for ri, row in enumerate(rows, start=1):
            cells = []
            for ci, cell in enumerate(row):
                ref = "%s%d" % (col_letter(ci), ri)
                kind = cell[0]
                if kind == "s":
                    cells.append('<c r="%s" t="s"><v>%d</v></c>'
                                 % (ref, s_id(cell[1])))
                elif kind == "n":
                    v = cell[1]
                    cells.append('<c r="%s"><v>%s</v></c>' % (ref, v))
                elif kind == "f":
                    formula, cached = cell[1], cell[2]
                    if isinstance(cached, str) and cached.startswith("#"):
                        cells.append('<c r="%s" t="e"><f>%s</f><v>%s</v></c>'
                                     % (ref, escape(formula), escape(cached)))
                    else:
                        cells.append('<c r="%s"><f>%s</f><v>%s</v></c>'
                                     % (ref, escape(formula), cached))
            row_xml.append('<row r="%d">%s</row>' % (ri, "".join(cells)))
        parts["xl/worksheets/sheet%d.xml" % si] = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="%s"><sheetData>%s</sheetData></worksheet>'
            % (NS, "".join(row_xml)))

    ss = "".join("<si><t>%s</t></si>" % escape(t) for t in strings)
    parts["xl/sharedStrings.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sst xmlns="%s" count="%d" uniqueCount="%d">%s</sst>'
        % (NS, len(strings), len(strings), ss))

    sheets_xml = "".join(
        '<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (escape(n), i, i)
        for i, (n, _) in enumerate(sheets, start=1))
    parts["xl/workbook.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="%s" xmlns:r="%s"><sheets>%s</sheets></workbook>'
        % (NS, RNS, sheets_xml))
    parts["xl/_rels/workbook.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>'
            % (i, i) for i in range(1, len(sheets) + 1))
        + '</Relationships>')
    parts["xl/styles.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<styleSheet xmlns="%s"><fonts count="1"><font><sz val="11"/>'
        '<name val="Calibri"/></font></fonts><fills count="1">'
        '<fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
        '</cellStyleXfs><cellXfs count="1">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '</cellXfs></styleSheet>' % NS)
    parts["_rels/.rels"] = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>')
    parts["[Content_Types].xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        + "".join(
            '<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            % i for i in range(1, len(sheets) + 1))
        + '</Types>')

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in parts.items():
            zf.writestr(name, data.encode("utf-8"))
    print("wrote", path)


S = lambda t: ("s", t)
N = lambda v: ("n", v)
F = lambda f, v: ("f", f, v)

HEADER = [S("订单号"), S("日期"), S("产品"), S("数量"), S("单价"), S("金额"), S("备注")]

# 坏表埋点：
#  - 第3行与第2行整行重复           → DATA-DUP-001
#  - 备注列 7/7 空                  → DATA-NULL-001
#  - 数量列混入"待定"文本            → DATA-TYPE-001
#  - F8 的 SUM(F2:F6) 缓存 99999（真值 2590）→ DATA-FORM-001
#  - F7 为 #DIV/0!                  → DATA-ERR-001
BAD_ROWS = [
    HEADER,
    [S("ORD001"), S("2026-01-05"), S("A产品"), N(10), N(99.5), F("D2*E2", 995.0), S("")],
    [S("ORD001"), S("2026-01-05"), S("A产品"), N(10), N(99.5), F("D3*E3", 995.0), S("")],
    [S("ORD002"), S("2026-01-06"), S("B产品"), S("待定"), N(50), F("D4*E4", 0), S("")],
    [S("ORD003"), S("2026-01-07"), S("A产品"), N(5), N(100), F("D5*E5", 500), S("")],
    [S("ORD004"), S("2026-01-08"), S("C产品"), N(4), N(25), F("D6*E6", 100), S("")],
    [S("ORD005"), S("2026-01-09"), S("B产品"), N(10), N(0), F("D7/E7", "#DIV/0!"), S("")],
    [S("合计"), S(""), S(""), S(""), S(""), F("SUM(F2:F6)", 99999), S("")],
]

GOOD_HEADER = [S("订单号"), S("日期"), S("产品"), S("数量"), S("单价"), S("金额")]
GOOD_ROWS = [
    GOOD_HEADER,
    [S("ORD001"), S("2026-01-05"), S("A产品"), N(10), N(99.5), F("D2*E2", 995.0)],
    [S("ORD002"), S("2026-01-06"), S("B产品"), N(3), N(50), F("D3*E3", 150)],
    [S("ORD003"), S("2026-01-07"), S("A产品"), N(5), N(100), F("D4*E4", 500)],
    [S("合计"), S(""), S(""), S(""), S(""), F("SUM(F2:F4)", 1645)],
]


def main():
    write_xlsx(os.path.join(HERE, "xlsx-bad", "data_bad.xlsx"), [("Sheet1", BAD_ROWS)])
    write_xlsx(os.path.join(HERE, "xlsx-good", "data_good.xlsx"), [("Sheet1", GOOD_ROWS)])

    # 坏 opslog：缺字段 + 改数无备份/备份不存在 + 无回滚脚本
    bad_dir = os.path.join(HERE, "log-bad")
    os.makedirs(bad_dir, exist_ok=True)
    bad_log = {"records": [
        {"ts": "2026-10-11T10:00:00+08:00", "op": "dedupe", "file": "data.xlsx",
         "before": "100 行", "after": "90 行"},  # 缺 detail、无 backup
        {"ts": "2026-10-11T10:05:00+08:00", "op": "fill_na", "file": "data.xlsx",
         "before": "空值 20 个", "after": "已填 0", "detail": "用户确认空即 0",
         "backup": ".bak/not-exist.xlsx"},  # 备份文件不存在
    ]}
    with open(os.path.join(bad_dir, "opslog.json"), "w", encoding="utf-8") as fh:
        json.dump(bad_log, fh, ensure_ascii=False, indent=2)

    # 好 opslog：字段齐全 + 备份存在 + rollback.sh 可用
    good_dir = os.path.join(HERE, "log-good")
    os.makedirs(os.path.join(good_dir, ".bak"), exist_ok=True)
    open(os.path.join(good_dir, ".bak", "data.xlsx.bak-20261011-120000.xlsx"), "w").write("fake-backup")
    good_log = {"records": [
        {"ts": "2026-10-11T12:00:00+08:00", "op": "backup", "file": "data.xlsx",
         "before": "原文件", "after": "已备份",
         "detail": "hook 自动备份", "backup": ".bak/data.xlsx.bak-20261011-120000.xlsx",
         "reversible": True},
        {"ts": "2026-10-11T12:01:00+08:00", "op": "dedupe", "file": "data.xlsx",
         "sheet": "Sheet1", "before": "100 行", "after": "97 行",
         "detail": "删除 3 行整行重复，保留首次出现",
         "backup": ".bak/data.xlsx.bak-20261011-120000.xlsx", "reversible": True},
    ]}
    with open(os.path.join(good_dir, "opslog.json"), "w", encoding="utf-8") as fh:
        json.dump(good_log, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(good_dir, "rollback.sh"), "w", encoding="utf-8") as fh:
        fh.write('#!/bin/bash\nset -euo pipefail\n'
                 'cp ".bak/data.xlsx.bak-20261011-120000.xlsx" "data.xlsx"\n'
                 'echo "已回滚"\n')
    print("wrote log fixtures")


if __name__ == "__main__":
    main()

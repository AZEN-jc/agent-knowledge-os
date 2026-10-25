"""报告导出：JSON 与 PDF（Phase 5.7）。

## 铁律：导出的内容不新增任何判断

报告里的每个字都必须是 API 已经断言过的东西的复述 —— 命盘、事实、
证据链、强度算式、审查结论、指纹。PDF 不是「另一份分析」，是同一份
分析的另一种排版。任何在导出层新写的断语都是绕过契约层的第二条出口：
它不经过规则匹配、不经过 Critic、不出现在 API 响应里，用户却会以为
它和证据链同级。

本模块因此只做两件事：**组报**（把服务层已有的响应拼成报告结构）与
**排版**（把报告结构画成 PDF）。没有第三种函数。

PDF 用 reportlab 的 CID 字体 STSong-Light 渲染中文 —— 不随包裹发
字体文件（一个几 MB 的 ttf 进运行时依赖，只为了四个标题），CID 字体
的度量内置于 reportlab，中文显示由阅读器侧的同名字体承担。
"""

from __future__ import annotations

import io
import json
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas as pdf_canvas

#: 中文字体。注册一次即可；CID 字体按名字引用，度量内置于 reportlab。
_CJK_FONT = "STSong-Light"
pdfmetrics.registerFont(UnicodeCIDFont(_CJK_FONT))

#: 报告 JSON 的格式版本。报告结构变更时升它 —— 消费者（下载工具、
#: 归档脚本）靠它判断要不要重新解析，而不是靠猜。
REPORT_FORMAT_VERSION = 1

_PAGE_WIDTH, _PAGE_HEIGHT = A4
_MARGIN = 56
_BOTTOM = 64
_LINE_HEIGHT = 15


def _jsonable(value: Any) -> Any:
    """服务层的数据结构含 tuple（Pillar.hidden_stems、dayun 空元组等），
    JSON 序列化一趟才是**线上形状**（数组）。

    报告要与 API 响应逐字段一致（测试钉住），就不能停在 Python 对象形状
    —— FastAPI 在网关侧做这层转换，组报层自己做。``ensure_ascii=False``
    与 :func:`report_json` 一致；遇到不可序列化的对象会大声抛错，不静默
    吞成字符串。
    """
    return json.loads(json.dumps(value, ensure_ascii=False))


def build_report(
    service: Any,
    birth_data: dict[str, Any],
    topics: list[str] | tuple[str, ...],
    *,
    true_solar_time: bool = False,
) -> dict[str, Any]:
    """组报：一次多主题分析的完整快照。

    与 ``/api/analyze/multi`` 的响应**逐字段一致**（测试钉住）——
    报告不是新分析，是那次分析的结构化存档。``birth`` 是请求侧的
    出生信息原样带回（缺的字段带引擎默认值），让报告自含复算输入。
    """
    multi = service.analyze_multi(
        birth_data, topics, true_solar_time=true_solar_time
    )
    return _jsonable({
        "format_version": REPORT_FORMAT_VERSION,
        "birth": multi.chart["birth"],
        "chart": multi.chart,
        "topics": list(multi.topics),
        "results": multi.to_dict()["results"],
        "succeeded": len(multi.succeeded),
        "failed": len(multi.failed),
    })


def report_json(report: dict[str, Any]) -> bytes:
    """报告的 JSON 序列化。

    ``ensure_ascii=False``：报告是给人看也给人归档的，转义成
    ``\\u7532\\u5b50`` 的中文在 diff 里不可读，等于把可审读性换取了
    一点点的编码安全 —— 而 UTF-8 JSON 本身没有编码问题。
    """
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False)
    return (text + "\n").encode("utf-8")


def _wrap(text: str, width: int) -> list[str]:
    """按显示宽度粗折行（中文按 1 字、ASCII 按 0.5 字估）。

    不做精确字体度量：CID 字体的宽度查询要读嵌入度量表，为一个折行
    函数引入它不划算。估宽的代价是偶发的一两字误差，观感可接受。
    """
    lines: list[str] = []
    current = ""
    used = 0.0
    for char in text:
        char_width = 1.0 if ord(char) > 0x2E80 else 0.5
        if used + char_width > width and current:
            lines.append(current)
            current = ""
            used = 0.0
        current += char
        used += char_width
    if current:
        lines.append(current)
    return lines


class _RecordingCanvas:
    """测试替身：记录 drawString 的文本，不产生 PDF。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def setFont(self, name: str, size: int) -> None:
        pass

    def drawString(self, x: float, y: float, text: str) -> None:
        self.calls.append(text)

    def showPage(self) -> None:
        pass

    def save(self) -> None:
        pass


def _draw_report(target: Any, report: dict[str, Any]) -> None:
    """把报告结构画到 canvas 上。``target`` 是 canvas 或测试替身。"""
    y = _PAGE_HEIGHT - _MARGIN

    def emit(text: str, *, font_size: int = 10, bold: bool = False) -> None:
        nonlocal y
        for line in _wrap(text, 46):
            target.setFont(_CJK_FONT, font_size)  # type: ignore[attr-defined]
            target.drawString(_MARGIN, y, line)
            y -= _LINE_HEIGHT
            if y < _BOTTOM:
                target.showPage()
                y = _PAGE_HEIGHT - _MARGIN

    chart = report["chart"]
    emit("命理分析报告", font_size=16, bold=True)
    emit("")
    birth = report["birth"]
    emit(
        f"出生：{birth['year']}-{birth['month']:02d}-{birth['day']:02d} "
        f"{birth['hour']:02d}:{birth['minute']:02d}（{birth['timezone']}）"
    )
    emit(
        f"日主 {chart['day_master']}　·　{chart['provider']}　·　"
        f"算法 {chart['algorithm_version']}"
    )
    census = chart.get("elements") or {}
    if census.get("count"):
        counts = "　".join(f"{e}{n}" for e, n in census["count"].items())
        line = f"五行计数　{counts}"
        if census.get("missing"):
            line += f"　·　缺：{'、'.join(census['missing'])}"
        if census.get("dominant"):
            line += f"　·　偏旺：{'、'.join(census['dominant'])}"
        emit(line)
    emit("四柱：" + "　".join(
        f"{pillar['heavenly_stem']}{pillar['earthly_branch']}"
        for pillar in chart["pillars"]
    ))
    emit("")

    for result in report["results"]:
        if not result["ok"]:
            emit(f"主题「{result['topic_name']}」分析失败：{result['error']}")
            emit("")
            continue
        analysis = result["analysis"]["analysis"]
        evidence = analysis["evidence"]
        emit(f"── 主题「{evidence['topic_name']}」"
             f"（覆盖状态：{evidence['status']}）", font_size=12, bold=True)
        emit(evidence["coverage_note"])
        emit(
            f"证据强度 {evidence['strength']:.2f}"
            f"（支持 {evidence['strength_breakdown']['supporting_rules']} 条）"
        )
        if evidence.get("untraced_rules"):
            emit(f"证据链断环：{'、'.join(evidence['untraced_rules'])}")
        if evidence.get("unreviewed_rules"):
            emit(f"含未校核规则：{'、'.join(evidence['unreviewed_rules'])}")

        for link in evidence["chain"]:
            emit(f"◆ {link['conclusion']}　[{link['rule_id']}]"
                 f"（{link['confidence']} / {link['source_tier']} / {link['review_status']}）")
            for condition in link.get("conditions") or []:
                sources = "、".join(condition.get("sources") or [])
                emit(
                    f"　条件 {condition['key']}：要求 {condition['expected']}，"
                    f"实际 {condition['actual']}（出处：{sources}）"
                )
            if link.get("urn"):
                emit(f"　URN：{link['urn']}")
            citation = link.get("citation")
            if citation:
                chapter = f"　·　{citation['chapter']}" if citation.get("chapter") else ""
                emit(f"　出处：{citation['book']}　·　{citation['edition']}{chapter}")
                if citation.get("original_text"):
                    emit(f"　原文：「{citation['original_text']}」")
                if citation.get("url"):
                    emit(f"　链接：{citation['url']}")
        emit("")

        critique = result["analysis"]["critique"]
        verdict = "审查通过" if critique["passed"] else "审查未通过"
        emit(f"审查：{verdict}"
             + ("" if critique["passed"] else f"：{'；'.join(critique['issues'])}"))
        draft = analysis["draft"]
        emit(
            f"草稿来源：{draft['source']}"
            + (f"（降级原因：{draft['degraded_reason']}）" if draft.get("degraded_reason") else "")
        )
        emit(f"契约指纹：{draft['contract_fingerprint']}　·　"
             f"规则库指纹：{draft['rule_fingerprint']}")
        emit("")

    emit("信号是结构描述（命盘里出现了什么），不是预测；证据强度是证据等级，"
         "不是事件概率。")


def render_pdf(report: dict[str, Any]) -> bytes:
    """报告 → PDF 字节。"""
    buffer = io.BytesIO()
    target = pdf_canvas.Canvas(buffer, pagesize=A4)
    _draw_report(target, report)
    target.save()
    return buffer.getvalue()

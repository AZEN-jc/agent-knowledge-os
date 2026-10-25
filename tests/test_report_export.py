"""报告导出：组报与排版的契约（Phase 5.7）。

## 这个文件守什么

两条铁律：

1. **报告不新增判断**。导出层的每个字都必须是 API 已经断言过的东西的
   复述。绕过契约层新写一句「事业有成」，它不经过规则匹配、不经过
   Critic、不出现在 API 响应里，用户却会以为它和证据链同级。
2. **JSON 与 API 响应逐字段一致**。报告是那次分析的结构化存档，
   不是另一次分析 —— 同一次输入，报告与接口返回的命盘、证据链、
   审查结论必须逐字段相同。

PDF 的渲染用记录型 canvas 替身验证：断言画出来的文本都来自报告结构
（URN、逐字原文、强度算式都在），不需要解析 PDF 字节。
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from api.server import app
from runtime.mingli_service import MingLiService
from runtime.report import (
    REPORT_FORMAT_VERSION,
    _draw_report,
    _jsonable,
    _RecordingCanvas,
    build_report,
    render_pdf,
    report_json,
)

client = TestClient(app)

#: 会命中典籍层规则的命盘（日柱甲子 + 时柱甲子）——报告里要有带 URN 与
#: 逐字原文的一环，否则出处相关断言全部空转。选型理由同
#: tests/test_citation_allowlist.py。
BIRTH = {"year": 1990, "month": 2, "day": 28, "hour": 0}
TOPICS = ["命局", "事业"]


def _service() -> MingLiService:
    return MingLiService()


# ── 组报：与 API 响应逐字段一致 ───────────────────────────────────────


def _assert_api_subset(api_value: object, report_value: object, path: str = "") -> None:
    """API 响应的每个字段，报告里都有且相等。

    方向是 **API ⊆ 报告**：报告是服务层的完整输出，API 是它的过滤视图
    （``EvidenceResponse`` 的 ``extra="ignore"`` 裁掉 sources / rules /
    rule_provenance 等服务层明细）。报告比 API 多的是那些明细，不是新
    判断；少任何一个 API 字段才是 diverge —— 用户下载的报告和界面上
    看到的对不上，是导出层最不能犯的错。
    """
    if isinstance(api_value, dict):
        assert isinstance(report_value, dict), f"{path}: 报告侧不是对象"
        for key, value in api_value.items():
            assert key in report_value, f"{path}.{key}: API 有、报告没有"
            _assert_api_subset(value, report_value[key], f"{path}.{key}")
    elif isinstance(api_value, list):
        assert isinstance(report_value, list), f"{path}: 报告侧不是列表"
        assert len(api_value) == len(report_value), f"{path}: 长度不同"
        for index, (api_item, report_item) in enumerate(zip(api_value, report_value)):
            _assert_api_subset(api_item, report_item, f"{path}[{index}]")
    else:
        assert api_value == report_value, f"{path}: {api_value!r} != {report_value!r}"


def test_report_matches_the_api_responses_field_by_field():
    service = _service()
    report = build_report(service, dict(BIRTH), TOPICS)

    chart = client.post("/api/chart", json=dict(BIRTH)).json()
    multi = client.post("/api/analyze/multi", json={**BIRTH, "topics": TOPICS}).json()

    # chart 端点不过滤（无 response_model），两边全等。
    assert report["chart"] == chart
    assert report["birth"] == chart["birth"]
    # results 走过滤视图：API 的每个字段在报告里都有且相等。
    _assert_api_subset(multi["results"], report["results"], "results")
    assert report["topics"] == multi["topics"]
    assert report["succeeded"] == multi["succeeded"] == 2
    assert report["failed"] == multi["failed"] == 0
    assert report["format_version"] == REPORT_FORMAT_VERSION


def test_report_adds_nothing_beyond_the_service_output():
    """反向：报告不新增服务层没有的内容（「不新增判断」的可执行形式）。

    组报 = 服务层输出 + 五个信封字段。除了信封，报告与服务层序列化
    逐字段相同 —— 想在导出层加一句自己的话，这条红。
    """
    service = _service()
    multi = service.analyze_multi(dict(BIRTH), TOPICS)
    report = build_report(service, dict(BIRTH), TOPICS)

    envelope = {"format_version", "birth", "chart", "topics", "results", "succeeded", "failed"}
    assert set(report) == envelope
    assert report["chart"] == _jsonable(multi.chart)
    assert report["results"] == _jsonable(multi.to_dict()["results"])


def test_report_has_no_timestamp_or_other_nonreproducible_field():
    """报告可复算：同一输入两次组报，字节级相同。

    不放 generated_at 之类的时间戳 —— 它让同一份输入产出不同的报告，
    而报告的 provenance 已经由算法版本与两个指纹承担，时间戳不增加
    任何可核验性。
    """
    first = build_report(_service(), dict(BIRTH), TOPICS)
    second = build_report(_service(), dict(BIRTH), TOPICS)

    assert report_json(first) == report_json(second)


def test_report_carries_failed_topics_with_reasons():
    """失败主题进报告，且带原因 —— 报告不能只报成功的部分。

    纯空格主题必然失败（AnalystAgent 的入参校验），手法同
    tests/test_concurrent_analysis.py 的故障隔离测试。
    """
    service = _service()
    report = build_report(service, dict(BIRTH), ["命局", "   "])

    by_topic = {result["topic"]: result for result in report["results"]}
    assert by_topic["命局"]["ok"] is True
    assert by_topic["   "]["ok"] is False
    assert by_topic["   "]["error"]
    assert by_topic["   "]["analysis"] is None


# ── JSON 导出 ─────────────────────────────────────────────────────────


def test_report_json_is_utf8_readable_and_round_trips():
    report = build_report(_service(), dict(BIRTH), TOPICS)
    payload = report_json(report)

    text = payload.decode("utf-8")
    assert "甲子" in text  # ensure_ascii=False：中文可读，不是 \u 转义
    assert json.loads(text) == report


def test_report_json_contains_the_classical_citation():
    """典籍层那一环的 URN 与逐字原文必须在 JSON 里。"""
    report = build_report(_service(), dict(BIRTH), TOPICS)
    payload = json.loads(report_json(report))

    links = [
        link
        for result in payload["results"] if result["ok"]
        for link in result["analysis"]["analysis"]["evidence"]["chain"]
    ]
    classical = [link for link in links if link["urn"]]
    assert classical, "这张盘应命中至少一条典籍层规则"
    urn = classical[0]["urn"]
    assert urn.startswith("urn:divination:")
    assert urn in report_json(report).decode("utf-8")
    citation = classical[0]["citation"]
    assert citation["original_text"]
    assert citation["url"].startswith("http")


# ── PDF 渲染 ──────────────────────────────────────────────────────────


def test_pdf_starts_with_the_header_and_has_pages():
    report = build_report(_service(), dict(BIRTH), TOPICS)
    payload = render_pdf(report)

    assert payload[:5] == b"%PDF-"
    assert len(payload) > 2000  # 有实际内容，不是空壳


def test_pdf_draws_only_strings_from_the_report():
    """画出来的每一行文本，都必须是报告结构里有的内容的复述。

    验证方式：记录型 canvas 收下所有 drawString，报告结构里的关键片段
    （URN、逐字原文、强度算式、审查结论、指纹）都必须出现；同时
    渲染函数只读 report 字典 —— 这一条由代码结构保证（_draw_report
    除了 report 不碰第二个数据源），测试兜底关键片段在场。
    """
    report = build_report(_service(), dict(BIRTH), TOPICS)
    recorder = _RecordingCanvas()
    _draw_report(recorder, report)
    drawn = "\n".join(recorder.calls)

    assert "命理分析报告" in drawn
    assert "1990-02-28" in drawn                       # 出生信息
    assert "sxtwl-2.0.7-bazi-v2" in drawn              # 算法版本
    assert "五行计数" in drawn                          # 普查行
    assert "证据强度" in drawn                          # 强度算式
    assert "审查" in drawn                              # Critic 结论
    assert "urn:divination:" in drawn                   # 规范引用
    assert "原文：" in drawn                             # 逐字原文
    assert "不是预测" in drawn                          # 立场声明随报告走
    # 指纹：报告能回答「哪版契约、哪版规则库」。
    assert "契约指纹" in drawn
    # 人话层（Phase 6.1）：报告是给人读的，条件要先有一句普通中文，
    # 字段级依据跟在后面。
    assert "依据 " in drawn
    assert "出现在天干上" in drawn or "四柱天干与四支本气里没有" in drawn


def test_pdf_reports_failed_topics_instead_of_hiding_them():
    report = build_report(_service(), dict(BIRTH), ["命局", "   "])
    recorder = _RecordingCanvas()
    _draw_report(recorder, report)
    drawn = "\n".join(recorder.calls)

    assert "分析失败" in drawn


def test_pdf_wraps_long_lines_instead_of_running_off_the_page():
    """长行折行：A4 宽度约 46 个全角字，超宽行必须断开。"""
    from runtime.report import _wrap

    long_line = "原文：「" + "命" * 80 + "」"
    lines = _wrap(long_line, 46)

    assert len(lines) > 1
    assert all(len(line) <= 46 for line in lines)
    assert "".join(lines) == long_line  # 折行不丢字

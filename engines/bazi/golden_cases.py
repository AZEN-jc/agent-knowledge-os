"""Phase 1：golden cases。

来源口径（重要）：这里的预期值**不是**从某个「权威命盘数据库」抄来的 ——
离线环境无法核验那种来源，凭记忆填写就等于编造，违背本项目的核心原则。

预期值的来源是 **sxtwl 2.0.7 与 lunar-python 1.4.8 两套独立实现交叉确认**：
两套实现在这些时刻给出完全相同的四柱。这个声明不是注释，而是被
``tests/test_bazi_golden.py`` 在运行时重新校验的 —— 如果哪天两套实现分叉，
测试会直接变红，而不是悄悄带着一个失效的来源标注继续跑。

覆盖的边界：立春时刻前后、夏令时年份的换月、晚子时、早子时、大雪、
跨年小寒、闰月、现代日期、远端年份。
"""

from __future__ import annotations

from engines.bazi.golden import GoldenCase
from engines.bazi.models import BirthInput

DUAL_SOURCE = "sxtwl 2.0.7 与 lunar-python 1.4.8 双实现交叉确认（2026-10-09）"

_PILLAR_NAMES = ("year", "month", "day", "hour")


def _expected(*pairs: str) -> dict[str, object]:
    """把四个干支串转成 ``compare_chart`` 认识的 pillars 结构。"""
    return {
        "pillars": [
            {"name": name, "heavenly_stem": pair[0], "earthly_branch": pair[1]}
            for name, pair in zip(_PILLAR_NAMES, pairs, strict=True)
        ]
    }


GOLDEN_CASES: tuple[GoldenCase, ...] = (
    GoldenCase(
        case_id="lichun-1990-before",
        birth=BirthInput(1990, 2, 4, 9, 0),
        expected=_expected("己巳", "丁丑", "庚子", "辛巳"),
        source=DUAL_SOURCE,
        note="立春 1990-02-04 10:14 之前，年柱仍属己巳；按日分界的实现会误判为庚午",
    ),
    GoldenCase(
        case_id="lichun-1990-after",
        birth=BirthInput(1990, 2, 4, 10, 15),
        expected=_expected("庚午", "戊寅", "庚子", "辛巳"),
        source=DUAL_SOURCE,
        note="立春时刻之后一分钟，年柱与月柱同时进入庚午年、寅月",
    ),
    GoldenCase(
        case_id="mangzhong-1990-dst",
        birth=BirthInput(1990, 6, 6, 7, 47),
        expected=_expected("庚午", "壬午", "壬寅", "甲辰"),
        source=DUAL_SOURCE,
        note="1990 年 6 月行夏令时；芒种在标准时 06:46，当地钟面 07:46 换月",
    ),
    GoldenCase(
        case_id="late-zi-1990",
        birth=BirthInput(1990, 6, 15, 23, 30),
        expected=_expected("庚午", "壬午", "辛亥", "庚子"),
        source=DUAL_SOURCE,
        note="晚子时默认口径：日柱仍属当日，时干按次日日干推",
    ),
    GoldenCase(
        case_id="early-zi-1990",
        birth=BirthInput(1990, 6, 16, 0, 30),
        expected=_expected("庚午", "壬午", "壬子", "庚子"),
        source=DUAL_SOURCE,
        note="早子时：日柱已进次日，与时柱同为子",
    ),
    GoldenCase(
        case_id="daxue-1990",
        birth=BirthInput(1990, 12, 7, 17, 15),
        expected=_expected("庚午", "戊子", "丙午", "丁酉"),
        source=DUAL_SOURCE,
        note="大雪 1990-12-07 17:14 之后一分钟，亥月转子月",
    ),
    GoldenCase(
        case_id="xiaohan-1991",
        birth=BirthInput(1991, 1, 6, 4, 29),
        expected=_expected("庚午", "己丑", "丙子", "庚寅"),
        source=DUAL_SOURCE,
        note="小寒 1991-01-06 04:28 之后一分钟；公历已跨年，干支年仍是庚午",
    ),
    GoldenCase(
        case_id="leap-month-2020",
        birth=BirthInput(2020, 6, 1, 12, 0),
        expected=_expected("庚子", "辛巳", "乙亥", "壬午"),
        source=DUAL_SOURCE,
        note="2020 闰四月期间；月柱只跟节气走，不受闰月影响",
    ),
    GoldenCase(
        case_id="lichun-2024",
        birth=BirthInput(2024, 2, 4, 17, 0),
        expected=_expected("甲辰", "丙寅", "戊戌", "辛酉"),
        source=DUAL_SOURCE,
        note="立春 2024-02-04 16:26 之后，进入甲辰年",
    ),
    GoldenCase(
        case_id="year-2100",
        birth=BirthInput(2100, 6, 15, 12, 0),
        expected=_expected("庚申", "壬午", "戊子", "戊午"),
        source=DUAL_SOURCE,
        note="远端年份，用于确认历法库不只在近几十年可用",
    ),
)

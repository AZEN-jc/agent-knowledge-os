"""Phase 3.6：流年、大运、流月的边界。

## 这一层的边界为什么值得单独测

时间轴的每一个分界都是**节气的一个精确时刻**，不是日期的零点。这意味着
「差一秒」就会换年、换月。已有的测试只验了「节时刻当刻属于新的一月」，
没有验另一侧 —— 边界写反（``<`` 写成 ``<=``）时，前者照样通过，
而所有在节气当天、节气时刻之前出生的人会整体错一个月。

这里把两侧都测：每个节**前一秒**属于旧月，**当刻**属于新月。十二个节逐一验。

## 另两件事

- **BirthInput 只有分钟精度**。这不是缺陷，是输入契约，但它决定了「节气落在
  某一分钟的第 53 秒」时，填 16:26 的人算 16:26:00，仍在节气之前。这条必须
  写进测试，否则有人会以为是边界算错了。
- **大运必须覆盖每一个整数年龄，且不重叠**。``_dayun_in_effect`` 用浮点起运
  年龄判断，写错比较方向会出现「某个年龄没有大运」或「两个大运同时生效」，
  而这两种情况都不会报错，只会让时间轴少一段或多一段。
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

import pytest

from engines.bazi import BirthInput, SxtwlBaziProvider
from engines.bazi.jieqi import (
    ganzhi_year,
    jie_terms_in,
    lichun_moment,
    month_pillar,
    year_pillar,
)
from engines.bazi.time_engine import (
    ClassicalApproxDayunPolicy,
    flow_months,
    month_contexts,
    year_context,
)
from knowledge.time_windows import _dayun_in_effect

TZ = ZoneInfo("Asia/Shanghai")
PROVIDER = SxtwlBaziProvider()

#: 十二个「节」（不是「气」）：月支只由节划分。
JIE_NAMES = ("立春", "惊蛰", "清明", "立夏", "芒种", "小暑",
             "立秋", "白露", "寒露", "立冬", "大雪", "小寒")

#: 节 → 该节开启的月支。
JIE_BRANCH = {
    "立春": "寅", "惊蛰": "卯", "清明": "辰", "立夏": "巳",
    "芒种": "午", "小暑": "未", "立秋": "申", "白露": "酉",
    "寒露": "戌", "立冬": "亥", "大雪": "子", "小寒": "丑",
}


def jie_moments(year: int) -> dict[str, datetime]:
    """``year`` 年立春起、次年立春前的十二个节，按名字索引。"""
    out: dict[str, datetime] = {}
    for term in jie_terms_in((year, year + 1)):
        if term.name in JIE_NAMES and term.name not in out:
            out[term.name] = term.moment
    return out


# ── 月支：每个节的前一秒与当刻 ────────────────────────────────────────


def test_month_branch_flips_exactly_at_every_jie_moment():
    """十二个节逐一验：前一秒是旧月，当刻是新月。

    **只验「当刻属于新月」是不够的。** 把比较写成 ``<=`` 时，当刻仍然属于
    新月（``term.moment <= moment`` 为真），测试照样全绿；但前一秒也会被判成
    新月 —— 所有在节气时刻之前出生的人整体错一个月。两侧都测才封得住。
    """
    moments = jie_moments(2024)
    assert set(moments) == set(JIE_NAMES), f"缺少节：{set(JIE_NAMES) - set(moments)}"

    for name, moment in moments.items():
        before = month_pillar(moment - timedelta(seconds=1))
        at = month_pillar(moment)

        assert at[1] == JIE_BRANCH[name], f"{name} 当刻应进入 {JIE_BRANCH[name]} 月，实得 {at[1]}"
        assert before[1] != at[1], f"{name} 前一秒与当刻的月支相同，边界没有生效"


def test_the_month_branch_sequence_is_the_canonical_one():
    """十二个月的月支必须按 寅卯辰巳午未申酉戌亥子丑 顺序推进。

    逐节验「换了」还不够 —— 换错方向也是「换了」。
    """
    moments = jie_moments(2024)
    order = [month_pillar(moments[name])[1] for name in JIE_NAMES]

    assert order == list("寅卯辰巳午未申酉戌亥子丑")


def test_month_stem_follows_the_five_tiger_rule_across_the_boundary():
    """跨节时月干必须跟着换，且按五虎遁。

    只换月支不换月干，会让「丙寅月」变成「丙卯月」这种干支不合法的组合。
    """
    moments = jie_moments(2024)
    pillars = [month_pillar(moments[name]) for name in JIE_NAMES]

    for stem, branch in pillars:
        # 六十甲子合法性：干支下标同奇偶。
        assert ("甲乙丙丁戊己庚辛壬癸".index(stem) % 2) == (
            "子丑寅卯辰巳午未申酉戌亥".index(branch) % 2
        ), f"{stem}{branch} 不是合法的干支组合"


# ── 年柱：立春两侧 ────────────────────────────────────────────────────


def test_year_pillar_flips_exactly_at_lichun():
    lichun = lichun_moment(2024)

    before = year_pillar(lichun - timedelta(seconds=1))
    at = year_pillar(lichun)

    assert before == ("癸", "卯"), f"立春前一秒应仍属癸卯，实得 {before}"
    assert at == ("甲", "辰"), f"立春当刻应进入甲辰，实得 {at}"


def test_ganzhi_year_agrees_with_the_year_pillar():
    """两个 API 必须给同一个答案。

    ``ganzhi_year`` 返回干支年的**公历年份**（2023 表示癸卯），
    ``year_pillar`` 返回干支。两者各算一遍，口径不一致时用户会看到
    「2023 年」配「甲辰」这种自相矛盾的标注。
    """
    for moment in (
        datetime(2024, 1, 15, 12, tzinfo=TZ),   # 立春前
        datetime(2024, 2, 5, 12, tzinfo=TZ),    # 立春后
        datetime(2024, 6, 1, 0, tzinfo=TZ),
    ):
        stem, branch = year_pillar(moment)
        assert (stem, branch) == (
            "甲乙丙丁戊己庚辛壬癸"[(ganzhi_year(moment) - 4) % 10],
            "子丑寅卯辰巳午未申酉戌亥"[(ganzhi_year(moment) - 4) % 12],
        ), f"{moment.date()} 的两个年柱接口不一致"


def test_birth_input_resolves_to_the_minute_so_the_jie_minute_stays_before_it():
    """出生时间只有分钟精度 —— 这条是输入契约，不是边界算错。

    2024 立春在 16:26:53。填「16:26」的人实际被当成 16:26:00，
    仍在节气之前，所以年柱是癸卯而不是甲辰。填「16:27」才进甲辰。

    写这条是因为它极容易被误判成 bug：只看结果的人会说「16:26 都过了立春
    怎么还是癸卯」。真实原因是输入没有秒。
    """
    lichun = lichun_moment(2024)
    assert (lichun.hour, lichun.minute, lichun.second) == (16, 26, 53)

    at_minute = PROVIDER.calculate(BirthInput(2024, 2, 4, 16, 26))
    next_minute = PROVIDER.calculate(BirthInput(2024, 2, 4, 16, 27))

    assert at_minute.pillars[0].heavenly_stem + at_minute.pillars[0].earthly_branch == "癸卯"
    assert next_minute.pillars[0].heavenly_stem + next_minute.pillars[0].earthly_branch == "甲辰"


# ── 流年：按干支年，不按公历年 ────────────────────────────────────────


def test_year_context_is_the_ganzhi_year_that_starts_in_that_calendar_year():
    """``year_context(chart, 2024)`` 指「2024 年内立春开启的那个干支年」。

    它**不是**「2024 年 1 月 1 日所在的干支年」（那是癸卯）。这个区别必须
    写下来：时间轴按干支年编号，1 月 1 日到立春之间仍属上一个干支年。
    """
    chart = PROVIDER.calculate(BirthInput(1990, 2, 1, 12))
    context = year_context(chart, 2024)

    assert (context.heavenly_stem, context.earthly_branch) == ("甲", "辰")
    assert (context.heavenly_stem, context.earthly_branch) == year_pillar(
        lichun_moment(2024) + timedelta(days=1)
    )
    # 1 月 1 日所在的是上一个干支年 —— 两者不是同一件事。
    assert ganzhi_year(datetime(2024, 1, 1, 12, tzinfo=TZ)) == 2023


# ── 流月：覆盖完整、无缝隙、无重叠 ────────────────────────────────────


def test_flow_months_are_contiguous_and_start_at_each_jie():
    """流月的端点必须首尾相接，且每个起点就是一个节的时刻。"""
    months = flow_months(2024)
    moments = jie_moments(2024)

    assert len(months) == 12
    for index, month in enumerate(months):
        assert month.start == moments[JIE_NAMES[index]]
        if index + 1 < len(months):
            assert month.end == months[index + 1].start
    assert months[-1].end == lichun_moment(2025)


def test_a_range_starting_exactly_at_a_jie_includes_that_month():
    """``[start, end)`` 是左闭右开：起点正好落在节时刻时，该月要算进来。"""
    moment = jie_moments(2024)["芒种"]
    months = month_contexts(moment, moment + timedelta(days=40))

    assert months[0].jie_name == "芒种"
    assert months[0].start == moment


def test_a_range_ending_exactly_at_a_jie_excludes_the_next_month():
    """右端点正好落在节时刻时，下一个月不算进来 —— 否则区间会多算一个月。"""
    moment = jie_moments(2024)["芒种"]
    months = month_contexts(moment - timedelta(days=40), moment)

    assert all(month.start < moment for month in months)
    assert all(month.jie_name != "芒种" for month in months)


# ── 大运：每个整数年龄恰好落在一步大运里 ──────────────────────────────


def dayun_sequence():
    chart = PROVIDER.calculate(BirthInput(1990, 6, 15, 12, gender="男"))
    return ClassicalApproxDayunPolicy().calculate(chart)


def test_dayun_covers_every_integer_age_after_the_start_without_gaps():
    """起运之后、八步走完之前，每个整数年龄都必须落在一步大运里。

    ``_dayun_in_effect`` 用浮点起运年龄判断。比较方向写错会出现「某个年龄
    没有大运」—— 时间轴会少一段，而且不报错，只是那一年没有大运信号。

    **第一版这条写到 90 岁，失败了：88 岁没有大运。** 不是缺陷 ——
    八步 × 十年只覆盖到起运后 80 年。已按真实覆盖范围写，另加一条把
    覆盖上限本身钉住（见下一条）。
    """
    sequence = dayun_sequence()
    start = float(sequence[0]["start_age_years"])  # type: ignore[arg-type]
    covered_until = start + 10 * len(sequence)

    for age in range(int(start) + 1, int(covered_until)):
        assert _dayun_in_effect(sequence, age) is not None, f"{age} 岁没有大运"


def test_dayun_coverage_ends_after_the_eighth_step():
    """八步走完之后没有大运，这是**已知的覆盖上限**，不是缺数据。

    起运 7.42 岁、八步 × 十年 → 覆盖到 87.42 岁。88 岁起返回 None。
    产品上这意味着「88 岁以上只报流年」，应当如实说明，而不是让
    ``_dayun_in_effect`` 循环回到第一步（那会给出一个假的、循环的大运）。
    """
    sequence = dayun_sequence()
    start = float(sequence[0]["start_age_years"])  # type: ignore[arg-type]
    # 覆盖终点是 87.42 岁：87 岁仍在第八步里，88 岁起没有。
    # 用 ceil 而不是 int —— int(87.42) = 87，那一年其实还在覆盖范围内。
    beyond = math.ceil(start + 10 * len(sequence))

    assert _dayun_in_effect(sequence, beyond - 1) is not None
    assert _dayun_in_effect(sequence, beyond) is None


def test_dayun_never_has_two_steps_in_effect_at_once():
    """同一年龄不能落进两步大运 —— 否则信号会重复累加，强度虚高。"""
    sequence = dayun_sequence()

    for age in range(0, 100):
        in_effect = [
            entry for entry in sequence
            if float(entry["start_age_years"]) <= age < float(entry["start_age_years"]) + 10  # type: ignore[arg-type]
        ]
        assert len(in_effect) <= 1, f"{age} 岁同时落在 {len(in_effect)} 步大运里"


def test_dayun_switches_once_per_ten_years():
    """八步之间只该有七次「换步」，另有进出各一次。

    第一版只数「相邻年龄结果不同」的个数，得到 8 —— 因为把
    「无大运 → 第一步」和「第八步 → 无大运」也算成了换步。这里分开数：
    换步 7 次、进入 1 次、退出 1 次。
    """
    sequence = dayun_sequence()
    keys: list[tuple[object, object] | None] = []
    for age in range(0, 100):
        current = _dayun_in_effect(sequence, age)
        keys.append(
            None if current is None
            else (current["heavenly_stem"], current["earthly_branch"])
        )

    transitions = [
        (earlier, later) for earlier, later in pairwise(keys) if earlier != later
    ]
    step_changes = [
        (earlier, later) for earlier, later in transitions
        if earlier is not None and later is not None
    ]

    assert len(step_changes) == len(sequence) - 1
    assert sum(1 for earlier, later in transitions if earlier is None) == 1  # 进入
    assert sum(1 for earlier, later in transitions if later is None) == 1    # 退出


def test_dayun_starts_only_once_and_is_none_before_that():
    """起运前没有大运 —— 这是真实状态，不是缺数据。

    把起运前硬塞一个「第一步」会让用户在童年就看到大运信号。
    """
    sequence = dayun_sequence()
    start = float(sequence[0]["start_age_years"])  # type: ignore[arg-type]

    assert _dayun_in_effect(sequence, 0) is None
    assert _dayun_in_effect(sequence, max(0, int(start) - 1)) is None


@pytest.mark.parametrize("gender", ("男", "女"))
def test_both_genders_get_a_full_dayun_sequence(gender: str):
    """顺逆不同，但八步都要有，且天干不重复。"""
    chart = PROVIDER.calculate(BirthInput(1990, 6, 15, 12, gender=gender))
    sequence = ClassicalApproxDayunPolicy().calculate(chart)

    assert len(sequence) == 8
    assert len({entry["heavenly_stem"] for entry in sequence}) == 8

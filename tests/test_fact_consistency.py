"""事实层的一致性审计：键名对得上之外，**值也必须真的来自它声称的来源**。

## 为什么已有测试不够

``test_structural_rules.py::test_fact_schema_and_extractor_stay_in_sync``
只回答「产出的键在不在词表里」。它不回答下面这些：

1. ``Fact.source`` 写着 ``chart.pillars.month.hidden_stems`` —— 这个路径真的
   存在吗？取值真的等于那条路径上的东西吗？证据链是给用户看「这条结论来自
   命盘哪一处」的，来源写错等于证据链在撒谎，而键名测试看不出来。
2. 词表里的键是否**每一张盘都产出**（除了结构上可能缺席的）。一个键若在
   任何命盘上都不产出，引用它的规则永远不会触发 —— 这比报错更糟，因为它
   静默地什么都不做。
3. 规则用到的条件键，是否每一张盘都能拿到值。静态校验只查「键在词表里」，
   查不出「词表里有、但没人产出」。

## 验证口径

不拿提取器的输出当预期。每条断言都回到 :class:`Chart` 的原始字段重新算：
``year_stem`` 必须等于 ``chart.pillars[0].heavenly_stem``，五行计数必须等于
「四干 + 四支本气」的手工清点。提取器写错时这些断言会红，而拿它自己的输出
对照自己的输出不会。
"""

from __future__ import annotations

import re

import pytest

from engines.bazi import BirthInput, SxtwlBaziProvider
from engines.bazi.ten_gods import ELEMENTS, POLARITY, TEN_GODS, ten_god
from knowledge.default_rules import default_registry
from knowledge.facts import (
    FACT_SCHEMA,
    Fact,
    extract_facts,
    group_facts,
    index_facts,
    resolve_source,
)

PROVIDER = SxtwlBaziProvider()

#: 审计用的命盘样本：跨年代、跨时辰、跨节气边界。样本不大（40 张）是因为
#: 每条断言都要手工复算，样本再大也只是重复同一种结构。
SAMPLE: tuple[BirthInput, ...] = tuple(
    BirthInput(year, month, day, hour)
    for year in (1950, 1976, 1990, 2003, 2024, 2035)
    for month, day, hour in ((1, 5, 0), (2, 4, 6), (6, 15, 12), (11, 7, 23))
)

#: 结构上可能缺席的键 —— 只有命盘确实存在该结构时才产出。
#: 这张表与 ``test_structural_rules.py`` 里的那份必须一致；不一致时下面
#: :func:`test_the_structurally_optional_set_is_the_same_everywhere` 会红。
STRUCTURALLY_OPTIONAL = frozenset({
    "has_relation",
    "repeated_branches",
    "ten_god_with_root",
    "ten_god_without_root",
    "dominant_elements",
    "missing_elements",
    "liunian_relations",
    "liunian_relation_pairs",
    "dayun_relations",
    "dayun_relation_pairs",
})

#: 由 :func:`knowledge.flow_facts.flow_facts` 产出的键，不是本命盘事实。
#: 它们不参与「每张盘都必须产出」的检查 —— 那是另一个产出方的责任，
#: 由 ``test_flow_fact_keys_are_declared_and_sourced`` 单独守。
FLOW_KEYS: frozenset[str] = frozenset(
    key for key in FACT_SCHEMA if key.startswith(("liunian_", "dayun_"))
)

#: ``Fact.source`` 允许出现的路径形态。``[*]`` 表示对四柱逐一成立。
#: 允许清单而不是「以 chart. 开头就行」：后者会让 ``chart.whatever`` 也通过。
SOURCE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"^chart\.day_master$",
        r"^chart\.pillars$",
        r"^chart\.relations$",
        r"^chart\.pillars\.(year|month|day|hour)$",
        r"^chart\.pillars\.(year|month|day|hour)\.hidden_stems$",
        r"^chart\.pillars\[\*\]\.(ten_god|hidden_stems|earthly_branch)$",
    )
)


def charts() -> list[object]:
    return [PROVIDER.calculate(birth) for birth in SAMPLE]


# ── 来源路径必须可解析，且值对得上 ────────────────────────────────────


def test_every_fact_source_matches_an_allowed_path():
    """``Fact.source`` 只能是已知的几种路径形态。

    为什么用允许清单：证据链的最后一跳是给用户看的，路径必须能真的指到
    命盘上某一处。若只检查「以 chart. 开头」，``chart.whatever`` 也能过。
    """
    offenders: list[str] = []
    for chart in charts():
        for fact in extract_facts(chart):
            if not any(pattern.match(fact.source) for pattern in SOURCE_PATTERNS):
                offenders.append(f"{fact.type} → {fact.source}")
    assert not offenders, "以下事实的来源路径不在允许清单内：\n  " + "\n  ".join(offenders)


def test_sources_without_a_wildcard_resolve_on_the_chart():
    """不带 ``[*]`` 的来源必须真的能按文法取到值。

    这条是「路径拼错」的守门人：``chart.pillars.month.hidden_stems`` 若写成
    ``chart.pillars.month.hidden_stem``（少个 s），字符串本身看不出问题，
    但任何按路径回溯的实现都会 ``ValueError``。

    注意 ``chart.pillars.year`` **不是**属性访问 —— ``pillars`` 是元组，
    ``year`` 是柱名。这条路径形态此前只写在人读的注释里，所以这里改用
    :func:`knowledge.facts.resolve_source` 解析，让文法本身可执行、可验证。
    """
    chart = charts()[0]
    for fact in extract_facts(chart):
        if "[*]" in fact.source:
            continue
        # 不抛异常即为通过；取值是否等于 fact.value 由下面几条断言分别管
        # （有些事实是派生值，例如 day_master_element 与 day_master 同源）。
        resolve_source(chart, fact.source)


def test_wildcard_sources_resolve_to_one_value_per_pillar():
    """``[*]`` 形态必须对四柱逐项取值，且条数与四柱一致。"""
    chart = charts()[0]
    for fact in extract_facts(chart):
        if "[*]" not in fact.source:
            continue
        resolved = resolve_source(chart, fact.source)
        assert isinstance(resolved, tuple)
        assert len(resolved) == len(chart.pillars), (
            f"{fact.source} 应逐柱取值，得到 {len(resolved)} 项"
        )


def test_resolve_source_rejects_paths_it_cannot_parse():
    """文法外的路径必须报错，不能静默返回 None。

    静默返回 None 会让「来源写错」看起来像「这条事实没有来源」，
    而证据链随后会把空来源当成正常数据展示出去。
    """
    chart = charts()[0]
    for bad in ("time.liunian", "chart.nope", "chart.pillars.nope", "chart.day_master.x"):
        with pytest.raises(ValueError):
            resolve_source(chart, bad)


def test_pillar_facts_carry_the_values_of_the_pillar_they_point_at():
    """单柱事实的值必须等于它指向的那一柱的字段。

    这是本文件的核心断言：来源写着 ``chart.pillars.year``，那 ``year_stem``
    就必须等于 ``chart.pillars[0].heavenly_stem``。提取器里如果把下标写错
    （年份取了月柱），键名测试全绿，命盘解读却整体偏移一位。
    """
    for chart in charts():
        by_name = {pillar.name: pillar for pillar in chart.pillars}
        values = {fact.type: fact.value for fact in extract_facts(chart)}
        for name in ("year", "month", "day", "hour"):
            pillar = by_name[name]
            assert values[f"{name}_stem"] == pillar.heavenly_stem
            assert values[f"{name}_branch"] == pillar.earthly_branch
            assert values[f"{name}_pillar"] == pillar.heavenly_stem + pillar.earthly_branch


def test_day_master_facts_point_at_the_day_pillar_stem():
    """日主三件套必须与日柱天干一致。"""
    for chart in charts():
        values = {fact.type: fact.value for fact in extract_facts(chart)}
        day_stem = chart.pillars[2].heavenly_stem
        assert values["day_master"] == day_stem
        assert values["day_master_element"] == ELEMENTS[day_stem]
        assert values["day_master_polarity"] == POLARITY[day_stem]
        # Chart.day_master 与四柱之间也不能各说各话。
        assert chart.day_master == day_stem


def test_month_facts_come_from_the_month_branch_main_qi():
    """月令相关事实必须取月支**本气**（藏干第一位），不是别的位。"""
    for chart in charts():
        month = chart.pillars[1]
        main_qi = month.hidden_stems[0]
        values = {fact.type: fact.value for fact in extract_facts(chart)}
        assert values["month_branch_element"] == ELEMENTS[main_qi]
        assert values["month_branch_ten_god"] == ten_god(
            chart.pillars[2].heavenly_stem, main_qi
        )


# ── 五行计数与集合类事实必须自洽 ──────────────────────────────────────


def test_element_counts_match_a_manual_tally():
    """五行计数 = 四柱天干 + 四支本气，共 8 项（口径见 facts 模块文档）。"""
    for chart in charts():
        tally = dict.fromkeys(("木", "火", "土", "金", "水"), 0)
        for pillar in chart.pillars:
            tally[ELEMENTS[pillar.heavenly_stem]] += 1
            tally[ELEMENTS[pillar.hidden_stems[0]]] += 1
        values = {fact.type: fact.value for fact in extract_facts(chart)}
        for element, expected in tally.items():
            assert values[f"count_{element}"] == expected, (
                f"{element} 计数应为 {expected}，实得 {values[f'count_{element}']}"
            )
        assert sum(tally.values()) == 8, "四干四支共 8 项，合计必须为 8"


def test_missing_and_dominant_elements_are_the_complement_of_the_counts():
    """缺失 / 偏旺两个集合必须能由计数推出来，不能是另一套独立口径。"""
    for chart in charts():
        values = {fact.type: fact.value for fact in extract_facts(chart)}
        counts = {e: values[f"count_{e}"] for e in ("木", "火", "土", "金", "水")}

        assert set(values["missing_elements"]) == {e for e, n in counts.items() if n == 0}
        assert set(values["dominant_elements"]) == {e for e, n in counts.items() if n >= 3}
        # 两个集合不可能相交：一个五行要么缺席要么在场。
        assert not set(values["missing_elements"]) & set(values["dominant_elements"])


def test_same_element_count_includes_stems_and_hidden_stems():
    """日主同类计数 = 四干 + 全部藏干中与日主同五行者（口径见模块文档）。"""
    for chart in charts():
        day_element = ELEMENTS[chart.pillars[2].heavenly_stem]
        expected = sum(
            1
            for pillar in chart.pillars
            for stem in (pillar.heavenly_stem, *pillar.hidden_stems)
            if ELEMENTS[stem] == day_element
        )
        values = {fact.type: fact.value for fact in extract_facts(chart)}
        assert values["day_master_same_element_count"] == expected


# ── 十神事实里不能混进「日主」 ────────────────────────────────────────


def test_no_fact_ever_reports_the_day_master_as_a_ten_god():
    """``日主`` 是日柱天干的标签，不是十神。它不能出现在任何十神事实里。

    为什么这条值得单独测：``Pillar.ten_god`` 在日柱上存的就是字符串
    ``"日主"``（对外响应字段，不能改），于是「把所有 pillar.ten_god 收进
    一个集合」这种写法会把 ``日主`` 混进十神。提取器现在用
    ``pillar.name != "day"`` 挡住了，但那是**一处容易漏的过滤** ——
    新增十神事实时忘了它，就会出现「日主有根」这类自相矛盾的证据。
    """
    for chart in charts():
        for fact in extract_facts(chart):
            if "ten_god" not in fact.type:
                continue
            values = fact.value if isinstance(fact.value, tuple) else (fact.value,)
            assert "日主" not in values, f"{fact.type} 里混进了「日主」：{values}"

    assert "日主" not in TEN_GODS, "十神全表不应包含「日主」"


# ── 词表、提取器、规则三方对齐 ────────────────────────────────────────


def test_every_declared_key_is_documented():
    """词表每条都要有说明。空说明等于没声明。"""
    empty = [key for key, description in FACT_SCHEMA.items() if not description.strip()]
    assert not empty, f"以下事实键没有说明：{empty}"


def test_every_non_optional_key_is_produced_by_every_chart():
    """除结构上可能缺席的键，其余每个键都必须在**每一张**命盘上产出。

    这条比「至少有一张盘产出」更严：如果一个键只在特定命盘上产出，引用它的
    规则在别的命盘上就静默不触发，而调用方看不出差别 —— 结论少了，却没人报错。
    """
    required = set(FACT_SCHEMA) - STRUCTURALLY_OPTIONAL - FLOW_KEYS
    for chart in charts():
        produced = {fact.type for fact in extract_facts(chart)}
        missing = required - produced
        assert not missing, (
            f"{chart.pillars[0].heavenly_stem}{chart.pillars[0].earthly_branch} 年"
            f" 的命盘缺少事实：{sorted(missing)}"
        )


def test_no_fact_carries_a_none_or_empty_value():
    """``extract_facts`` 会过滤掉 None 值 —— 于是「产出 None」等于静默丢事实。

    这里直接对**过滤前**的语义做断言：所有留下来的值都必须有内容。
    空元组是合法的（例如「没有重复地支」），空字符串不是。
    """
    for chart in charts():
        for fact in extract_facts(chart):
            assert fact.value is not None, f"{fact.type} 的值为 None"
            if isinstance(fact.value, str):
                assert fact.value.strip(), f"{fact.type} 的值为空字符串"


def test_every_rule_condition_key_is_actually_produced():
    """规则引用的每个条件键，必须真能在某张命盘上拿到值。

    静态校验（``validate_condition_keys``）只查「键在词表里」。词表里可以有
    一个**永远不产出**的键 —— 那种规则永远不会触发，且没有任何报错。
    这条把词表接到真实命盘上。
    """
    registry = default_registry()
    produced_anywhere: set[str] = set()
    for chart in charts():
        produced_anywhere |= {fact.type for fact in extract_facts(chart)}

    # 结构上可能缺席的键，只要样本里出现过一次就算可达；样本覆盖了六害与
    # 多种关系，若某类关系在样本里没出现，这里会如实报出来而不是放过。
    unreachable = sorted(registry.condition_keys() - produced_anywhere)
    assert not unreachable, (
        "以下条件键被规则引用，但没有任何样本命盘产出它 —— 这些规则永远不会触发：\n  "
        + "\n  ".join(unreachable)
    )


def test_the_structurally_optional_set_is_the_same_everywhere():
    """本文件的「可缺席」清单必须与 ``test_structural_rules.py`` 的一致。

    两份清单各写一遍就会漂：一处加了新键、另一处没加，于是同一条事实
    在一份测试里算「必须产出」、在另一份里算「允许缺席」，两边都不报错。
    """
    import test_structural_rules

    assert STRUCTURALLY_OPTIONAL == test_structural_rules.STRUCTURAL_ABSENCE, (
        "两份「结构上可能缺席」清单不一致："
        f"仅本文件有 {sorted(STRUCTURALLY_OPTIONAL - test_structural_rules.STRUCTURAL_ABSENCE)}，"
        f"仅那边有 {sorted(test_structural_rules.STRUCTURAL_ABSENCE - STRUCTURALLY_OPTIONAL)}"
    )


# ── 归并与索引的一致性 ────────────────────────────────────────────────


def test_grouping_and_indexing_agree():
    """``group_facts`` 与 ``index_facts`` 必须给出同一批键与同一批值。

    两者分工不同（前者判条件、后者答来源），但都从同一串事实来。若归并时
    丢了重复项（例如 ``{f.type: f.value}`` 这种写法），规则就看不到第二种
    地支关系 —— 这个 bug 曾经真实存在过，见 ``group_facts`` 的 docstring。
    """
    for chart in charts():
        facts: tuple[Fact, ...] = extract_facts(chart)
        grouped = group_facts(facts)
        indexed = index_facts(facts)

        assert set(grouped) == set(indexed)
        for key, facts_of_type in indexed.items():
            values = tuple(fact.value for fact in facts_of_type)
            expected = values[0] if len(values) == 1 else values
            assert grouped[key] == expected


@pytest.mark.parametrize("axis", ("liunian", "dayun"))
def test_flow_fact_keys_are_declared_and_sourced(axis: str):
    """时间轴事实的键与来源也要在词表与允许清单内。

    时间轴用 ``time.`` 命名空间而不是 ``chart.`` —— 流年干支不是命盘的一部分，
    同一个人不同年份不同，挂到 Chart 上会让「命盘不变」这个前提失效。

    **但来源指向 chart 也是对的**：``dayun_stem_ten_god_root`` 问的是「大运天干
    十神在本命四支里有没有根」，答案确实在命盘里。所以规则不是「一律 time.」，
    而是「time.* 必须落在本轴命名空间内，chart.* 必须真的能解析」。
    第一版断言「一律 time.」是我想当然了，被这条数据逮到。
    """
    from knowledge.flow_facts import flow_facts

    chart = charts()[0]
    facts = flow_facts(chart, axis, "甲", "午")
    declared = set(FACT_SCHEMA)
    assert facts, f"{axis} 没有产出任何事实"
    for fact in facts:
        assert fact.type in declared, f"{fact.type} 不在词表里"
        assert fact.type.startswith(f"{axis}_"), f"{fact.type} 应以 {axis}_ 开头"
        if fact.source.startswith("time."):
            assert fact.source == f"time.{axis}" or fact.source.startswith(f"time.{axis}."), (
                f"{fact.type} 的来源落在别的轴：{fact.source!r}"
            )
        else:
            # chart.* 来源必须能解析 —— 与提取器那批用同一套文法。
            resolve_source(chart, fact.source)

"""五行普查：单一事实源（Phase 5.3）。

## 这个文件守什么

「五行计数」在 5.3 之前有**两份生产实现加一个死读法**：

1. ``knowledge/facts.py`` 自己数一遍，产出 ``count_X`` / ``missing_elements``
   / ``dominant_elements`` 事实；
2. 前端读的 ``chart.elements.missing`` —— provider 从来没产出过这个键，
   「缺五行」一行从上线起就是死的（5.2 删了那行死代码）；
3. （``tests/test_evidence_audit`` 也有一份，但那是**刻意**的独立复算
   实现，同 lunar_python 差分测试的套路 —— 与被测同源就失去复核意义，
   不在收编范围。）

5.3 把生产侧收成 ``engines.bazi.ten_gods.element_census`` 一个实现：
facts 层调用它（事实层口径不变），provider 调用它（``chart.elements``
带普查，UI 直接读），``ELEMENT_NAMES`` 也只有一个定义处
（facts 转口，structural_rules 经 facts 转手）。

**两份消费者、一份实现**这件事由本文件钉住：任一侧悄悄改口径
（换阈值、加减计数项），另一侧的测试就红。
"""

from __future__ import annotations

from engines.bazi import BaziCalculator, BirthInput, SxtwlBaziProvider
from engines.bazi.ten_gods import (
    DOMINANT_THRESHOLD,
    ELEMENT_NAMES,
    element_census,
)
from knowledge.facts import extract_facts

CALCULATOR = BaziCalculator(SxtwlBaziProvider())


def _chart(birth: BirthInput):
    return CALCULATOR.calculate_chart(birth)


def _fact_values(chart, prefix: str) -> dict[str, object]:
    facts = {fact.type: fact.value for fact in extract_facts(chart)}
    return {
        element: facts[f"{prefix}_{element}"] for element in ELEMENT_NAMES
    }


# ── 口径 ───────────────────────────────────────────────────────────────


def test_census_counts_eight_items():
    """四柱天干 + 四支本气 = 8 项。多数一个少数一个都是口径漂移。"""
    chart = _chart(BirthInput(1990, 2, 1, 12))
    census = element_census(chart.pillars)

    assert sum(census["count"].values()) == 8
    assert set(census["count"]) == set(ELEMENT_NAMES)


def test_census_order_follows_the_element_names():
    """枚举顺序是木火土金水（相生序），不是 dict 的插入序之外的花样。"""
    assert ELEMENT_NAMES == ("木", "火", "土", "金", "水")
    chart = _chart(BirthInput(1990, 2, 1, 12))
    census = element_census(chart.pillars)

    assert tuple(census["count"]) == ELEMENT_NAMES


def test_missing_and_dominant_are_derived_from_the_counts():
    """缺失 = 计数为 0 的补集；偏旺 = 计数 ≥ 阈值的子集。两者不独立成表。"""
    assert DOMINANT_THRESHOLD == 3
    chart = _chart(BirthInput(1990, 2, 1, 12))
    census = element_census(chart.pillars)
    counts = census["count"]

    assert set(census["missing"]) == {e for e, n in counts.items() if n == 0}
    assert set(census["dominant"]) == {e for e, n in counts.items() if n >= DOMINANT_THRESHOLD}
    assert not set(census["missing"]) & set(census["dominant"])


# ── provider：chart.elements 带普查 ────────────────────────────────────


def test_chart_elements_carry_the_census():
    """UI 读的 chart.elements.count/missing/dominant 必须真实存在。

    5.2 删掉的死代码读的就是这个形状的键 —— 那回是 provider 没产出，
    这一回是先有测试再有产出。
    """
    chart = _chart(BirthInput(1990, 2, 1, 12))
    payload = chart.to_dict()
    census = element_census(chart.pillars)

    # day_master_element 是原有的键（日主五行），不能被普查挤掉。
    assert payload["elements"]["day_master_element"] == "火"  # 丁日主
    assert payload["elements"]["count"] == census["count"]
    assert tuple(payload["elements"]["missing"]) == census["missing"]
    assert tuple(payload["elements"]["dominant"]) == census["dominant"]


def test_chart_elements_census_survives_a_missing_element_chart():
    """找一张真缺五行的命盘：缺失列表非空才说明这条路径有数据走过。"""
    # 1990-02-01 12:00 四柱 庚午/戊寅/丁酉/丙午 —— 天干地支本气只覆盖四种五行。
    chart = _chart(BirthInput(1990, 2, 1, 12))
    missing = chart.to_dict()["elements"]["missing"]

    assert missing, "这张盘应缺至少一种五行，否则本节空测"
    assert set(missing) <= set(ELEMENT_NAMES)


# ── facts 层与 provider 层同源 ─────────────────────────────────────────


def test_facts_counts_match_the_chart_census():
    """事实层的 count_X 与 chart.elements.count 逐元素相等。

    这是反漂移的主测试：facts 层与 provider 层曾各自数一遍。现在 facts
    调用 element_census，这条测试保证「调用」没被改回「自己数」。
    """
    for birth in (
        BirthInput(1990, 2, 1, 12),
        BirthInput(1984, 6, 15, 23, 50, longitude=121.5),
        BirthInput(2001, 11, 7, 3, 15),
    ):
        chart = _chart(birth)
        census = element_census(chart.pillars)
        fact_counts = _fact_values(chart, "count")

        assert fact_counts == census["count"], f"{birth} 的事实层计数与普查不一致"


def test_facts_missing_and_dominant_match_the_census():
    chart = _chart(BirthInput(1990, 2, 1, 12))
    facts = {fact.type: fact.value for fact in extract_facts(chart)}
    census = element_census(chart.pillars)

    assert set(facts["missing_elements"]) == set(census["missing"])
    assert set(facts["dominant_elements"]) == set(census["dominant"])


def test_element_names_have_a_single_source():
    """ELEMENT_NAMES 只在 ten_gods 定义，消费者直引。

    ``structural_rules`` 曾经 ``knowledge.facts`` 转手 import 它 —— 转口链
    每多一环就多一处会断的地方，现在两边都直引 ten_gods。
    ``tests/test_evidence_audit`` 的独立副本是刻意保留的审计实现，
    不要求同源。
    """
    import knowledge.structural_rules as structural_module

    assert structural_module.ELEMENTS is ELEMENT_NAMES

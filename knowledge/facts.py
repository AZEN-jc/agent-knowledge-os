"""从确定性命盘提取事实（Fact）：只描述**命盘里有什么**，不做吉凶判断。

这里是整个证据链的源头。规则只能看到本模块产出的事实，因此
「规则条件键是否存在于事实词表」是一个可以静态校验的硬约束 ——
见 :data:`FACT_SCHEMA`。

模块边界：本模块**不依赖** :mod:`knowledge.rules`。规则匹配需要回填
「这条条件是被哪条事实满足的」，于是 :mod:`knowledge.rules` 反过来依赖这里。
把 :class:`Fact` 放在本模块而不是 :mod:`knowledge.evidence`，就是为了让这条
依赖是单向的 —— 否则规则与证据层会互相 import。

三条口径约定，写下来免得后人猜：

1. **五行计数**：按「四柱天干 + 四支本气（藏干第一位）」共 8 项计数。
   不同流派对藏干是否计入、计几位存在分歧，本实现只选一种并明示，
   不声称这是唯一正确口径。
2. **有根**：四支藏干中存在与日主**同五行**者即为有根（不要求同阴阳）。
   更严格的本气根口径（同五行且同阴阳）是另一个流派分歧点，尚未录入。
3. **日主同类多寡分档**：计数口径是「四柱天干 + 全部藏干」，量级约 13 项，
   所以分档取 2 / 4 为界，不是百分位。阈值是本实现选定的，不是典籍规定。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engines.bazi.models import Chart
from engines.bazi.ten_gods import (
    ELEMENTS,
    POLARITY,
    element_census,
    stem_relation,
    ten_god,
)

PILLAR_NAMES = ("year", "month", "day", "hour")
#: ELEMENT_NAMES 自 Phase 5.3 起由 engines.bazi.ten_gods 定义。
#: 生产侧曾有两份（本模块定义 + structural_rules 经本模块转手），对不上
#: 只是时间问题；现在两边都直引 ten_gods。tests/test_evidence_audit 的
#: 独立副本是刻意保留的审计实现，不在此列。

FACT_SCHEMA: dict[str, str] = {
    # 日主
    "day_master": "日主天干",
    "day_master_element": "日主五行",
    "day_master_polarity": "日主阴阳",
    "day_master_root": "日主在四支是否有根（有根 / 无根）",
    "day_master_same_element_count": "四柱天干与藏干中与日主同五行的个数",
    # 四柱干支
    "year_stem": "年柱天干",
    "month_stem": "月柱天干",
    "day_stem": "日柱天干",
    "hour_stem": "时柱天干",
    "year_branch": "年支",
    "month_branch": "月支",
    "day_branch": "日支",
    "hour_branch": "时支",
    "four_branches": "四支去重后的集合",
    "repeated_branches": "四支中重复出现的地支",
    # 整柱干支：典籍断语常按月柱整体取断（「乙卯月刑折」），只有单干单支时
    # 就得写两条条件，而「乙干且卯支」不等于「乙卯月」—— 还要防甲卯、乙寅等
    # 组合被误命中。所以整柱必须是一等事实。
    "year_pillar": "年柱完整干支（如「庚申」）",
    "month_pillar": "月柱完整干支（如「乙卯」）",
    "day_pillar": "日柱完整干支",
    "hour_pillar": "时柱完整干支",
    # 十神
    "year_ten_god": "年柱天干十神",
    "month_ten_god": "月柱天干十神",
    "hour_ten_god": "时柱天干十神",
    "transparent_ten_gods": "天干（除日主外）出现的十神",
    "hidden_ten_gods": "四支藏干对应的十神",
    "ten_god_with_root": "既透干又见根的十神",
    "ten_god_without_root": "透干但四支无根的十神（虚透）",
    # 月令
    "month_branch_element": "月支本气五行",
    "month_branch_ten_god": "月支本气对日主的十神",
    "month_branch_extended_ten_god": "月支藏干中在天干（年月时）透出者对应的十神",
    "day_master_vs_month": "日主与月令的生克关系（同我 / 生我 / 我生 / 我克 / 克我）",
    "year_month_elements": "年月两柱干与本气出现的五行（去重）",
    # 五行计数
    "count_木": "木的计数",
    "count_火": "火的计数",
    "count_土": "土的计数",
    "count_金": "金的计数",
    "count_水": "水的计数",
    "missing_elements": "四柱未出现的五行",
    "dominant_elements": "计数 ≥3 的五行",
    # 地支结构
    "has_relation": "四支关系类型（六合 / 六冲 / 六害 / 相破 / 自刑 / 三刑）",
    "relation_count": "地支关系总条数",
    "relation_density": "地支关系密度（无 / 少 / 多）",
    # 旺衰结构计数
    "day_master_same_element_level": "日主同类（比劫与印）在命局中的多寡（偏少 / 中等 / 偏多）",
    # 时间轴：流年与大运。前缀 ``liunian_`` / ``dayun_`` 各六个键，由
    # :mod:`knowledge.flow_facts` 产出。它们**不是**本命盘事实 —— 同一个人
    # 在不同年份的流年十神不同，而本命盘事实不变，所以单独一组而不是
    # 让 ``extract_facts`` 多收一个参数。
    "liunian_pillar": "流年柱完整干支",
    "liunian_stem_ten_god": "流年天干对日主的十神",
    "liunian_branch_ten_god": "流年支本气对日主的十神",
    "liunian_relations": "流年支与命盘四支的结构关系类型（六合 / 六冲 / 六害 / 相破）",
    "liunian_relation_pairs": "流年支与命盘四支的结构关系明细（含所冲/所合的是哪一支）",
    "liunian_stem_ten_god_root": "流年天干十神在四支藏干中是否有同类（有根 / 无根）",
    "dayun_pillar": "大运柱完整干支",
    "dayun_stem_ten_god": "大运天干对日主的十神",
    "dayun_branch_ten_god": "大运支本气对日主的十神",
    "dayun_relations": "大运支与命盘四支的结构关系类型（六合 / 六冲 / 六害 / 相破）",
    "dayun_relation_pairs": "大运支与命盘四支的结构关系明细（含所冲/所合的是哪一支）",
    "dayun_stem_ten_god_root": "大运天干十神在四支藏干中是否有同类（有根 / 无根）",
}


@dataclass(frozen=True)
class Fact:
    """一条命盘事实。

    ``source`` 是证据链回溯到命盘要素的最后一跳。没有它，用户只能看到
    「规则要求正官」，看不到「正官来自月支藏干」。

    **``source`` 的完整文法**（此前只写了「必须形如 chart.xxx」，而实际用到
    的路径比这句话复杂，导致没人能机器验证它）：

    ==============================  ====================================
    形态                             含义
    ==============================  ====================================
    ``chart.day_master``            命盘的日主天干
    ``chart.pillars``               四柱元组（整体）
    ``chart.relations``             地支关系元组
    ``chart.pillars.<name>``        **按柱名**取那一柱（year/month/day/hour），
                                    不是属性访问 —— ``pillars`` 是元组
    ``chart.pillars.<name>.<attr>`` 那一柱的某个字段
    ``chart.pillars[*].<attr>``     对四柱逐一取该字段
    ``time.<axis>``                 时间轴事实（流年/大运）整体
    ``time.<axis>.<field>``         时间轴那一柱的某个字段（如 ``.heavenly_stem``）
    ==============================  ====================================

    ``time.*`` 与 ``chart.*`` 是两个命名空间：流年干支不是命盘的一部分，
    同一个人不同年份不同，所以不能挂在 Chart 上。:func:`resolve_source`
    只解析 ``chart.*``。
    """

    type: str
    value: Any
    source: str
    confidence: float = 1.0


#: ``Fact.source`` 里表示「对四柱逐一」的记号。
WILDCARD = "[*]"


def resolve_source(chart: Chart, source: str) -> Any:
    """按 :class:`Fact` 文法的 ``chart.*`` 形态取值。

    **为什么要有这个函数，而不是让调用方自己 ``getattr``。**
    ``chart.pillars.year`` 看着像属性路径，但 ``pillars`` 是元组，
    ``year`` 是柱名 —— 直接按点号拆开遍历会 ``AttributeError``。
    文法写在 docstring 里没人能验证，写成函数才能被测试盯住，
    也才能让证据链真的回溯到命盘要素而不是停在字符串上。

    ``time.*`` 不在本函数职责内：它需要流年/大运的上下文，
    只有产出方自己知道。传进来会抛 ``ValueError``，不静默返回 None。
    """
    if not source.startswith("chart."):
        raise ValueError(f"只能解析 chart.* 来源，收到 {source!r}")

    return _walk(chart, source.split(".")[1:], source)


def _walk(node: Any, parts: list[str], source: str) -> Any:
    """按剩余路径段逐级下钻；遇到 ``[*]`` 时对元组逐项应用后续路径。

    ``[*]`` 是**挂在段尾**的（``pillars[*]``），不是独立一段 —— 真实数据里
    写成 ``chart.pillars[*].ten_god``，按点号切出来是 ``pillars[*]``。
    第一版实现只处理了独立成段的 ``[*]``，于是这条路径解析不了。
    """
    for index, part in enumerate(parts):
        if part.endswith(WILDCARD):
            base = part[: -len(WILDCARD)]
            node = _walk(node, [base], source) if base else node
            if not isinstance(node, tuple):
                raise ValueError(f"{source!r} 里的 [*] 只能用在元组上")
            rest = parts[index + 1:]
            if not rest:
                return node
            return tuple(_walk(item, rest, source) for item in node)

        if part == WILDCARD:  # 独立成段的写法，保留兼容
            if not isinstance(node, tuple):
                raise ValueError(f"{source!r} 里的 [*] 只能用在元组上")
            rest = parts[index + 1:]
            return node if not rest else tuple(_walk(item, rest, source) for item in node)

        if isinstance(node, tuple):
            # 元组上只有一种走法：按柱名取那一柱。
            names = {item.name for item in node if hasattr(item, "name")}
            if part not in names:
                raise ValueError(f"{source!r} 在元组上无法解析 {part!r}")
            node = next(item for item in node if getattr(item, "name", None) == part)
            continue

        if not hasattr(node, part):
            raise ValueError(f"{source!r} 在 {type(node).__name__} 上取不到 {part!r}")
        node = getattr(node, part)
    return node


def extract_facts(chart: Chart) -> tuple[Fact, ...]:
    """只提取命盘中实际存在的结构事实。"""
    pillars = chart.pillars
    day_stem = chart.day_master or pillars[2].heavenly_stem
    day_element = ELEMENTS[day_stem]

    facts: list[Fact] = [
        Fact("day_master", day_stem, "chart.day_master"),
        Fact("day_master_element", day_element, "chart.day_master"),
        Fact("day_master_polarity", POLARITY[day_stem], "chart.day_master"),
    ]

    hidden_gods: list[str] = []
    hidden_elements: list[str] = []
    for pillar in pillars:
        facts.append(Fact(f"{pillar.name}_stem", pillar.heavenly_stem, f"chart.pillars.{pillar.name}"))
        facts.append(Fact(f"{pillar.name}_branch", pillar.earthly_branch, f"chart.pillars.{pillar.name}"))
        facts.append(Fact(
            f"{pillar.name}_pillar",
            pillar.heavenly_stem + pillar.earthly_branch,
            f"chart.pillars.{pillar.name}",
        ))
        # 日柱天干恒为「日主」，不是一个十神，产出来只会污染事实链。
        if pillar.name != "day" and pillar.ten_god:
            facts.append(Fact(f"{pillar.name}_ten_god", pillar.ten_god, f"chart.pillars.{pillar.name}"))
        for hidden in pillar.hidden_stems:
            hidden_gods.append(ten_god(day_stem, hidden))
            hidden_elements.append(ELEMENTS[hidden])

    transparent = tuple(pillar.ten_god for pillar in pillars if pillar.name != "day" and pillar.ten_god)
    hidden_set = set(hidden_gods)
    facts.append(Fact("transparent_ten_gods", transparent, "chart.pillars[*].ten_god"))
    facts.append(Fact("hidden_ten_gods", tuple(hidden_gods), "chart.pillars[*].hidden_stems"))
    facts.append(Fact(
        "ten_god_with_root",
        tuple(god for god in dict.fromkeys(transparent) if god in hidden_set),
        "chart.pillars[*].hidden_stems",
    ))
    facts.append(Fact(
        "ten_god_without_root",
        tuple(god for god in dict.fromkeys(transparent) if god not in hidden_set),
        "chart.pillars[*].hidden_stems",
    ))

    month_main = pillars[1].hidden_stems[0]
    month_element = ELEMENTS[month_main]
    facts.append(Fact("month_branch_element", month_element, "chart.pillars.month.hidden_stems"))
    facts.append(Fact("month_branch_ten_god", ten_god(day_stem, month_main), "chart.pillars.month.hidden_stems"))
    facts.append(Fact("day_master_vs_month", stem_relation(day_element, month_element), "chart.pillars.month"))

    # 年月两柱的五行构成。典籍说「若水位年月，水泛木浮」—— 断的是年月这一层的
    # 水势，不是全命局的水数。全命局的 count_水 在这里答不上话：时柱带一水也会
    # 把计数抬起来，而那不是断语说的范围。引文范围必须与判定范围一致。
    year_month_elements = tuple(dict.fromkeys(
        ELEMENTS[p.heavenly_stem] for p in pillars[:2]
    )) + tuple(dict.fromkeys(
        ELEMENTS[p.hidden_stems[0]] for p in pillars[:2]
    ))
    facts.append(Fact(
        "year_month_elements",
        tuple(dict.fromkeys(year_month_elements)),
        "chart.pillars[*].hidden_stems",
    ))

    # 透干定格法所需的事实：月支藏干中，出现在年月时天干上的那些十神。
    # 不含日柱天干 —— 日干是日主本身，不是十神，混进来会让「透干」的含义走样。
    stem_gods = {
        pillar.heavenly_stem: pillar.ten_god
        for pillar in pillars
        if pillar.name != "day" and pillar.ten_god
    }
    facts.append(Fact(
        "month_branch_extended_ten_god",
        tuple(dict.fromkeys(
            god for hidden in pillars[1].hidden_stems
            if (god := stem_gods.get(hidden)) is not None
        )),
        "chart.pillars.month.hidden_stems",
    ))

    # 五行计数：四柱天干 + 四支本气，共 8 项（口径见 element_census 的文档）。
    # 这里不再自己数一遍 —— Phase 5.3 起 count_X / missing_elements /
    # dominant_elements 与 chart.elements 的普查同源（element_census），
    # 两份实现对不上是迟早的事，曾为此死过一行 UI。
    census = element_census(pillars)
    for element, count in census["count"].items():
        facts.append(Fact(f"count_{element}", count, "chart.pillars"))
    facts.append(Fact("missing_elements", census["missing"], "chart.pillars"))
    facts.append(Fact("dominant_elements", census["dominant"], "chart.pillars"))

    branches = tuple(pillar.earthly_branch for pillar in pillars)
    facts.append(Fact("four_branches", tuple(dict.fromkeys(branches)), "chart.pillars[*].earthly_branch"))
    facts.append(Fact(
        "repeated_branches",
        tuple(branch for branch in dict.fromkeys(branches) if branches.count(branch) >= 2),
        "chart.pillars[*].earthly_branch",
    ))
    facts.append(Fact("relation_count", len(chart.relations), "chart.relations"))
    facts.append(Fact("relation_density", _density(len(chart.relations)), "chart.relations"))
    for relation in chart.relations:
        facts.append(Fact("has_relation", relation["type"], "chart.relations"))

    rooted = "有根" if day_element in hidden_elements else "无根"
    facts.append(Fact("day_master_root", rooted, "chart.pillars[*].hidden_stems"))
    same_element = sum(
        1
        for element in [ELEMENTS[p.heavenly_stem] for p in pillars] + hidden_elements
        if element == day_element
    )
    facts.append(Fact("day_master_same_element_count", same_element, "chart.pillars"))
    facts.append(Fact(
        "day_master_same_element_level", _same_element_level(same_element), "chart.pillars"
    ))

    return tuple(fact for fact in facts if fact.value is not None)


def _density(count: int) -> str:
    """地支关系密度分档；分档阈值是本实现选定的，不是典籍规定。"""
    if count == 0:
        return "无"
    return "少" if count <= 2 else "多"


def _same_element_level(count: int) -> str:
    """日主同类多寡分档（口径见模块文档第 3 条）。"""
    if count <= 2:
        return "偏少"
    return "中等" if count <= 4 else "偏多"


def group_facts(facts: tuple[Fact, ...]) -> dict[str, Any]:
    """按类型归并事实值：同类型多条事实收成元组，只有一条时保持标量。

    不能写成 ``{fact.type: fact.value}`` —— 一个命盘里往往同时存在六合、自刑
    等多种地支关系，直接建字典会让后一条覆盖前一条，只剩最后一条能被规则看到，
    地支关系类规则于是永远匹配不上。
    """
    grouped: dict[str, list[Any]] = {}
    for fact in facts:
        grouped.setdefault(fact.type, []).append(fact.value)
    return {
        key: values[0] if len(values) == 1 else tuple(values)
        for key, values in grouped.items()
    }


def index_facts(facts: tuple[Fact, ...]) -> dict[str, tuple[Fact, ...]]:
    """按类型索引事实对象（不是取值），供规则匹配回填条件追踪。

    与 :func:`group_facts` 的分工：后者给匹配器判「条件成不成立」，
    前者给证据链答「是哪条事实、来自命盘哪里」。
    """
    index: dict[str, list[Fact]] = {}
    for fact in facts:
        index.setdefault(fact.type, []).append(fact)
    return {key: tuple(values) for key, values in index.items()}

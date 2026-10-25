"""Phase 3：独立事实复核与规则匹配准确率（MINGLI_PLAN.md §3.5 验收标准 1、2）。

这组测试用**在测试内部另写一遍**的事实推导路径，与 :mod:`knowledge.facts`
的结果逐条比对，再据此计算规则匹配的 precision / recall。

它证明什么、不证明什么 —— 必须说清楚，否则「准确率 100%」会被读成
「命理判断 100% 正确」：

- **证明**：事实提取与规则匹配的**管道**自洽 —— 没有覆盖、漏项、键名漂移、
  多值丢失这类错误。Phase 2 真出过一个：同类型多值事实互相覆盖，导致
  「六合」规则永远匹配不上，而测试全绿。
- **不证明**：命理判断的正确性。两边读的是同一份命盘字段、同一套结构定义；
  若定义本身错了，这里发现不了 —— 那需要典籍原文，属 Phase 2 的阻塞点。

所以下面把指标叫作「管道准确率」，不叫「预测准确率」。这是刻意的命名：
名字一旦含糊，数字就会被过度解读。
"""

from engines.bazi import BirthInput, SxtwlBaziProvider
from knowledge.default_rules import default_registry
from knowledge.facts import extract_facts, group_facts
from knowledge.rules import Rule, condition_holds

PROVIDER = SxtwlBaziProvider()

MINIMUM_FACTS_PER_CHART = 20
"""MINGLI_PLAN.md §3.5 验收标准 1：能从命盘提取 20+ 事实。"""

MINIMUM_PIPELINE_ACCURACY = 0.9
"""MINGLI_PLAN.md §3.5 验收标准 2：事实与规则匹配准确率 > 90%。"""

# ── 测试内部独立重写的定义表 ────────────────────────────────────────────
# 刻意不从 engines.bazi 导入：本组测试要复核的是「聚合与匹配管道」，
# 定义表两边必须各自持有，否则一处改动会被另一处掩盖。

ELEMENT_OF = {
    "甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
    "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水",
}
YANG_STEMS = frozenset("甲丙戊庚壬")
ELEMENT_NAMES = ("木", "火", "土", "金", "水")
GENERATES = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
CONTROLS = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}


def audit_ten_god(day_master: str, stem: str) -> str:
    """测试内的十神实现。判定顺序与产品实现一致，但代码是独立写的。"""
    mine = ELEMENT_OF[day_master]
    other = ELEMENT_OF[stem]
    same = (day_master in YANG_STEMS) == (stem in YANG_STEMS)
    if other == mine:
        return "比肩" if same else "劫财"
    if other == GENERATES[mine]:
        return "食神" if same else "伤官"
    if mine == GENERATES[other]:
        return "偏印" if same else "正印"
    if other == CONTROLS[mine]:
        return "偏财" if same else "正财"
    return "七杀" if same else "正官"


def audit_month_relation(day_element: str, month_element: str) -> str:
    if month_element == day_element:
        return "同我"
    if GENERATES[month_element] == day_element:
        return "生我"
    if GENERATES[day_element] == month_element:
        return "我生"
    if CONTROLS[day_element] == month_element:
        return "我克"
    return "克我"


def audit_density(count: int) -> str:
    """与产品实现同一套阈值（0 / ≤2 / 其余）。阈值变了，两边必须一起改。"""
    if count == 0:
        return "无"
    return "少" if count <= 2 else "多"


def audit_same_element_level(count: int) -> str:
    if count <= 2:
        return "偏少"
    return "中等" if count <= 4 else "偏多"


def audit_fact_map(chart) -> dict[str, object]:
    """独立推导一份事实映射（只覆盖规则实际读取的条件键）。

    刻意不复用 :func:`knowledge.facts.extract_facts` 的任何一行 ——
    复核的价值全部来自「两条路径独立走完再比对」。
    """
    pillars = chart.pillars
    day_stem = chart.day_master or pillars[2].heavenly_stem
    day_element = ELEMENT_OF[day_stem]

    hidden = [stem for pillar in pillars for stem in pillar.hidden_stems]
    hidden_gods = [audit_ten_god(day_stem, stem) for stem in hidden]
    transparent = [p.ten_god for p in pillars if p.name != "day" and p.ten_god]

    month_main = pillars[1].hidden_stems[0]
    stem_gods = {p.heavenly_stem: p.ten_god for p in pillars if p.name != "day" and p.ten_god}

    stem_elements = [ELEMENT_OF[p.heavenly_stem] for p in pillars]
    main_elements = [ELEMENT_OF[p.hidden_stems[0]] for p in pillars]
    counts = {element: (stem_elements + main_elements).count(element) for element in ELEMENT_NAMES}

    relations = tuple(relation["type"] for relation in chart.relations)
    hidden_elements = [ELEMENT_OF[stem] for stem in hidden]
    same_element = sum(
        1 for element in stem_elements + hidden_elements if element == day_element
    )

    # 四柱干支八键。日时断这类规则的条件就是「日柱是甲子、时柱是甲子」，
    # 读的正是这八个键。
    #
    # 刻意不复用上面那个 `day_stem`：那个变量是
    # ``chart.day_master or pillars[2].heavenly_stem``，语义是「日主」；
    # 而产品产出的**事实键** ``day_stem`` 取自 ``pillars[2].heavenly_stem``。
    # 两者在真实命盘上恒等，但共用一个变量就等于这条独立路径少走了一步 ——
    # 将来 provider 若让 day_master 与日柱天干不一致，复核会跟着一起错，
    # 而那正是它存在的意义。
    pillar_codes = {
        f"{pillar.name}_{suffix}": value
        for pillar in pillars
        for suffix, value in (("stem", pillar.heavenly_stem), ("branch", pillar.earthly_branch))
    }
    # 整柱干支四键。「癸巳月水火中死」读的是整柱，不是月干或月支之一 ——
    # 拆成两个键就表达不了「干与支必须同时是这个组合」。
    pillar_full_codes = {
        f"{pillar.name}_pillar": pillar.heavenly_stem + pillar.earthly_branch
        for pillar in pillars
    }

    # 年月两柱的五行构成。与 ``year_month_elements`` 的边界同一口径：
    # 只看年、月两柱的天干与本气藏干，**不含日时两柱**。
    # 断语「若水位年月，水泛木浮」说的是年月这一层的水势；
    # 复核路径如果顺手把四柱都算进去，就把判定范围放宽了 ——
    # 那会让「规则多命中」被算成一致，而它恰恰是这次要复核的错误。
    year_month_stem_elements = [
        ELEMENT_OF[p.heavenly_stem] for p in pillars[:2]
    ]
    year_month_main_elements = [
        ELEMENT_OF[p.hidden_stems[0]] for p in pillars[:2]
    ]
    year_month_elements = tuple(dict.fromkeys(
        year_month_stem_elements + year_month_main_elements
    ))

    # 季节与合局（Phase 6.3）。同样独立写一份，不 import 产品实现 ——
    # 复用就意味着「产品把辰判成夏，复核也跟着判成夏」。
    season_of = {
        "寅": "春", "卯": "春", "辰": "春",
        "巳": "夏", "午": "夏", "未": "夏",
        "申": "秋", "酉": "秋", "戌": "秋",
        "亥": "冬", "子": "冬", "丑": "冬",
    }
    branch_set = {pillar.earthly_branch for pillar in pillars}
    san_he = {
        frozenset({"寅", "午", "戌"}): "火",
        frozenset({"申", "子", "辰"}): "水",
        frozenset({"亥", "卯", "未"}): "木",
        frozenset({"巳", "酉", "丑"}): "金",
    }
    san_hui = {
        frozenset({"寅", "卯", "辰"}): "木",
        frozenset({"巳", "午", "未"}): "火",
        frozenset({"申", "酉", "戌"}): "金",
        frozenset({"亥", "子", "丑"}): "水",
    }
    formed: list[tuple[str, str]] = []
    for table, label in ((san_he, "三合"), (san_hui, "三会")):
        for members, element in table.items():
            if members <= branch_set:
                formed.append((f"{label}{element}局", element))

    fact_map: dict[str, object] = {
        **pillar_codes,
        **pillar_full_codes,
        "year_month_elements": year_month_elements,
        "month_season": season_of[pillars[1].earthly_branch],
        "year_month_branches": (pillars[0].earthly_branch, pillars[1].earthly_branch),
        # 不去重：产品的 ``transparent_ten_gods`` 按柱逐个收（年干与时干
        # 同为偏财时会出现两次）。复核要照产品的实际取值来，不能顺手
        # 用「更合理」的集合语义 —— 那会掩盖产品侧真的改了行为。
        "transparent_ten_gods": tuple(transparent),
        "day_master_root": "有根" if day_element in {ELEMENT_OF[s] for s in hidden} else "无根",
        "day_master_same_element_level": audit_same_element_level(same_element),
        "day_master_vs_month": audit_month_relation(day_element, ELEMENT_OF[month_main]),
        "dominant_elements": tuple(e for e in ELEMENT_NAMES if counts[e] >= 3),
        "missing_elements": tuple(e for e in ELEMENT_NAMES if counts[e] == 0),
        "has_relation": relations,
        "month_branch_extended_ten_god": tuple(dict.fromkeys(
            god for stem in pillars[1].hidden_stems if (god := stem_gods.get(stem)) is not None
        )),
        "month_branch_ten_god": audit_ten_god(day_stem, month_main),
        "month_ten_god": pillars[1].ten_god,
        "relation_density": audit_density(len(chart.relations)),
        "ten_god_with_root": tuple(dict.fromkeys(
            god for god in transparent if god in set(hidden_gods)
        )),
        "ten_god_without_root": tuple(dict.fromkeys(
            god for god in transparent if god not in set(hidden_gods)
        )),
    }
    # 合局类键与产品同语义：不成局时**不产出**，而不是产出空元组。
    if formed:
        fact_map["has_combination"] = tuple(name for name, _ in formed)
        fact_map["combination_elements"] = tuple(dict.fromkeys(el for _, el in formed))
    return fact_map


def audit_sample() -> tuple[BirthInput, ...]:
    """确定性的命盘样本，跨年份与月份，覆盖换月、换年与四时。"""
    return tuple(
        BirthInput(year, month, day, hour)
        for year in (1985, 1990, 1995, 2005, 2024)
        for month in (1, 4, 7, 10)
        for day in (3, 15, 27)
        for hour in (0, 6, 12, 18)
    )


def as_multiset(value: object) -> tuple:
    """把标量与元组统一成排序后的多重集合。

    ``group_facts`` 的容器约定是「同类型多条事实 → 元组，只有一条 → 标量」，
    所以两条路径的容器形状会不同（产品给 ``'六合'``，复核给 ``('六合',)``），
    但**取值集合**必须一致。比集合而不是比容器，测的才是「推导是否一致」，
    而不是「谁抄了谁的容器约定」—— 后者由 test_evidence.py 单独守着。
    """
    if isinstance(value, tuple):
        return tuple(sorted(value, key=str))
    return (value,)


def rule_holds(rule: Rule, fact_map: dict[str, object]) -> bool:
    """用独立推导的事实映射判断规则是否应当命中。

    这里复用 ``condition_holds``：被测对象是**事实推导**，不是那个谓词。
    谓词本身的边界（多值包含、字符串不做子串匹配）由 test_rules.py 单独守着。
    """
    return all(condition_holds(fact_map.get(key), expected) for key, expected in rule.condition.items())


# ── 验收标准 1：20+ 事实 ───────────────────────────────────────────────


def test_every_sampled_chart_yields_twenty_or_more_facts():
    counts = [len(extract_facts(PROVIDER.calculate(birth))) for birth in audit_sample()]

    assert min(counts) >= MINIMUM_FACTS_PER_CHART, f"最少的一张命盘只产出 {min(counts)} 条事实"


def test_facts_never_invent_a_source_outside_the_chart():
    for birth in audit_sample()[:40]:
        for fact in extract_facts(PROVIDER.calculate(birth)):
            assert fact.source.startswith("chart."), f"{fact.type} 的来源 {fact.source} 无法回溯到命盘"


# ── 复核本身要覆盖规则读到的每一个条件键 ────────────────────────────────


def test_the_audit_covers_every_condition_key_the_rules_read():
    """新增一条读新条件键的规则时，必须同时扩展本复核。

    否则新键会静默地落在复核范围之外，「准确率」这个数字就不再代表全部规则。
    """
    audited = set(audit_fact_map(PROVIDER.calculate(BirthInput(1990, 2, 1, 12))))
    read_by_rules = set(default_registry().condition_keys())

    assert read_by_rules <= audited, f"复核未覆盖规则读取的条件键：{sorted(read_by_rules - audited)}"


def test_independent_derivation_matches_the_product_on_every_sampled_chart():
    """两条独立路径对同一张命盘必须给出同一份事实。

    空的多值事实要单独说一句：``has_relation`` 是「每个关系产一条事实」，
    命盘没有任何地支关系时产品**不产出这个键**（而不是产一条空元组）。
    两者语义相同 —— 规则读不到它，就不会命中 —— 所以这里按空集合处理，
    而不是把它当成缺项。``missing_elements`` 之类则恒定产出，即使取值为空。
    """
    for birth in audit_sample():
        chart = PROVIDER.calculate(birth)
        # 必须走 group_facts，不能写成 {fact.type: fact.value ...} ——
        # 一个命盘常有多条 has_relation 事实，字典推导会让后一条覆盖前一条，
        # 那正是 Phase 2 修过的 bug。复核脚本自己踩一遍就太讽刺了。
        produced = group_facts(extract_facts(chart))
        independent = audit_fact_map(chart)

        for key, expected in independent.items():
            actual = produced.get(key)
            if actual is None and expected == ():
                continue
            assert as_multiset(actual) == as_multiset(expected), (
                f"{birth.year}-{birth.month}-{birth.day} {birth.hour}时 的 {key} 不一致："
                f"产品 {actual!r} vs 复核 {expected!r}"
            )


# ── 验收标准 2：管道准确率 > 90% ────────────────────────────────────────


def test_pipeline_precision_and_recall_stay_above_ninety_percent():
    registry = default_registry()
    rules = registry.select()
    true_positive = false_positive = false_negative = 0

    for birth in audit_sample():
        chart = PROVIDER.calculate(birth)
        independent = audit_fact_map(chart)
        matched = {match.rule.id for match in registry.match(extract_facts(chart))}
        expected = {rule.id for rule in rules if rule_holds(rule, independent)}

        true_positive += len(matched & expected)
        false_positive += len(matched - expected)
        false_negative += len(expected - matched)

    assert true_positive > 0, "样本没有命中任何规则，准确率无从谈起"
    precision = true_positive / (true_positive + false_positive)
    recall = true_positive / (true_positive + false_negative)

    assert precision >= MINIMUM_PIPELINE_ACCURACY, f"匹配精确率 {precision:.4f} 低于 90%"
    assert recall >= MINIMUM_PIPELINE_ACCURACY, f"匹配召回率 {recall:.4f} 低于 90%"

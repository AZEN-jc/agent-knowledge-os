"""Phase 6 事件窗口测试：流年与大运的结构信号。

**验证口径（与 golden cases 同一纪律）。** 预期值不来自任何「权威命理库」——
那种来源离线无法核验，凭记忆填就等于编造。这里的历史案例全部满足两条之一：

1. 流年干支可用**六十甲子算术**独立复核：``(year - 4) % 60``。
   1984 甲子、2000 庚辰、2020 庚子、2024 甲辰、1949 己丑 —— 这五个年份的
   干支是公认的历史锚点，任何人都能手算，不依赖本项目任何一行代码。
2. 十神由 ``engines.bazi.ten_gods.ten_god`` 计算，而那个函数本身被
   ``tests/test_bazi_relations.py`` 用五行表逐项钉过。

**这一层刻意不测的东西。** 不测「某年会发生什么」。信号的定义是
「命盘里出现了什么结构」，没有一处会给出必然性判断；为预测写测试
等于给一套没有的语义背书。
"""

from engines.bazi import BirthInput, SxtwlBaziProvider
from engines.bazi.ten_gods import TEN_GODS, ten_god
from engines.bazi.time_engine import ClassicalApproxDayunPolicy, DayunPolicy
from knowledge.flow_facts import flow_facts
from knowledge.time_windows import (
    GOD_SIGNAL,
    SIGNAL_CONFIDENCE,
    TOPIC_TEN_GODS,
    analyze_period,
)

PROVIDER = SxtwlBaziProvider()


def chart_of(birth: tuple[int, int, int, int], **kwargs):
    return PROVIDER.calculate(BirthInput(*birth, **kwargs))


# ── 流年干支：历史锚点，可用 (year - 4) % 60 独立复核 ──────────────────


def test_liunian_pillar_matches_the_sexagenary_arithmetic():
    """五个公认锚点年。手算一遍就能证伪，不依赖本项目任何实现。"""
    anchors = {
        1984: "甲子",  # 上一个甲子年
        2000: "庚辰",
        2020: "庚子",  # 「庚子年」
        2024: "甲辰",
        1949: "己丑",
    }
    for year, expected in anchors.items():
        window = analyze_period(chart_of((1990, 2, 1, 12)), year, year, "结构")[0]
        actual = window.liunian.heavenly_stem + window.liunian.earthly_branch
        assert actual == expected, f"{year} 年应为 {expected}，实得 {actual}"


def test_the_anchors_are_independently_recomputable():
    """锚点表本身也要能被独立算式复现 —— 否则它只是一份抄来的清单。"""
    stems = "甲乙丙丁戊己庚辛壬癸"
    branches = "子丑寅卯辰巳午未申酉戌亥"
    for year, expected in ((1984, "甲子"), (2000, "庚辰"), (2020, "庚子"),
                           (2024, "甲辰"), (1949, "己丑")):
        index = (year - 4) % 60
        assert stems[index % 10] + branches[index % 12] == expected


# ── 五个历史案例：不同日主 × 锚点年 ───────────────────────────────────


HISTORICAL_CASES = (
    # (生辰, 年份, 流年干支, 日主, 流年天干十神)
    ((1975, 8, 8, 10), 1984, "甲子", "丙", "偏印"),
    ((1963, 5, 17, 6), 2000, "庚辰", "庚", "比肩"),
    ((1988, 11, 3, 15), 2020, "庚子", "壬", "偏印"),
    ((1990, 2, 1, 12), 2024, "甲辰", "丁", "正印"),
    ((2000, 12, 25, 23), 1949, "己丑", "丁", "食神"),
)


def test_five_historical_cases_agree_with_the_ten_god_table():
    """五个案例的流年干支、日主、十神三者必须自洽。

    自洽的意思是：十神不是写死在用例里的，而是用
    ``ten_god(日主, 流年天干)`` 现场算出来再和用例比对 —— 用例只声明
    干支与日主这两个可独立核验的量。
    """
    for birth, year, ganzhi, day_master, god in HISTORICAL_CASES:
        chart = chart_of(birth)
        assert chart.pillars[2].heavenly_stem == day_master, f"{birth} 日主应为 {day_master}"

        window = analyze_period(chart, year, year, "结构")[0]
        actual = window.liunian.heavenly_stem + window.liunian.earthly_branch
        assert actual == ganzhi, f"{birth} 生于 {year} 年流年应为 {ganzhi}"

        facts = {fact.type: fact.value for fact in flow_facts(chart, "liunian", ganzhi[0], ganzhi[1])}
        assert facts["liunian_stem_ten_god"] == god, (
            f"{day_master} 日主见流年干 {ganzhi[0]} 应为 {god}"
        )
        assert facts["liunian_stem_ten_god"] == ten_god(day_master, ganzhi[0])


def test_each_historical_case_produces_a_reportable_signal():
    """每个案例都要能产出一条命名的信号，而不是空窗口。"""
    for birth, year, ganzhi, day_master, god in HISTORICAL_CASES:
        chart = chart_of(birth)
        window = analyze_period(chart, year, year, "结构")[0]
        assert window.signals, f"{birth} 在 {year} 年没有任何信号"
        assert window.strength > 0.0
        report = window.to_report()
        assert str(year) in report
        assert "信号" in report


# ── 流年事实：与本命盘口径一致 ─────────────────────────────────────────


def test_flow_ten_god_uses_the_same_table_as_the_natal_chart():
    """流年十神与本命盘十神必须走同一个函数，不能另写一套五行表。

    这是最容易悄悄分叉的地方：两处各有一张十神表，改了一处忘另一处，
    于是同一个日主在不同层得到不同的十神，而没有任何测试会响。
    """
    chart = chart_of((1990, 2, 1, 12))
    day_stem = chart.pillars[2].heavenly_stem
    for stem in "甲乙丙丁戊己庚辛壬癸":
        flow = {f.type: f.value for f in flow_facts(chart, "liunian", stem, "子")}
        assert flow["liunian_stem_ten_god"] == ten_god(day_stem, stem)


def test_flow_root_uses_the_same_definition_as_the_natal_chart():
    """有根的判定只看四支藏干，与本命盘 ``ten_god_with_root`` 同口径。

    **挑这张盘是刻意的。** 1975-08-08 日主丙，四柱乙卯癸未丙戌癸巳 ——
    癸水的十神「正官」**只在天干上出现，四支藏干里没有**。所以这张盘能把
    「只看藏干」和「藏干 + 天干」两种口径区分开；用别的盘（比如 1990-02-01
    那张）两个口径给出相同答案，测了也白测 —— 探针 U2 就是在那一版上漏掉的。

    下面两条断言分别钉住「无根」与「有根」两侧，只钉一侧的话，
    把判定整体反过来也能通过。
    """
    chart = chart_of((1975, 8, 8, 10))
    day_stem = chart.pillars[2].heavenly_stem
    assert day_stem == "丙"

    hidden_gods = {
        ten_god(day_stem, hidden)
        for pillar in chart.pillars
        for hidden in pillar.hidden_stems
    }
    assert "正官" not in hidden_gods, "这张盘的四支藏干里不该有正官"
    assert {ten_god(day_stem, p.heavenly_stem) for p in chart.pillars} >= {"正官"}, (
        "而天干上确实有正官 —— 这是本测试能区分口径的前提"
    )

    for stem in "甲乙丙丁戊己庚辛壬癸":
        facts = {f.type: f.value for f in flow_facts(chart, "dayun", stem, "子")}
        expected = "有根" if ten_god(day_stem, stem) in hidden_gods else "无根"
        assert facts["dayun_stem_ten_god_root"] == expected, (
            f"日主丙见大运干{stem}（{ten_god(day_stem, stem)}）的有根判定不对"
        )

    # 关键的那一条：癸对丙是正官，藏干里没有，必须是「无根」。
    # 若实现顺手把天干也算进去，这一条立刻变「有根」。
    assert {f.type: f.value for f in flow_facts(chart, "liunian", "癸", "子")}[
        "liunian_stem_ten_god_root"
    ] == "无根"
    # 反向：辛对丙是正财，酉支藏干里有辛，必须是「有根」。
    assert {f.type: f.value for f in flow_facts(chart, "liunian", "辛", "子")}[
        "liunian_stem_ten_god_root"
    ] == "有根"


def test_flow_facts_reject_an_unknown_axis():
    """轴名写错不能静默产出一堆没人读的事实键。"""
    chart = chart_of((1990, 2, 1, 12))
    for bad in ("liuyue", "流年", ""):
        try:
            flow_facts(chart, bad, "甲", "子")
        except ValueError:
            continue
        raise AssertionError(f"轴名 {bad!r} 应当被拒")


def test_relation_signals_name_the_natal_pillar_they_touch():
    """「冲的是哪一支」必须保留 —— 冲日支与冲年支是实质不同的两件事。"""
    chart = chart_of((1990, 2, 1, 12))  # 四支 巳丑酉午
    pairs = [
        f.value for f in flow_facts(chart, "liunian", "庚", "午")
        if f.type == "liunian_relation_pairs"
    ]
    assert pairs == ["六害丑（month支）"], pairs


# ── 主题过滤 ───────────────────────────────────────────────────────────


def test_topic_filtering_keeps_only_the_relevant_god_group():
    """问财运时不该冒出官星信号 —— 但地支关系必须留下。"""
    chart = chart_of((1990, 2, 1, 12))
    for window in analyze_period(chart, 2024, 2028, "财运"):
        for signal in window.signals:
            if signal.kind.endswith("relation_pairs"):
                continue
            assert any(group in signal.name for group in TOPIC_TEN_GODS["wealth"]), (
                f"{window.year} 年冒出与财运无关的信号 {signal.name}"
            )


def test_relation_signals_survive_every_topic():
    """冲太岁与问什么无关。

    按主题把它筛掉，等于让同一个结构事实在某些主题下消失 —— 而它的存在
    不取决于用户问的是财运还是事业。验法是取一个**确实有**关系信号的年份，
    看它在每个主题下都还在；不是断言每年都有（2025 乙巳对这张盘就没有）。
    """
    chart = chart_of((1990, 2, 1, 12))
    with_relations = [
        window.year for window in analyze_period(chart, 2024, 2028, "结构")
        if any(s.kind.endswith("relation_pairs") for s in window.signals)
    ]
    assert with_relations, "该区间内应有至少一年带地支关系信号"

    for year in with_relations:
        baseline = {
            s.name for s in analyze_period(chart, year, year, "结构")[0].signals
            if s.kind.endswith("relation_pairs")
        }
        assert baseline
        for topic in ("财运", "事业", "婚姻", "健康"):
            kept = {
                s.name for s in analyze_period(chart, year, year, topic)[0].signals
                if s.kind.endswith("relation_pairs")
            }
            assert kept == baseline, f"{year} 年在 {topic} 主题下丢了 {baseline - kept}"


def test_every_topic_in_the_table_is_a_registered_topic():
    """:data:`TOPIC_TEN_GODS` 里的键必须是已登记主题。

    拼错一个字母不会抛异常，只会让那个主题永远走默认分组 ——
    而「走了默认分组」这件事没有任何测试会发现。
    """
    from knowledge.topics import known_topic_ids

    known = known_topic_ids()
    unknown = set(TOPIC_TEN_GODS) - known
    assert unknown == set(), f"主题映射里有未登记的主题：{sorted(unknown)}"


def test_every_ten_god_has_a_signal_group():
    """十个十神必须都有信号分组。

    漏一个不会报错，只会让那个十神以原名当信号输出 —— 于是报告里
    同时出现「财星入命」和「正官入命」两种粒度，而读者无从知道
    前者是分过组的、后者是漏了映射的。
    """
    missing = set(TEN_GODS) - set(GOD_SIGNAL)
    assert missing == set(), f"这些十神没有信号分组：{sorted(missing)}"
    assert set(GOD_SIGNAL) <= set(TEN_GODS), "信号分组里有不是十神的名目"
    assert set(GOD_SIGNAL.values()) <= {
        group for groups in TOPIC_TEN_GODS.values() for group in groups
    }, "有信号分组没被任何主题收录"


# ── 不做预测 ───────────────────────────────────────────────────────────


def test_report_never_asserts_a_prediction():
    """报告里不得出现必然性措辞。

    这不是文风检查，是产出物的性质检查：整份报告的每个词都必须能被
    信号本身支撑。出现「会」「一定」「必将」就意味着有人在拿结构描述
    下判断。
    """
    banned = ("一定会", "必将", "必定", "肯定会", "必然会", "一定会")
    chart = chart_of((1990, 2, 1, 12), gender="男")
    for window in analyze_period(chart, 2020, 2035, "财运",
                                 dayun_policy=ClassicalApproxDayunPolicy()):
        report = window.to_report()
        for phrase in banned:
            assert phrase not in report, f"{window.year} 年报告含必然性措辞：{report}"


def test_a_year_without_signals_reports_absence_not_calm():
    """没有信号的年份报「无显著结构信号」，不报「平稳无事」。

    后者是一句判断 —— 它断言了「没事」，而我们并没有检验过「没事」。
    """
    chart = chart_of((1975, 8, 8, 10))
    empty = [w for w in analyze_period(chart, 2024, 2030, "财运") if not w.signals]
    assert empty, "这个区间内应当有至少一年没有任何信号"
    for window in empty:
        report = window.to_report()
        assert "无显著结构信号" in report
        assert "平稳" not in report and "无事" not in report


# ── 强度：与本命盘同一算式 ─────────────────────────────────────────────


def test_time_window_strength_uses_the_shared_kernel():
    """时间轴的强度必须走 :func:`knowledge.evidence.score_support` 的内核。

    「本命局 0.62，2028 年 0.48」这句话要有意义，前提是两边的数字是同一种
    东西。所以验的不是「数值上凑得齐」，而是**调的是同一个函数**：
    这里拿信号的置信度直接喂 ``score_support``，结果必须与窗口的
    ``breakdown`` 逐字段相同。

    早先这测试试图把 0.6 置信度的信号折算成整数个 MEDIUM 规则再对拍，
    折算里的 ``round`` 直接毁掉了精度 —— 那是测试在验一件做不到的事。
    """
    chart = chart_of((1990, 2, 1, 12))
    window = analyze_period(chart, 2028, 2028, "结构")[0]
    assert window.signals

    from knowledge.evidence import score_support

    expected = score_support(tuple(SIGNAL_CONFIDENCE for _ in window.signals), 0)
    assert window.breakdown == expected


def test_score_strength_delegates_to_the_same_kernel():
    """规则口径与信号口径必须同源 —— 否则两个层的强度数字不可比。"""
    from knowledge.evidence import CONFIDENCE_SCORES, score_strength, score_support

    class _Rule:
        confidence = "MEDIUM"

    class _Match:
        def __init__(self, rule):
            self.rule = rule

    matches = tuple(_Match(_Rule()) for _ in range(3))
    assert score_strength(matches, ()) == score_support(
        tuple(CONFIDENCE_SCORES["MEDIUM"] for _ in matches), 0
    )


# ── 大运的显式边界 ─────────────────────────────────────────────────────


def test_dayun_is_not_computed_without_a_policy():
    """不选流派就不算大运 —— 顺逆规则不同流派有分歧，不猜默认值。"""
    chart = chart_of((1990, 2, 1, 12))
    window = analyze_period(chart, 2024, 2024, "财运")[0]
    assert window.dayun is None
    assert all(signal.axis == "liunian" for signal in window.signals)


def test_dayun_requires_gender_and_says_so():
    """缺性别时报错要说清为什么，不能只是抛一个裸 ValueError。"""
    chart = chart_of((1990, 2, 1, 12))  # 未传 gender
    try:
        analyze_period(chart, 2024, 2024, "财运",
                       dayun_policy=ClassicalApproxDayunPolicy())
    except ValueError as error:
        assert "gender" in str(error)
    else:
        raise AssertionError("缺性别时应当报错")


def test_unspecified_policy_is_skipped_rather_than_raised():
    """未选流派的策略静默跳过，而不是让整段分析失败。

    「今年没有大运信息」是一个合法的部分结果；为了它把整个区间
    的分析判失败，是拿严格换可用性。
    """
    chart = chart_of((1990, 2, 1, 12))
    window = analyze_period(chart, 2024, 2024, "财运", dayun_policy=DayunPolicy())[0]
    assert window.dayun is None


def test_the_dayun_in_effect_spans_ten_years():
    """同一步大运覆盖连续的十年，跨步不重叠也不留空。"""
    chart = chart_of((1990, 2, 1, 12), gender="男")
    windows = analyze_period(chart, 2000, 2070, "财运",
                             dayun_policy=ClassicalApproxDayunPolicy())
    covered = [w for w in windows if w.dayun is not None]
    assert covered, "七十年内应当有大运生效的年份"

    runs: dict[str, list[int]] = {}
    for window in covered:
        key = str(window.dayun["heavenly_stem"]) + str(window.dayun["earthly_branch"])
        runs.setdefault(key, []).append(window.year)

    for key, years in runs.items():
        assert years == list(range(years[0], years[-1] + 1)), f"大运 {key} 的年份不连续"
        assert len(years) <= 10, f"大运 {key} 覆盖了 {len(years)} 年，超过十年"


# ── 边界与可回溯 ───────────────────────────────────────────────────────


def test_analyze_period_rejects_a_reverse_range():
    chart = chart_of((1990, 2, 1, 12))
    try:
        analyze_period(chart, 2030, 2020, "财运")
    except ValueError as error:
        assert "start_year" in str(error)
    else:
        raise AssertionError("反向区间应当被拒")


def test_every_signal_carries_a_source_and_a_detail():
    """没有 source 的信号不可回溯 —— 那是把「信号」当成了结论。"""
    chart = chart_of((1990, 2, 1, 12), gender="男")
    for window in analyze_period(chart, 2020, 2030, "财运",
                                 dayun_policy=ClassicalApproxDayunPolicy()):
        for signal in window.signals:
            assert signal.source.startswith("time."), f"{signal.name} 的 source 不可回溯"
            assert signal.detail.strip(), f"{signal.name} 没有说明"


def test_to_dict_round_trips_the_report():
    """序列化产物必须自带报告文本，否则下游各自拼一次就会拼出不同的话。"""
    chart = chart_of((1990, 2, 1, 12))
    window = analyze_period(chart, 2028, 2028, "财运")[0]
    payload = window.to_dict()
    assert payload["report"] == window.to_report()
    assert payload["year"] == 2028
    assert payload["topic"] == "wealth"
    assert isinstance(payload["signals"], list)

"""Phase 2：结构层规则库测试。

这一组测试守的是「规则库不能是摆设」。一条条件键拼错、或者条件永远不可能
成立的规则，不会报错，只会永远静默地匹配不上 —— 死规则比错规则更难发现。
所以这里用两个角度把它钉死：

1. **静态**：每条规则的条件键必须存在于事实词表 :data:`FACT_SCHEMA`。
2. **动态**：每条规则必须有一张**真实命盘**能命中它（见证命盘），并在测试
   运行时重新验证一遍。新增规则时若不补见证，测试直接失败。
"""

from engines.bazi import BirthInput, SxtwlBaziProvider
from knowledge.classical_backlog import CLASSICAL_BACKLOG, BacklogStatus, next_action
from knowledge.default_rules import default_registry, default_schools
from knowledge.evidence import (
    CONFIDENCE_SCORES,
    CONFLICT_PENALTY,
    FACT_SCHEMA,
    build_evidence,
    extract_facts,
    group_facts,
)
from knowledge.provenance import ReviewStatus, SourceTier
from knowledge.schools import STRUCTURAL_SCHOOL
from knowledge.structural_rules import ELEMENTS, PATTERN_TEN_GODS, RELATIONS, TEN_GODS

PROVIDER = SxtwlBaziProvider()

PHASE_TWO_MINIMUM_RULES = 50
"""MINGLI_PLAN.md Phase 2 验收标准 1：至少 50 条规则录入。"""


def matched_rule_ids(year: int, month: int, day: int, hour: int) -> set[str]:
    chart = PROVIDER.calculate(BirthInput(year, month, day, hour))
    return {match.rule.id for match in default_registry().match(group_facts(extract_facts(chart)))}


# ── 规模与来源 ─────────────────────────────────────────────────────────


def test_rule_library_meets_the_phase_two_minimum():
    assert len(default_registry().select()) >= PHASE_TWO_MINIMUM_RULES


def test_every_rule_declares_source_school_category_and_topic():
    schools = default_schools()

    for rule in default_registry().select():
        assert rule.source.strip(), f"{rule.id} 缺少来源"
        assert rule.category.strip(), f"{rule.id} 缺少类别"
        assert rule.topic.strip(), f"{rule.id} 缺少主题"
        assert schools.has(rule.school), f"{rule.id} 挂在未注册流派 {rule.school}"


def test_every_rule_condition_key_exists_in_the_fact_schema():
    unknown = default_registry().condition_keys() - set(FACT_SCHEMA)

    assert unknown == set(), f"规则引用了不存在的事实键：{sorted(unknown)}"


def test_rule_library_is_structural_only_for_now():
    """典籍层当前一条都没有 —— 这是刻意的，不是遗漏。

    在底本确认之前录入断语就等于编造典籍。这条测试把「当前状态」钉住，
    等典籍层真正开始录入时，它会失败并提醒作者同步更新来源治理文档。
    """
    rules = default_registry().select()

    assert {rule.source_tier for rule in rules} == {SourceTier.STRUCTURAL}
    assert {rule.review_status for rule in rules} == {ReviewStatus.ACTIVE}
    assert {rule.school for rule in rules} == {STRUCTURAL_SCHOOL}
    assert all(rule.citation is None for rule in rules)


def test_rule_ids_are_unique_and_prefixed():
    rules = default_registry().select()
    ids = [rule.id for rule in rules]

    assert len(ids) == len(set(ids))
    assert all(rule_id.startswith("STRUCT_") for rule_id in ids)


def test_rule_versions_are_declared():
    assert all(rule.version.strip() for rule in default_registry().select())


# ── 覆盖面：该有的规则都要有 ───────────────────────────────────────────


def test_ten_god_rules_cover_all_ten_gods_for_root_and_void():
    rules = default_registry()
    rooted = {rule.condition["ten_god_with_root"] for rule in rules.select(category="ten_god")
              if "ten_god_with_root" in rule.condition}
    void = {rule.condition["ten_god_without_root"] for rule in rules.select(category="ten_god")
            if "ten_god_without_root" in rule.condition}

    assert rooted == set(TEN_GODS)
    assert void == set(TEN_GODS)


def test_pattern_rules_cover_the_eight_patterns_in_both_methods():
    rules = default_registry()
    by_main = {rule.condition["month_branch_ten_god"] for rule in rules.select(category="pattern")
               if "month_branch_ten_god" in rule.condition}
    by_transparent = {
        rule.condition["month_branch_extended_ten_god"]
        for rule in rules.select(category="pattern")
        if "month_branch_extended_ten_god" in rule.condition
    }

    assert by_transparent == set(PATTERN_TEN_GODS)
    # 本气定格法还要覆盖比肩（建禄）与劫财（月刃）
    assert by_main == set(TEN_GODS)


def test_relation_rules_cover_every_relation_type():
    covered = {
        rule.condition["has_relation"]
        for rule in default_registry().select(category="relation")
        if "has_relation" in rule.condition
    }

    assert covered == set(RELATIONS)


def test_element_rules_cover_every_element_for_missing_and_dominant():
    rules = default_registry().select(category="element")
    missing = {rule.condition["missing_elements"] for rule in rules if "missing_elements" in rule.condition}
    dominant = {rule.condition["dominant_elements"] for rule in rules if "dominant_elements" in rule.condition}

    assert missing == set(ELEMENTS)
    assert dominant == set(ELEMENTS)


# ── 动态可达性：每条规则都要有真实命盘能命中 ────────────────────────────


def test_every_rule_has_a_witness_chart():
    missing = sorted({rule.id for rule in default_registry().select()} - set(RULE_WITNESS))

    assert missing == [], (
        "以下规则没有任何见证命盘，属于死规则："
        f"{missing}。新增规则后必须补一张能命中它的真实命盘。"
    )


def test_witness_charts_actually_match_their_rule():
    for rule_id, (year, month, day, hour) in sorted(RULE_WITNESS.items()):
        assert rule_id in matched_rule_ids(year, month, day, hour), (
            f"见证命盘 {year}-{month}-{day} {hour}时 命中不了 {rule_id}"
        )


# ── 冲突：值级比较，不误报 ─────────────────────────────────────────────
#
# 用两张真实命盘对照：
#   1990-02-01 12:00 → 月支本气与透干都是「食神」，两法一致，不该报冲突
#   1990-01-09 14:00 → 月支本气是「正财」，藏干里还有「正官」透干，
#                      两法给出不同格局名，必须报冲突


AGREEING_BIRTH = (1990, 2, 1, 12)
DISAGREEING_BIRTH = (1990, 1, 9, 14)


def evidence_for(birth: tuple[int, int, int, int]):
    return build_evidence(PROVIDER.calculate(BirthInput(*birth)), default_registry())


def test_two_pattern_methods_agreeing_is_not_reported_as_conflict():
    """本气与透干给出同一个格局名时没有分歧。"""
    evidence = evidence_for(AGREEING_BIRTH)
    matched = {match.rule.id for match in evidence.matches}

    assert {"STRUCT_PATTERN_001", "STRUCT_PATTERN_EXT_001"} <= matched
    assert evidence.conflicts == ()
    assert evidence.conflict_notes == ()


def test_two_pattern_methods_disagreeing_is_reported_as_conflict():
    """两法给出不同格局名时必须并列披露，且说明具体分歧在哪。"""
    evidence = evidence_for(DISAGREEING_BIRTH)
    conflicting_ids = {rule_id for pair in evidence.conflicts for rule_id in pair}

    assert evidence.conflicts, "该命盘两法结论不同，应报冲突"
    assert {"STRUCT_PATTERN_004", "STRUCT_PATTERN_EXT_006"} <= conflicting_ids
    assert evidence.conflict_notes
    assert "pattern_name" in evidence.conflict_notes[0]
    assert "正财格" in evidence.conflict_notes[0]
    assert "正官格" in evidence.conflict_notes[0]


def test_conflicts_reduce_evidence_strength():
    evidence = evidence_for(DISAGREEING_BIRTH)
    base = sum(
        CONFIDENCE_SCORES[match.rule.confidence] for match in evidence.matches
    ) / len(evidence.matches)

    assert evidence.conflicts
    assert evidence.strength == round(base - CONFLICT_PENALTY * len(evidence.conflicts), 4)
    assert evidence.strength < round(base, 4)


# ── 证据链完整性 ───────────────────────────────────────────────────────


def test_evidence_reports_no_unreviewed_rules_for_the_current_library():
    evidence = build_evidence(
        PROVIDER.calculate(BirthInput(1990, 2, 1, 12)), default_registry()
    )

    assert evidence.unreviewed_rule_ids == ()


def test_evidence_serialises_provenance_for_every_matched_rule():
    evidence = build_evidence(
        PROVIDER.calculate(BirthInput(1990, 2, 1, 12)), default_registry()
    )
    payload = evidence.to_dict()

    assert len(payload["rule_provenance"]) == len(evidence.matches)
    for item in payload["rule_provenance"]:
        assert item["school"] == STRUCTURAL_SCHOOL
        assert item["source_tier"] == "structural"
        assert item["review_status"] == "ACTIVE"


def test_fact_schema_and_extractor_stay_in_sync():
    """事实词表不能出现「声明了但没人产出」的键。

    反向不要求完全相等：``has_relation`` 这类键只有在命盘确实存在对应结构时
    才会产出，某一张命盘缺它是正常的。
    """
    produced = {fact.type for fact in extract_facts(PROVIDER.calculate(BirthInput(1990, 2, 1, 12)))}
    declared = set(FACT_SCHEMA)

    assert produced <= declared, f"提取器产出了词表里没有的键：{sorted(produced - declared)}"
    assert len(produced) >= len(declared) - 2, (
        f"词表声明了 {len(declared)} 个键，但这张命盘只产出 {len(produced)} 个；"
        "若某个键从未被任何命盘产出，说明提取器漏了它。"
    )


# ── 典籍层：诚实留白 ───────────────────────────────────────────────────


def test_classical_backlog_is_not_empty_and_every_entry_explains_its_blocker():
    assert CLASSICAL_BACKLOG

    for entry in CLASSICAL_BACKLOG:
        assert entry.blocker.strip(), f"{entry.id} 必须说明阻塞原因"
        assert entry.needed_action.strip(), f"{entry.id} 必须说明下一步动作"
        assert entry.book.strip()


def test_classical_backlog_prioritises_di_tian_sui_first():
    assert next_action().book == "《滴天髓》"


def test_classical_backlog_has_no_ready_entries_yet():
    """当前没有任何一条典籍来源是可录入的 —— 这是 Phase 2 的真实状态。"""
    assert [entry for entry in CLASSICAL_BACKLOG if entry.status is BacklogStatus.READY] == []


def test_legally_blocked_sources_are_distinguished_from_source_blocked_ones():
    statuses = {entry.status for entry in CLASSICAL_BACKLOG}

    assert BacklogStatus.BLOCKED_LEGAL in statuses
    assert BacklogStatus.BLOCKED_SOURCE in statuses


# ── 见证命盘表 ─────────────────────────────────────────────────────────
# 每条规则对应一张真实命盘（年、月、日、时）。由扫描 1950-2030 的命盘生成，
# 并在 test_witness_charts_actually_match_their_rule 中逐条复验。

RULE_WITNESS: dict[str, tuple[int, int, int, int]] = {
    "STRUCT_DM_LEVEL_001": (1990, 1, 5, 0),
    "STRUCT_DM_LEVEL_002": (1990, 1, 1, 0),
    "STRUCT_DM_LEVEL_003": (1990, 1, 1, 4),
    "STRUCT_DM_ROOT_001": (1990, 1, 1, 0),
    "STRUCT_DM_ROOT_002": (1990, 1, 9, 0),
    "STRUCT_ELEMENT_DOM_001": (1990, 1, 13, 4),
    "STRUCT_ELEMENT_DOM_002": (1990, 1, 1, 0),
    "STRUCT_ELEMENT_DOM_003": (1990, 1, 1, 2),
    "STRUCT_ELEMENT_DOM_004": (1990, 2, 5, 4),
    "STRUCT_ELEMENT_DOM_005": (1990, 2, 17, 0),
    "STRUCT_ELEMENT_MISS_001": (1990, 1, 5, 0),
    "STRUCT_ELEMENT_MISS_002": (1975, 2, 13, 4),
    "STRUCT_ELEMENT_MISS_003": (1990, 5, 17, 0),
    "STRUCT_ELEMENT_MISS_004": (1990, 1, 1, 0),
    "STRUCT_ELEMENT_MISS_005": (1990, 1, 9, 2),
    "STRUCT_JIANLU_001": (1990, 3, 21, 0),
    "STRUCT_MONTH_001": (1990, 1, 13, 0),
    "STRUCT_MONTH_002": (1990, 1, 25, 0),
    "STRUCT_MONTH_003": (1990, 1, 5, 0),
    "STRUCT_MONTH_004": (1990, 1, 9, 0),
    "STRUCT_MONTH_005": (1990, 1, 1, 0),
    "STRUCT_PATTERN_001": (1990, 2, 1, 0),
    "STRUCT_PATTERN_002": (1990, 1, 5, 0),
    "STRUCT_PATTERN_003": (1990, 3, 17, 0),
    "STRUCT_PATTERN_004": (1990, 1, 9, 0),
    "STRUCT_PATTERN_005": (1990, 3, 25, 0),
    "STRUCT_PATTERN_006": (1990, 1, 1, 0),
    "STRUCT_PATTERN_007": (1990, 3, 13, 0),
    "STRUCT_PATTERN_008": (1990, 1, 25, 0),
    "STRUCT_PATTERN_EXT_001": (1990, 2, 1, 0),
    "STRUCT_PATTERN_EXT_002": (1990, 1, 5, 14),
    "STRUCT_PATTERN_EXT_003": (1990, 2, 1, 2),
    "STRUCT_PATTERN_EXT_004": (1990, 1, 9, 0),
    "STRUCT_PATTERN_EXT_005": (1990, 2, 1, 6),
    "STRUCT_PATTERN_EXT_006": (1990, 1, 1, 10),
    "STRUCT_PATTERN_EXT_007": (1990, 3, 13, 10),
    "STRUCT_PATTERN_EXT_008": (1990, 1, 9, 18),
    "STRUCT_RELATION_001": (1990, 1, 1, 12),
    "STRUCT_RELATION_002": (1990, 1, 1, 2),
    "STRUCT_RELATION_003": (1990, 1, 1, 0),
    "STRUCT_RELATION_004": (1990, 1, 1, 16),
    "STRUCT_RELATION_005": (1990, 1, 5, 12),
    "STRUCT_RELATION_006": (1990, 1, 1, 16),
    "STRUCT_RELATION_DENSITY_001": (1990, 1, 9, 2),
    "STRUCT_RELATION_DENSITY_002": (1990, 1, 1, 0),
    "STRUCT_RELATION_DENSITY_003": (1990, 1, 1, 16),
    "STRUCT_ROOT_001": (1990, 1, 1, 0),
    "STRUCT_ROOT_002": (1990, 1, 13, 0),
    "STRUCT_ROOT_003": (1990, 1, 1, 0),
    "STRUCT_ROOT_004": (1990, 1, 1, 2),
    "STRUCT_ROOT_005": (1990, 1, 1, 4),
    "STRUCT_ROOT_006": (1990, 1, 9, 0),
    "STRUCT_ROOT_007": (1990, 1, 5, 0),
    "STRUCT_ROOT_008": (1990, 1, 1, 10),
    "STRUCT_ROOT_009": (1990, 1, 1, 12),
    "STRUCT_ROOT_010": (1990, 1, 1, 14),
    "STRUCT_TEN_GOD_001": (1990, 1, 25, 0),
    "STRUCT_VOID_001": (1990, 1, 9, 0),
    "STRUCT_VOID_002": (1990, 1, 1, 18),
    "STRUCT_VOID_003": (1990, 1, 5, 12),
    "STRUCT_VOID_004": (1990, 1, 1, 0),
    "STRUCT_VOID_005": (1990, 1, 5, 16),
    "STRUCT_VOID_006": (1990, 1, 1, 6),
    "STRUCT_VOID_007": (1990, 1, 1, 8),
    "STRUCT_VOID_008": (1990, 1, 25, 0),
    "STRUCT_VOID_009": (1990, 1, 21, 12),
    "STRUCT_VOID_010": (1990, 1, 13, 0),
    "STRUCT_YUEREN_001": (1990, 1, 13, 0),
}

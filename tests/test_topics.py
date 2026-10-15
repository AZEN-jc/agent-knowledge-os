"""Phase 3：主题覆盖测试。

守的是一条诚实性约束：**结构层规则不许冒充主题结论**。

原实现里 ``build_evidence(chart, registry, topic="事业")`` 把全部 68 条结构规则
都标成「事业」主题输出 —— 用户会看到一份题为「事业」、内容却是十神与地支结构
的报告。这组测试把它钉死：主题没有专属规则时，必须报 ``base_only`` 并明说
「不构成对该主题的判断」。
"""

import pytest

from engines.bazi import BirthInput, SxtwlBaziProvider
from knowledge.default_rules import default_registry
from knowledge.evidence import build_evidence
from knowledge.provenance import ReviewStatus, SourceTier
from knowledge.rules import Rule, RuleRegistry
from knowledge.schools import STRUCTURAL_SCHOOL
from knowledge.topics import (
    STRUCTURAL_TOPIC,
    TOPICS,
    TopicStatus,
    is_registered,
    known_topic_ids,
    resolve,
    status_for,
)

PROVIDER = SxtwlBaziProvider()


def chart():
    return PROVIDER.calculate(BirthInput(1990, 2, 1, 12))


# ── 主题注册表 ─────────────────────────────────────────────────────────


def test_every_topic_has_a_unique_id_and_a_readable_name():
    ids = [topic.id for topic in TOPICS]

    assert len(ids) == len(set(ids))
    for topic in TOPICS:
        assert topic.name.strip(), f"{topic.id} 缺少中文名"
        assert topic.description.strip(), f"{topic.id} 缺少说明"


def test_resolve_accepts_both_ids_and_chinese_aliases():
    assert resolve("career").id == "career"
    assert resolve("事业").id == "career"
    assert resolve("工作").id == "career"
    assert resolve(STRUCTURAL_TOPIC).id == STRUCTURAL_TOPIC


def test_unknown_topic_resolves_to_itself_without_raising():
    """未登记的主题不报错 —— 用户仍应拿到结构层证据，只是没有主题层。"""
    resolved = resolve("炒股能不能发财")

    assert resolved.id == "炒股能不能发财"
    assert not is_registered(resolved.id)


def test_only_topics_with_rules_can_be_covered():
    """登记了名字但一条规则都没有的主题，必须报 base_only。

    这一条防的是「挂个名字就算覆盖」—— 覆盖状态的依据是**规则命中数**，
    不是主题表里有没有这一行。
    """
    assert status_for(resolve("career"), 0) is TopicStatus.BASE_ONLY
    assert status_for(resolve("career"), 3) is TopicStatus.COVERED
    assert status_for(resolve("没登记过"), 0) is TopicStatus.UNKNOWN


# ── 与证据层的联动 ─────────────────────────────────────────────────────


def test_structural_topic_is_covered_by_the_current_library():
    evidence = build_evidence(chart(), default_registry(), topic=STRUCTURAL_TOPIC)

    assert evidence.status is TopicStatus.COVERED
    assert evidence.domain_matches
    assert evidence.topic_id == STRUCTURAL_TOPIC


def test_career_question_is_not_labelled_as_a_career_conclusion():
    """回归：问「事业」不能拿到一份自称是事业结论的结构层报告。"""
    evidence = build_evidence(chart(), default_registry(), topic="事业")

    assert evidence.topic == "事业"
    assert evidence.topic_id == "career"
    assert evidence.status is TopicStatus.BASE_ONLY
    assert evidence.domain_matches == ()
    # 基础层照常给，不能因为主题没规则就什么都不给
    assert evidence.base_matches
    assert "事业" in evidence.coverage_note
    assert "不构成" in evidence.coverage_note


def test_every_rule_sits_on_a_registered_topic():
    """每条规则都必须挂在已登记主题上，且主题与层级对得上。

    上一版断言「全部规则都在 structure 主题上」—— 那在只有结构层时成立，
    Phase 5 录了 destiny 主题的典籍断语之后就不再成立。要守的不变式其实是
    「主题是登记过的，不是随手写的字符串」，与 ``validate_topics`` 同一口径。

    这里额外钉一条分层纪律：**结构层规则不许挂在领域主题上**。
    结构规则不区分事业/婚姻，它能被任何主题选中当背景；一旦给它贴上
    「婚姻」标签，它就会以「婚姻规则」的身份出现在结论里。
    """
    known = known_topic_ids()
    rules = default_registry().select()

    assert {rule.topic for rule in rules} <= set(known)
    for rule in rules:
        if rule.source_tier is SourceTier.STRUCTURAL:
            assert rule.topic == STRUCTURAL_TOPIC, (
                f"{rule.id} 是结构层规则，却挂在领域主题 {rule.topic} 上"
            )


def test_the_destiny_topic_is_covered_by_real_classical_rules():
    """destiny 主题不再空 —— 这是 Phase 5 的交付物本身。

    写死「有几条」没有意义（底本会继续录），要守的是**它确实通了**：
    问「命局」拿到 covered，且命中的是带 URN 的典籍规则，而不是结构层充数。

    命盘取 1980-02-21 00:00（日柱甲子、时柱甲子），命中《三命通會》卷八
    「甲子日甲子时」那一条。同一张盘也用作该规则的见证命盘。
    """
    destiny = PROVIDER.calculate(BirthInput(1980, 2, 21, 0))
    evidence = build_evidence(destiny, default_registry(), topic="命局")

    assert evidence.topic_id == "destiny"
    assert evidence.status is TopicStatus.COVERED
    assert evidence.domain_matches
    assert all(match.rule.urn for match in evidence.domain_matches)
    assert all(
        match.rule.source_tier is SourceTier.CLASSICAL
        for match in evidence.domain_matches
    )


def test_domain_rules_are_selected_when_the_topic_has_them():
    """一旦某个主题有了规则，它就该出现在 domain_matches 里。

    当前规则库没有 career 规则，所以这里手工造一条，验证通路是通的 ——
    否则「主题层永远为空」这件事就分不清是设计如此还是根本没接上。
    """
    registry = default_registry()
    registry.add(Rule(
        id="CAREER_DEMO_001",
        source="测试用占位规则",
        school=STRUCTURAL_SCHOOL,
        category="ten_god",
        topic="career",
        condition={"day_master_root": "有根"},
        conclusion="占位结论，仅用于验证主题层通路。",
        confidence="MEDIUM",
        review_status=ReviewStatus.REVIEWED,
    ))

    evidence = build_evidence(chart(), registry, topic="career")

    assert evidence.status is TopicStatus.COVERED
    assert [match.rule.id for match in evidence.domain_matches] == ["CAREER_DEMO_001"]
    assert len(evidence.matches) == len(evidence.base_matches) + 1


def test_assembly_rejects_rules_on_unregistered_topics():
    registry = RuleRegistry()
    registry.add(Rule(
        id="STRAY_001",
        source="来源",
        school=STRUCTURAL_SCHOOL,
        category="ten_god",
        topic="没登记过的主题",
        condition={"day_master_root": "有根"},
        conclusion="结论。",
    ))

    with pytest.raises(ValueError, match="未登记的主题"):
        registry.validate_topics(known_topic_ids())


def test_evidence_serialises_the_topic_decision():
    payload = build_evidence(chart(), default_registry(), topic="事业").to_dict()

    assert payload["topic"] == "事业"
    assert payload["topic_id"] == "career"
    assert payload["status"] == "base_only"
    assert payload["domain_rules"] == []
    assert payload["base_rules"]

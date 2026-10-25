"""可读性层：术语表与条件人话的守卫（Phase 6.1）。

## 这个文件守什么

1. **没有黑话漏网**：`FACT_SCHEMA` 里每个键都必须有中文模板。词表加了新键
   却忘了写人话，读者看到的就又是一串 `chart.pillars[*].hidden_stems`。
2. **翻译不许滑成判断**：模板里出现「吉/凶/富贵/克妻」这类词，说明它已经
   不是翻译了 —— 那是断语的职责，且断语必须有底本原文。
3. **术语表要覆盖十个十神**：十神是整套输出的最小词汇单位，缺一个就有
   一条结论读不懂。
"""

from __future__ import annotations

import re

import pytest

from knowledge.explain import (
    FORBIDDEN_IN_EXPLANATION,
    GLOSSARY,
    TEMPLATES,
    explain_condition,
    explain_evidence,
    explain_status,
    explain_strength,
)
from knowledge.facts import FACT_SCHEMA

#: 常见的实际取值，用来跑每个模板一遍。不放 None —— 计数类模板里 None
#: 不是合法值，拿它当样本只会测出「样本不合理」。None 的处理单独测。
SAMPLE_VALUES: tuple[object, ...] = ("甲", "正官", 3, ["水"], ("六冲",), [], True)


# ── 覆盖性 ─────────────────────────────────────────────────────────────


def test_every_fact_key_has_a_plain_language_template():
    missing = sorted(set(FACT_SCHEMA) - set(TEMPLATES))
    assert not missing, (
        "以下事实键没有中文模板，读者只会看到字段名：\n  " + "\n  ".join(missing)
    )


def test_every_template_key_is_a_real_fact_key():
    """反向：模板不能指向不存在的键（词表改名后模板会烂在这里）。"""
    extra = sorted(set(TEMPLATES) - set(FACT_SCHEMA))
    assert not extra, f"模板里有词表不存在的键：{extra}"


def test_every_ten_god_has_a_glossary_entry():
    terms = {entry["term"] for entry in GLOSSARY}
    for god in ("比肩", "劫财", "食神", "伤官", "偏财", "正财", "七杀", "正官", "偏印", "正印"):
        assert any(god in term for term in terms), f"术语表缺十神：{god}"


def test_glossary_entries_are_complete():
    for entry in GLOSSARY:
        assert entry.get("term"), "词条缺 term"
        assert entry.get("plain"), f"{entry.get('term')} 缺解释"


# ── 可读性 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("key", sorted(TEMPLATES))
def test_template_renders_without_placeholders_or_empty_text(key):
    for actual in SAMPLE_VALUES:
        text = explain_condition(key, actual, actual)
        assert text and text.strip(), f"{key} 在 actual={actual!r} 时输出为空"
        assert "{" not in text and "}" not in text, f"{key} 有未替换的占位符：{text}"
        assert "None" not in text, f"{key} 把 None 直接写进了句子：{text}"


@pytest.mark.parametrize("key", sorted(TEMPLATES))
def test_templates_do_not_slip_into_judgement(key):
    """翻译层不许出现吉凶判断词 —— 那是断语的职责。"""
    for actual in SAMPLE_VALUES:
        text = explain_condition(key, actual, actual)
        for word in FORBIDDEN_IN_EXPLANATION:
            assert word not in text, f"{key} 的解释里出现了判断词「{word}」：{text}"


def test_glossary_definitions_do_not_judge():
    for entry in GLOSSARY:
        for word in FORBIDDEN_IN_EXPLANATION:
            assert word not in entry["plain"], (
                f"术语「{entry['term']}」的定义里出现判断词「{word}」"
            )


def test_condition_explanations_are_readable_sentences():
    """至少要有句号、有中文，且不是字段名直出。"""
    text = explain_condition("ten_god_with_root", "偏财", ["偏财", "比肩"])
    assert text.endswith("。")
    assert "偏财" in text
    assert re.search(r"[\u4e00-\u9fff]", text)
    # 不是「ten_god_with_root：偏财」这种字段名直出
    assert "ten_god_with_root" not in text


def test_none_renders_as_a_chinese_word_not_the_literal_none():
    """空值不能把英文 None 直接写进句子。"""
    from knowledge.explain import _fmt

    assert _fmt(None) == "空"
    assert "None" not in explain_condition("missing_elements", ["水"], None)


# ── 强度与覆盖状态 ─────────────────────────────────────────────────────


def test_strength_explanation_says_it_is_not_a_probability():
    text = explain_strength(0.77, {"supporting_rules": 11, "raw_support": 9.8})
    assert "11" in text and "0.77" in text
    assert "不是" in text and "概率" in text


def test_status_explanation_is_plain_for_every_status():
    for status in ("covered", "base_only", "unknown"):
        text = explain_status(status)
        assert text and text.endswith("。")
        assert "coverage_note" not in text
    # base_only 必须说清「不构成对这个主题的判断」
    assert "不构成" in explain_status("base_only")


def test_evidence_explanation_counts_chain_and_classical_links():
    """用真实形状的替身：Evidence.matches 里是 RuleMatch，典籍层 rule.urn 非空。"""

    class _Rule:
        def __init__(self, urn):
            self.urn = urn

    class _Match:
        def __init__(self, urn):
            self.rule = _Rule(urn)

    class _Evidence:
        status = "base_only"
        topic_name = "事业"
        matches = (_Match(None), _Match(None), _Match("urn:divination:bazi:x:1:a.b.c"))

    text = explain_evidence(_Evidence())
    assert "3 条规则" in text
    assert "1 条有典籍原文" in text
    assert "不构成" in text


def test_evidence_explanation_handles_empty_chain():
    class _Evidence:
        status = "base_only"
        topic_name = "事业"
        matches = ()

    assert "没有命中任何规则" in explain_evidence(_Evidence())


# ── 变异探针：新键漏写模板必须被抓 ─────────────────────────────────────


def test_a_new_fact_key_without_template_is_caught(monkeypatch):
    """模拟「加了词表键但忘了写人话」——这条测试必须红。"""
    import knowledge.explain as explain_module

    monkeypatch.setitem(FACT_SCHEMA, "brand_new_fact", "新加的事实")
    missing = sorted(set(FACT_SCHEMA) - set(explain_module.TEMPLATES))
    assert "brand_new_fact" in missing

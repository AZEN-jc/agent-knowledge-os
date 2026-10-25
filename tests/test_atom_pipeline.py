"""录入流水线的账本（Phase 6.2）。

## 这个文件守什么

卷八有 60 个「某日某时断」小节、360 个条目。录入之前必须先在机器上
**对得上账**，否则漏条不会报错 —— 只是那一节少几条原子，而没人知道
少了几条。

两个真实缺陷（都已核实，不是假设）：

1. `juan8.txt:1044` 有一句诗「明出地上宜為大明君也」，与章节标题同级
   （都是 `##`），但它属于「六丁日丁未時斷」的正文。按标题级别切分会把
   该节从中间截断，**1 条而不是 6 条**，且不报错。
2. `juan8.txt:1075`「丁己日戊申時」是「丁巳日」的转录误字：己是天干，
   不可能出现在日柱地支位。只认干支的正则会整条漏掉，**5 条而不是 6 条**。

修法都写在 `layout.json` 里（吸收哪个标题、哪个字是误字），脚本消费它，
**不改底本一个字** —— 引文必须逐字回对。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from extract_atoms import (  # noqa: E402
    audit_sections,
    iter_sections,
    load_layout,
    section_body,
    split_entries,
)

from knowledge.corpus import load_corpus  # noqa: E402

CORPUS_ID = "bazi_sanmingtonghui_j8"


@pytest.fixture(scope="module")
def corpus_text() -> str:
    corpus = load_corpus()
    entry = next(item for item in corpus.entries if item.corpus_id == CORPUS_ID)
    return corpus.text(entry)


@pytest.fixture(scope="module")
def layout() -> dict:
    return load_layout()


# ── 账本 ───────────────────────────────────────────────────────────────


def test_the_ledger_closes_at_sixty_sections_and_three_hundred_sixty_entries():
    report = audit_sections(CORPUS_ID)

    assert report["total_sections"] == 60, "卷八应有 60 个「某日某时断」小节"
    assert report["total_entries"] == 360, "每节 6 个条目，共 360"
    assert report["unexplained"] == [], (
        "有未登记的缺条："
        + "；".join(f"{row['section']} {row['found']}/{row['expected']}"
                   for row in report["unexplained"])
    )


def test_every_section_heading_exists_verbatim_in_the_corpus(corpus_text: str):
    """章节标题必须逐字出现在底本里 —— 不许为了好看补字。"""
    headings = iter_sections(corpus_text)
    assert len(headings) == 60
    for heading in headings:
        assert heading in corpus_text


# ── 缺陷 1：诗句标题不得截断章节 ───────────────────────────────────────


def test_the_poem_heading_is_absorbed_instead_of_splitting_the_section(
    corpus_text: str, layout: dict
):
    absorbed = tuple(layout["absorbed_headings"])
    with_absorption = split_entries(section_body(corpus_text, "六丁日丁未時斷", absorbed))
    without = split_entries(section_body(corpus_text, "六丁日丁未時斷"))

    assert len(with_absorption) == 6
    # 这条断言同时是变异探针：撤掉 layout 里的吸收声明，本节回到 1 条。
    assert len(without) == 1, "没有吸收诗句时应当只剩 1 条 —— 这是缺陷的原始形态"


def test_absorbed_headings_are_declared_with_a_reason(layout: dict):
    for heading in layout["absorbed_headings"]:
        assert layout["absorbed_reasons"].get(heading), f"{heading} 缺理由"


# ── 缺陷 2：转录误字要能被定位，但引文不许改字 ─────────────────────────


def test_transcription_alias_recovers_the_missing_entry(corpus_text: str, layout: dict):
    absorbed = tuple(layout["absorbed_headings"])
    aliases = dict(layout["entry_aliases"])
    body = section_body(corpus_text, "六丁日戊申時斷", absorbed)

    assert len(split_entries(body)) == 5, "不认别名时该节只有 5 条 —— 缺陷原始形态"
    entries = split_entries(body, aliases)
    assert len(entries) == 6

    recovered = [e for e in entries if e["day_branch"] == "巳" and e["hour_branch"] == "申"]
    assert recovered, "别名应当把「丁己日戊申時」归一到丁巳"
    # 引文保留底本原字：改字就不是逐字回对了。
    assert "丁己日" in recovered[0]["raw"]


def test_alias_must_be_same_length(corpus_text: str):
    with pytest.raises(SystemExit):
        split_entries("甲子日甲子時", {"丁己日": "丁巳"})  # 长度不同，偏移会错


def test_every_alias_is_declared_with_a_reason(layout: dict):
    for wrong in layout["entry_aliases"]:
        assert layout["alias_reasons"].get(wrong), f"{wrong} 缺理由"


# ── 条目结构 ───────────────────────────────────────────────────────────


def test_every_entry_carries_four_pillars_and_a_quote(corpus_text: str, layout: dict):
    absorbed = tuple(layout["absorbed_headings"])
    aliases = dict(layout["entry_aliases"])
    for heading in iter_sections(corpus_text):
        entries = split_entries(section_body(corpus_text, heading, absorbed), aliases)
        assert len(entries) == 6, heading
        for entry in entries:
            for key in ("day_stem", "day_branch", "hour_stem", "hour_branch"):
                assert entry[key], f"{heading} 第 {entry['order']} 条缺 {key}"
            assert entry["suggested_quote"] or entry["raw"]


# ── 见证盘：按原子自己的时辰找，而不是一律按 0 点 ─────────────────────


def test_hour_of_branch_covers_all_twelve_and_stays_inside_the_shichen():
    from atom_checklist import HOUR_OF_BRANCH

    assert set(HOUR_OF_BRANCH) == set("子丑寅卯辰巳午未申酉戌亥")
    # 每个钟点都必须落在对应时辰的两小时内（子时跨日，取 0 点）。
    for index, branch in enumerate("子丑寅卯辰巳午未申酉戌亥"):
        hour = HOUR_OF_BRANCH[branch]
        assert 0 <= hour <= 23
        expected_start = (index * 2 - 1) % 24
        assert (hour - expected_start) % 24 <= 1, f"{branch} 时取 {hour} 点不在时辰内"


def test_day_pillar_probe_returns_a_valid_pair():
    import datetime as dt

    from atom_checklist import _day_pillar_of

    stem, branch = _day_pillar_of(dt.date(1990, 2, 28))
    assert stem in "甲乙丙丁戊己庚辛壬癸"
    assert branch in "子丑寅卯辰巳午未申酉戌亥"
    # 同一日必得同一日柱（纯函数，不依赖调用时刻）。
    assert _day_pillar_of(dt.date(1990, 2, 28)) == (stem, branch)

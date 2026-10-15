"""典籍引证体系的直接测试：URN、底本语料、四条引证守卫。

Phase 5 的机制（``knowledge/urn.py`` / ``knowledge/corpus.py`` /
``knowledge/rule_atoms.py``）在此之前**一条直接测试都没有** —— 八百多条绿测试
只是从 ``default_registry()`` 间接跑到它。那不是保障：这三个模块的职责恰恰是
「引文对不上就报错」，而报错路径只能靠直接调用触发。间接路径只走正常分支，
守卫失效时测试照样全绿。

每条守卫都测**两件事**：该拦的拦得住，该放行的放得过去。只测前者是半截守卫
—— 把合法引文一起拦掉的守卫同样让系统不可用，而那种失败通常在半夜才发现。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from knowledge.corpus import Corpus, CorpusEntry, CorpusError, load_corpus
from knowledge.default_rules import default_registry, default_schools
from knowledge.provenance import SourceTier
from knowledge.rule_atoms import (
    ATOM_VERSION,
    AtomError,
    atom_template,
    load_atom_dir,
    load_atom_file,
    revalidate_against_corpus,
)
from knowledge.topics import known_topic_ids
from knowledge.urn import is_urn, make, parse, try_parse

REPO = Path(__file__).resolve().parent.parent
CORPUS = load_corpus()

BASE_URN = "urn:divination:bazi:sanmingtonghui:ws761697:j8.liujia_ri.jiazi_jiazi"
COLLATION_URN = "urn:divination:bazi:sanmingtonghui:ws845354:j8.liujia_ri.jiazi_jiazi"
QUOTE = "甲寅日甲子時拱丑中辛貴"
ATOMS_DIR = REPO / "corpus" / "canonical" / "bazi_sanmingtonghui" / "atoms"

BASE = CORPUS.entry_for_urn(parse(BASE_URN))
COLLATION = CORPUS.entry_for_urn(parse(COLLATION_URN))
REPORT = load_atom_dir(
    ATOMS_DIR, CORPUS, schools=default_schools(), known_topics=known_topic_ids()
)


def flat(text: str) -> str:
    """与 ``knowledge.corpus._flatten`` 同一口径：只折叠空白，不动字。"""
    return re.sub(r"\s+", "", text)


def entry(**overrides) -> CorpusEntry:
    """拿真底本条目改几个字段，构造一条供校验用的 CorpusEntry。"""
    values = {name: getattr(BASE, name) for name in CorpusEntry.__dataclass_fields__}
    values.update(overrides)
    return CorpusEntry(**values)


def real_atoms() -> list[dict]:
    payload = json.loads((ATOMS_DIR / "juan8_liujia_ri.json").read_text(encoding="utf-8"))
    return json.loads(json.dumps(payload["atoms"]))


def load_atoms(atoms: list[dict], tmp_path: Path):
    path = tmp_path / "atom.json"
    path.write_text(
        json.dumps({"atom_version": 1, "atoms": atoms}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return load_atom_file(
        path, CORPUS, schools=default_schools(), known_topics=known_topic_ids()
    )


# ── URN 语法 ────────────────────────────────────────────────────────


def test_urn_round_trips() -> None:
    urn = parse(BASE_URN)

    assert urn.to_urn() == BASE_URN
    assert urn.system == "bazi"
    assert urn.system_name == "子平八字"
    assert urn.edition == "sanmingtonghui"
    assert urn.version == "ws761697"
    assert urn.juan == "j8"
    assert urn.chapter == "liujia_ri"
    assert urn.entry == "jiazi_jiazi"
    assert urn.to_dict()["system_name"] == "子平八字"


def test_urn_carries_a_version_segment() -> None:
    """URN 必须带版本段。这条测试守的是一个**刻意的设计决定**。

    老板给的示例是五段（无版本位）。但同一个底本代码可以对应多个版本
    （明万历刻本 / 文渊阁四库全书本 / 维基文库转录本），条文不同。URN 的用途是
    「反查出完整出处元数据」—— 两版共用一个 URN，反查回来的元数据就是错的。
    所以这里钉住：版本段在，且在 URN 串里。
    """
    urn = parse(BASE_URN)

    assert urn.version == "ws761697"
    assert "ws761697" in urn.to_urn()
    assert urn.version in BASE_URN


def test_make_and_parse_cannot_disagree() -> None:
    built = make("bazi", "sanmingtonghui", "ws761697", "j8", "liujia_ri", "jiazi_jiazi")

    assert built.to_urn() == BASE_URN
    assert parse(built.to_urn()) == built


@pytest.mark.parametrize(
    "bad",
    [
        "urn:divination:qimen:sanmingtonghui:ws761697:j8",
        "urn:divination:bazi:三命通會:ws761697:j8",
        "urn:divination:bazi:sanmingtonghui:WS761697:j8",
        "urn:divination:bazi:sanmingtonghui:ws761697:8",
        "urn:divination:bazi:sanmingtonghui:ws761697:j8.",
        "urn:divination::sanmingtonghui:ws761697:j8",
        "urn:divination:bazi:sanmingtonghui:ws761697",
        "urn:divination:bazi:sanmingtonghui:ws761697:j8.a.b.c.d",
        "三命通會卷八",
        "",
    ],
)
def test_parse_rejects_malformed_urns(bad: str) -> None:
    with pytest.raises(ValueError):
        parse(bad)


def test_a_chinese_juan_is_rejected() -> None:
    with pytest.raises(ValueError, match="卷号"):
        make("bazi", "sanmingtonghui", "ws761697", "卷八")


def test_try_parse_never_raises() -> None:
    assert try_parse(BASE_URN) is not None
    assert try_parse("不是 URN") is None
    assert try_parse("") is None
    assert is_urn(BASE_URN) is True
    assert is_urn("三命通會/卷八") is False
    assert is_urn("urn:divination:bazi:sanmingtonghui:ws761697:j8") is True


# ── 逐字定位：整套体系里最关键的一条守卫 ─────────────────────────────


def test_locate_finds_the_quote_and_reports_the_source_text() -> None:
    match = CORPUS.locate(parse(BASE_URN), QUOTE)

    assert match.urn == BASE_URN
    assert flat(match.exact) == QUOTE
    assert match.context_before or match.context_after
    assert match.to_dict()["is_verbatim"] is True


def test_locate_tolerates_line_breaks_in_the_source() -> None:
    """底本按版面断行，引用不带 —— 折叠空白就是为了这个。

    反过来也钉住：**折叠只发生在比对时**，回填的 ``exact`` 仍是底本原样
    （带原断行）。这条断言防止有人为了图省事把底本本身的换行也洗掉，
    那会让 ``text_sha256`` 换个平台就对不上。
    """
    match = CORPUS.locate(parse(BASE_URN), QUOTE)
    assert "\n" in match.exact or match.exact == QUOTE

    broken = match.exact[:2] + "\n" + match.exact[2:]
    relocated = CORPUS.locate(parse(BASE_URN), broken)

    assert flat(relocated.exact) == QUOTE


def test_locate_rejects_a_single_changed_character() -> None:
    with pytest.raises(CorpusError, match="引文在底本中找不到"):
        CORPUS.locate(parse(BASE_URN), QUOTE.replace("拱丑中辛", "拱丑中金"))


def test_locate_rejects_a_simplified_substitution() -> None:
    """繁体底本前换成简体字也过不了 —— 「贵」不是底本里的字。

    这是最现实的录入错误：作者按现代汉语习惯写引文。它不是「差不多」，
    是把一条并非原文的句子标成了原文。
    """
    with pytest.raises(CorpusError):
        CORPUS.locate(parse(BASE_URN), "甲寅日甲子时拱丑中辛贵")


def test_locate_rejects_truncation() -> None:
    """只引半句要能过（断语常只取半句），但不能凭空多出后半句。"""
    half = QUOTE[:7]

    assert flat(CORPUS.locate(parse(BASE_URN), half).exact) == half
    with pytest.raises(CorpusError):
        CORPUS.locate(parse(BASE_URN), QUOTE + "大貴")


def test_locate_rejects_an_empty_quote() -> None:
    with pytest.raises(CorpusError, match="引文为空"):
        CORPUS.locate(parse(BASE_URN), "   ")


def test_entry_for_urn_matches_all_four_segments_including_version() -> None:
    """少比版本，两个版本的引用就会指向同一份文本 —— 这正是 URN 多一段的理由。"""
    base = CORPUS.entry_for_urn(parse(BASE_URN))
    collation = CORPUS.entry_for_urn(parse(COLLATION_URN))

    assert base.version_code == "ws761697"
    assert collation.version_code == "ws845354"
    assert base.corpus_id != collation.corpus_id
    assert base.path != collation.path


def test_entry_for_urn_lists_what_has_been_frozen() -> None:
    with pytest.raises(CorpusError, match="已固化"):
        CORPUS.entry_for_urn(parse("urn:divination:bazi:nope:ws000:j8"))


# ── role 门禁：对照本不可供引用 ─────────────────────────────────────


def test_citation_refuses_a_collation_edition() -> None:
    """对照本的正文也在 corpus 里、引文同样找得到，但不拦就能「核验通过」
    却指向一个没有版本声明的文本。那正是「底本未定」本身。"""
    with pytest.raises(CorpusError, match="只有 role='base'"):
        CORPUS.citation(parse(COLLATION_URN), QUOTE)


def test_citation_refuses_a_reserve_edition() -> None:
    reserve = parse("urn:divination:zwds:qianshuchongzhen:ws7913704:j1")

    with pytest.raises(CorpusError, match="只有 role='base'"):
        CORPUS.citation(reserve, "問紫微所主若何")


def test_citation_builds_full_provenance_from_the_corpus() -> None:
    citation = CORPUS.citation(parse(BASE_URN), QUOTE)

    assert citation.book == "三命通會"
    assert citation.urn == BASE_URN
    assert "761697" in citation.url
    assert citation.edition == "欽定四庫全書本（清乾隆間編定；明 萬民英 撰）"
    assert citation.chapter == "卷八·六甲日甲子時斷"
    assert citation.is_canonical is True
    assert citation.parsed_urn is not None
    assert citation.parsed_urn.version == "ws761697"
    assert citation.parsed_urn.juan == "j8"


def test_chapter_label_resolves_the_chapter_name() -> None:
    assert CORPUS.chapter_label(parse(BASE_URN)) == "六甲日甲子時斷"
    assert CORPUS.chapter_label(parse(BASE_URN.replace(".liujia_ri", ""))) == ""


# ── 完整性：原文不可被无痕篡改 ───────────────────────────────────────


def test_the_real_corpus_is_internally_consistent() -> None:
    assert CORPUS.problems() == []


def test_problems_detects_a_tampered_corpus_file(tmp_path) -> None:
    """改 corpus 里的一个字，哈希自查必须报出来。"""
    original = (REPO / BASE.path).read_text(encoding="utf-8")
    mark = original.index("拱丑中辛")
    mutated = original[: mark + 1] + "中" + original[mark + 2 :]
    assert mutated != original
    assert len(mutated) == len(original)

    (tmp_path / "juan8.txt").write_text(mutated, encoding="utf-8")
    corpus = Corpus(tmp_path, (entry(path="juan8.txt"),), tmp_path)

    problems = corpus.problems()

    assert any("内容与 manifest 不符" in problem for problem in problems)


def test_problems_detects_a_missing_file(tmp_path) -> None:
    corpus = Corpus(tmp_path, (entry(path="gone.txt"),), tmp_path)

    assert any("文件缺失" in problem for problem in corpus.problems())


def test_problems_detects_a_wrong_chapter_label(tmp_path) -> None:
    """篇章表是手写的，标签写错一个字，反查回来的出处就会宣称一个不存在的篇名。"""
    (tmp_path / "juan8.txt").write_text(
        (REPO / BASE.path).read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "chapters.json").write_text(
        json.dumps(
            {"edition_code": "sanmingtonghui", "chapters": {"j8.liujia_ri": "六甲日甲丑時斷"}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    corpus = Corpus(tmp_path, (entry(path="juan8.txt"),), tmp_path)

    assert any("篇章表" in problem for problem in corpus.problems())


def test_manifest_entry_rejects_an_unregistered_role() -> None:
    with pytest.raises(CorpusError, match="role 未登记"):
        entry(role="whatever")


# ── 四条引证守卫：加载器就是守卫本身 ────────────────────────────────


def test_the_six_real_atoms_load_and_every_quote_locates() -> None:
    assert len(REPORT.rules) == 6
    assert len(REPORT.located) == 6

    for rule in REPORT.rules:
        assert rule.source_tier is SourceTier.CLASSICAL
        assert rule.urn
        assert rule.citation is not None
        assert rule.citation.urn == rule.urn
        assert rule.citation.is_canonical
        assert revalidate_against_corpus(rule, CORPUS)


def test_the_load_report_shows_where_each_quote_landed() -> None:
    """人工复核要看的是「引文对到了哪一句」，不是「加载成功」四个字。"""
    for rule_id, urn, exact in REPORT.located:
        assert rule_id
        assert urn.startswith("urn:divination:")
        assert exact.strip()
        assert flat(exact) in flat(CORPUS.text(BASE))


def test_every_classical_rule_revalidates_against_the_corpus() -> None:
    """「任何时刻都能拿现有规则去问底本」—— 这条约束本身要被测试。"""
    rules = default_registry().select(source_tier=SourceTier.CLASSICAL)

    assert rules
    for rule in rules:
        assert revalidate_against_corpus(rule, CORPUS)


def test_a_single_changed_character_fails_to_load(tmp_path) -> None:
    atoms = real_atoms()
    atoms[1]["citation"]["exact_quote"] = "甲寅日甲子時拱丑中金貴"

    with pytest.raises(AtomError, match="引文无法在底本中定位"):
        load_atoms(atoms, tmp_path)


def test_a_simplified_quote_fails_to_load(tmp_path) -> None:
    atoms = real_atoms()
    atoms[1]["citation"]["exact_quote"] = "甲寅日甲子时拱丑中辛贵"

    with pytest.raises(AtomError, match="引文无法在底本中定位"):
        load_atoms(atoms, tmp_path)


def test_a_missing_urn_fails_to_load(tmp_path) -> None:
    atoms = real_atoms()
    del atoms[0]["urn"]

    with pytest.raises(AtomError, match="缺少必需字段：urn"):
        load_atoms(atoms, tmp_path)


def test_a_collation_urn_fails_to_load(tmp_path) -> None:
    """原子指向对照本也不行 —— role 门禁在加载路径上同样生效。

    引文得先用对照本的用字（简体）写，否则 ``locate`` 会先失败，
    报的是「找不到」而不是「不可引用」—— 那是另一条守卫的错，
    会在 :func:`test_an_exact_quote_cannot_be_located_in_the_collation` 里测。
    两条都要测，因为**加载顺序决定了哪条守卫先说话**。
    """
    atoms = real_atoms()
    atoms[0]["urn"] = atoms[0]["urn"].replace("ws761697", "ws845354")
    atoms[0]["citation"]["exact_quote"] = "甲子日甲子时，子遥巳格"

    with pytest.raises(AtomError, match="只有 role='base'"):
        load_atoms(atoms, tmp_path)


def test_a_wrong_edition_code_fails_to_load(tmp_path) -> None:
    atoms = real_atoms()
    atoms[0]["urn"] = atoms[0]["urn"].replace(":sanmingtonghui:", ":ditiansui:")

    with pytest.raises(AtomError, match="不在 corpus 里"):
        load_atoms(atoms, tmp_path)


def test_an_unknown_condition_key_fails_to_load(tmp_path) -> None:
    """条件键拼错不会报错，只会让这条规则永远匹配不上 —— 所以这里必须拦。"""
    atoms = real_atoms()
    atoms[0]["condition"]["这个键不存在"] = "甲"

    with pytest.raises(AtomError, match="事实词表里不存在的键"):
        load_atoms(atoms, tmp_path)


def test_an_unregistered_topic_fails_to_load(tmp_path) -> None:
    atoms = real_atoms()
    atoms[0]["assertion"]["theme_domain"] = "风水"

    with pytest.raises(AtomError, match="未登记"):
        load_atoms(atoms, tmp_path)


def test_an_unregistered_school_fails_to_load(tmp_path) -> None:
    atoms = real_atoms()
    atoms[0]["school"] = "not_a_registered_school"

    with pytest.raises(AtomError, match="未注册的流派"):
        load_atoms(atoms, tmp_path)


def test_a_lying_book_name_fails_to_load(tmp_path) -> None:
    """原子可重述书名是为了自证，重述了就要对得上。"""
    atoms = real_atoms()
    atoms[0]["citation"]["book"] = "滴天髓"

    with pytest.raises(AtomError, match=r"citation\.book 与底本不符"):
        load_atoms(atoms, tmp_path)


def test_a_wrong_chapter_name_fails_to_load(tmp_path) -> None:
    atoms = real_atoms()
    atoms[0]["citation"]["chapter"] = "卷八·六甲日乙丑時斷"

    with pytest.raises(AtomError, match=r"citation\.chapter 与篇章表不符"):
        load_atoms(atoms, tmp_path)


def test_an_unknown_top_level_field_fails_to_load(tmp_path) -> None:
    atoms = real_atoms()
    atoms[0]["来历不明"] = "x"

    with pytest.raises(AtomError, match="含未知字段"):
        load_atoms(atoms, tmp_path)


def test_a_wrong_atom_version_fails_to_load(tmp_path) -> None:
    atoms = real_atoms()
    atoms[0]["atom_version"] = 99

    with pytest.raises(AtomError, match="atom_version"):
        load_atoms(atoms, tmp_path)


def test_an_empty_condition_fails_to_load(tmp_path) -> None:
    atoms = real_atoms()
    atoms[0]["condition"] = {}

    with pytest.raises(AtomError, match="condition 必须是非空对象"):
        load_atoms(atoms, tmp_path)


def test_an_illegal_polarity_fails_to_load(tmp_path) -> None:
    atoms = real_atoms()
    atoms[0]["assertion"]["polarity"] = "大吉"

    with pytest.raises(ValueError, match="polarity 非法"):
        load_atoms(atoms, tmp_path)


def test_a_duplicate_rule_id_fails_to_load(tmp_path) -> None:
    atoms = real_atoms()
    atoms.append(json.loads(json.dumps(atoms[0])))

    with pytest.raises(AtomError, match="规则 ID 重复"):
        load_atoms(atoms, tmp_path)


def test_an_empty_atom_file_fails_to_load(tmp_path) -> None:
    path = tmp_path / "atom.json"
    path.write_text(json.dumps({"atom_version": 1, "atoms": []}), encoding="utf-8")

    with pytest.raises(AtomError, match="必须是非空数组"):
        load_atom_file(
            path, CORPUS, schools=default_schools(), known_topics=known_topic_ids()
        )


# ── 对照本的能力边界：它能核什么，不能核什么 ─────────────────────────


def test_the_collation_is_a_simplified_punctuated_transcription() -> None:
    """对照本**不是**逐字互证源。这一点要被钉住，否则迟早有人想「顺手」用上它。

    它是同一部书的另一传本：**加了现代标点、换成简体字**。所以原子的繁体引文
    拿去对它逐字核对必然失败。失败是对的 —— 否则一条引文可以「核验通过」
    却落在一份「所据底本未標註」的文本上，那正是「底本未定」本身。
    """
    assert "已加現代標點、用簡體字" in COLLATION.transcription_note

    collation_text = flat(CORPUS.text(COLLATION))
    base_text = flat(CORPUS.text(BASE))

    assert "甲午日甲子时，时日并冲，忧伤妻子" in collation_text
    assert "甲午日甲子時時日併衝憂傷妻子" in base_text
    assert collation_text.count("（一云）") == 0
    assert base_text.count("（一云）") >= 50


def test_the_documented_collation_divergence_is_real() -> None:
    """四库本带「（一云）」异读，转录本没有。这条异文要可查，不是注释里的一句话。"""
    assert "（一云）髙" in flat(CORPUS.text(BASE))
    assert "（一云）" not in flat(CORPUS.text(COLLATION))


def test_an_exact_quote_cannot_be_located_in_the_collation() -> None:
    with pytest.raises(CorpusError, match="引文在底本中找不到"):
        CORPUS.locate(parse(COLLATION_URN), QUOTE)


def test_both_transcriptions_cover_the_same_six_jia_sections() -> None:
    base = re.findall(r"^## 六甲日", CORPUS.text(BASE), re.M)
    collation = re.findall(r"^## 六甲日", CORPUS.text(COLLATION), re.M)

    assert len(base) == 12
    assert len(collation) == 12


def test_upstream_dropped_stems_from_three_jia_headings() -> None:
    """上游维基文库的 ``{{SK anchor}}`` 自己丢了天干，**不是**我们的规范化问题。

    ``六甲日壬申時斷`` / ``六甲日癸酉時斷`` / ``六甲日甲戌時斷`` 在页面上被录成
    ``六甲日申時斷`` / ``酉`` / ``戌``（六乙、六丙等组同样有）。它不影响当前唯一
    登记的篇章 ``j8.liujia_ri``（标题完好）；但后续要登记别的时辰篇就会踩上 ——
    而一个错误的篇名会让反查回来的出处宣称底本里并不存在的标题。

    这条测试把已知缺陷钉住：上游哪天修好了，它变红，那时再改
    ``chapters.json`` 去登记新篇章，而不是默默靠一个错标签过关。
    """
    text = flat(CORPUS.text(BASE))

    assert "六甲日甲子時斷" in text       # 当前唯一登记的篇章，标题完好
    assert "六甲日申時斷" in text         # 上游缺陷：少了「壬」
    assert "六甲日壬申時斷" not in text
    assert "六甲日酉時斷" in text         # 少了「癸」
    assert "六甲日戌時斷" in text         # 少了「甲」


# ── 备存本与模板 ────────────────────────────────────────────────────


def test_the_reserve_entry_has_no_consumers_yet() -> None:
    """紫微斗数备存本的定位：文本固化了，但没有排盘引擎，所以没有原子可引。"""
    reserve = CORPUS.entry_for_urn(
        parse("urn:divination:zwds:qianshuchongzhen:ws7913704:j1")
    )

    assert reserve.role == "reserve"
    assert reserve.is_citable is False
    assert "排盤引擎" in reserve.transcription_note
    assert not [
        rule.id
        for rule in default_registry().select()
        if rule.citation is not None and rule.citation.book == reserve.book
    ]


def test_the_atom_template_documents_the_required_shape() -> None:
    template = atom_template()

    assert template["atom_version"] == ATOM_VERSION
    for key in ("rule_id", "urn", "citation", "condition", "assertion"):
        assert key in template
    assert template["urn"].startswith("urn:divination:")
    assert "逐字原文" in template["citation"]["exact_quote"]

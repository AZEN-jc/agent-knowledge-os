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

import hashlib
import json
import re
import tempfile
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


# ── 补厚：两类完整性校验各自只有一条测试，改写其中一半逻辑可能仍然全绿 ──


def mutate_one_character(text: str, anchor: str) -> str:
    """把 anchor 里的第二个字换成「一」，长度不变，哈希必变。"""
    at = text.index(anchor)
    return text[: at + 1] + "一" + text[at + 2 :]


def write_chapters(tmp_path: Path, chapters: dict[str, str]) -> None:
    (tmp_path / "chapters.json").write_text(
        json.dumps(
            {"edition_code": "sanmingtonghui", "chapters": chapters},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_a_tampered_collation_file_is_also_caught(tmp_path) -> None:
    """哈希自查对**每一卷**都跑，包括不可供引用的对照本。

    对照本不可供引用，但它同样是固化文本 —— 有人改了它的字，corpus 就不再是
    「我们固化过的那一份」，而异文核对的结论也跟着不可信。
    两项校验按 role 区别对待的只有篇章表那一项（对照本用字本就不同）；
    哈希这一项必须一视同仁。

    哈希取自对照本自己的 manifest 条目，所以**唯一**的病因是下面那次改动 ——
    否则用底本的哈希去配对照本的文件，什么都没改也会报不符，这条测试就白写了。
    """
    original = (REPO / COLLATION.path).read_text(encoding="utf-8")
    (tmp_path / "juan8_collation.txt").write_text(
        mutate_one_character(original, "六甲日甲子时断"), encoding="utf-8"
    )
    corpus = Corpus(
        tmp_path,
        (entry(path="juan8_collation.txt", role="collation", text_sha256=COLLATION.text_sha256),),
        tmp_path,
    )

    assert any("内容与 manifest 不符" in p for p in corpus.problems())


def test_a_hash_mismatch_does_not_also_report_chapter_noise(tmp_path) -> None:
    """内容已经判定不可信时，篇章表那一项要跳过。

    哈希对不上，说明这个文件不是我们固化的那一份；此时再拿它去核篇章表标签，
    报出来的是「篇名找不到」—— 而病根是内容被改过。诊断不能指向错的地方，
    所以哈希不匹配时要 ``continue``，不往下走。

    这条测试特意把改动落在篇名**自己身上**：去掉 ``continue`` 的话，
    两个问题会一起报出来，而只有第一个是真的病因。
    """
    text = (REPO / BASE.path).read_text(encoding="utf-8")
    (tmp_path / "juan8.txt").write_text(
        mutate_one_character(text, "六甲日甲子時斷"), encoding="utf-8"
    )
    write_chapters(tmp_path, {"j8.liujia_ri": "六甲日甲子時斷"})
    corpus = Corpus(tmp_path, (entry(path="juan8.txt"),), tmp_path)

    problems = corpus.problems()

    assert any("内容与 manifest 不符" in p for p in problems)
    assert not any("篇章表" in p for p in problems), "哈希已经对不上了，不该再报篇章表噪音"


def test_problems_reports_every_broken_entry(tmp_path) -> None:
    """两个条目同时坏掉要报两条 —— 只报第一条会让人以为只有一处问题。"""
    (tmp_path / "juan8.txt").write_text("改过的底本", encoding="utf-8")
    (tmp_path / "juan8_collation.txt").write_text("改过的对照本", encoding="utf-8")
    corpus = Corpus(
        tmp_path,
        (entry(path="juan8.txt"), entry(path="juan8_collation.txt")),
        tmp_path,
    )

    problems = [p for p in corpus.problems() if "内容与 manifest 不符" in p]

    assert len(problems) == 2


def test_problems_does_not_need_a_chapter_table(tmp_path) -> None:
    """没有 chapters.json 不是错误 —— 只是 URN 的 chapter 段缺个中文对照。

    把它当成问题会逼着每卷都先建篇章表才能固化，而固化本身不依赖那张表。
    """
    (tmp_path / "juan8.txt").write_text(
        (REPO / BASE.path).read_text(encoding="utf-8"), encoding="utf-8"
    )
    corpus = Corpus(tmp_path, (entry(path="juan8.txt"),), tmp_path)

    assert corpus.problems() == []


def test_problems_reports_one_issue_per_bad_label(tmp_path) -> None:
    """两个标签都写错就报两条，与文件条目的报错口径一致。"""
    (tmp_path / "juan8.txt").write_text(
        (REPO / BASE.path).read_text(encoding="utf-8"), encoding="utf-8"
    )
    write_chapters(
        tmp_path,
        {
            "j8.liujia_ri": "六甲日甲丑時斷",
            "j8.other": "六甲日甲寅時斷錯",
        },
    )
    corpus = Corpus(tmp_path, (entry(path="juan8.txt"),), tmp_path)

    problems = [p for p in corpus.problems() if "篇章表" in p]

    assert len(problems) == 2


def test_a_chapter_label_belonging_to_another_juan_is_ignored(tmp_path) -> None:
    """篇章表按版本共享、装着所有卷的标签；一个条目只管自己那一卷。

    不过滤的话，j8 的条目会对着 j1 的标签逐个报「正文里找不到」——
    而 j1 的标签本来就不该出现在 j8 的正文里。这是假警报，不是检查。
    """
    (tmp_path / "juan8.txt").write_text(
        (REPO / BASE.path).read_text(encoding="utf-8"), encoding="utf-8"
    )
    write_chapters(
        tmp_path,
        {
            "j8.liujia_ri": "六甲日甲子時斷",
            "j1.qixing": "諸星問答論",
        },
    )
    corpus = Corpus(tmp_path, (entry(path="juan8.txt"),), tmp_path)

    assert corpus.problems() == []


def test_a_collation_entry_is_not_chapter_checked(tmp_path) -> None:
    """篇章表只对底本（role=base）校验。

    chapters.json 里的标签按**底本用字**写：对照本是另一传本，简繁与用字都可能
    不同。拿对照本正文去核标签只会得到假警报 —— 这一条就是把那个门禁钉住，
    谁把 ``is_citable`` 的条件去掉，这里立刻红。

    这里刻意只用对照本一条条目：真 corpus 里底本与对照本共用一个
    chapters.json，底本那一侧的检查会先通过，门禁的效果就看不出来了。
    """
    (tmp_path / "juan8_collation.txt").write_text(
        (REPO / COLLATION.path).read_text(encoding="utf-8"), encoding="utf-8"
    )
    write_chapters(tmp_path, {"j8.liujia_ri": "六甲日甲子時斷"})
    corpus = Corpus(
        tmp_path,
        (
            entry(
                path="juan8_collation.txt",
                role="collation",
                text_sha256=COLLATION.text_sha256,
                # 字数也要跟着换：条目其余字段是从**底本**抄来的，只改 path 与
                # 哈希的话，Phase 3.4 新加的「字数与 manifest 不符」会先报一条 ——
                # 那是这份测试夹具自己不自洽，不是被测门禁的问题。
                text_chars=COLLATION.text_chars,
            ),
        ),
        tmp_path,
    )

    assert corpus.problems() == []


def test_manifest_entry_rejects_an_unregistered_role() -> None:
    with pytest.raises(CorpusError, match="role 未登记"):
        entry(role="whatever")


# ── 四条引证守卫：加载器就是守卫本身 ────────────────────────────────


def test_every_real_atom_loads_and_every_quote_locates() -> None:
    """不写死条数 —— 底本会继续录，写死就等于每次录新原子都要改测试。

    要守的不变式是「**每条都真的对回了底本**」。
    """
    assert REPORT.rules
    assert len(REPORT.rules) == len(REPORT.located)

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


# ── 第 5 轮：事实词表扩展后解锁的甲辰日，与「引文说了限制条件没表达」守卫 ──


def chart_1980():
    from engines.bazi import BaziCalculator, BirthInput, SxtwlBaziProvider

    return BaziCalculator(SxtwlBaziProvider()).calculate_chart(BirthInput(1980, 2, 21, 0, 30))


def facts_of(chart) -> dict:
    from knowledge.facts import extract_facts

    return {fact.type: fact.value for fact in extract_facts(chart)}


def test_the_new_pillar_facts_are_verbatim_combinations() -> None:
    """整柱干支必须真的等于干加支，不能是另一个算出来的东西。"""
    facts = facts_of(chart_1980())

    for pillar in chart_1980().pillars:
        assert facts[f"{pillar.name}_pillar"] == pillar.heavenly_stem + pillar.earthly_branch
        assert facts[f"{pillar.name}_stem"] == pillar.heavenly_stem
        assert facts[f"{pillar.name}_branch"] == pillar.earthly_branch


def test_year_month_elements_covers_only_the_year_and_month_pillars() -> None:
    """「水位年月」判的是年月两层，不是全命局。

    拿时柱的一水把全局计数抬起来，会把一条年月断语判成全局命中 ——
    那不是断语说的范围。这条测试把范围钉住。
    """
    from engines.bazi.ten_gods import ELEMENTS

    chart = chart_1980()
    values = facts_of(chart)
    pillars = chart.pillars[:2]
    expected = {ELEMENTS[p.heavenly_stem] for p in pillars} | {
        ELEMENTS[p.hidden_stems[0]] for p in pillars
    }

    assert set(values["year_month_elements"]) == expected
    # 时柱不参与：它的五行若不在 expected 里，正说明它没被算进来
    hour = chart.pillars[3]
    assert ELEMENTS[hour.hidden_stems[0]] in expected or (
        ELEMENTS[hour.heavenly_stem] in expected
    )


def test_every_emitted_fact_key_is_registered_in_the_schema() -> None:
    """产出了却没登记的事实键 = 规则永远用不上的死事实。"""
    from knowledge.facts import FACT_SCHEMA

    emitted = set(facts_of(chart_1980()))

    assert emitted <= set(FACT_SCHEMA)
    assert {"year_pillar", "month_pillar", "year_month_elements"} <= emitted


def test_condition_holds_treats_a_container_expectation_as_membership() -> None:
    """「寅午戌月俱吉」要能一条规则表达，而不是拆成三条。

    拆开的代价不只是重复：第三条一旦漏录，集合少一块而不报错。
    """
    from knowledge.rules import condition_holds

    assert condition_holds("寅", ["寅", "午", "戌"]) is True
    assert condition_holds("午", ["寅", "午", "戌"]) is True
    assert condition_holds("亥", ["寅", "午", "戌"]) is False
    assert condition_holds("寅", ("寅", "午")) is True
    # 原有的两侧语义都不能破
    assert condition_holds(("六合", "自刑"), "六合") is True
    assert condition_holds(("六合", "自刑"), "三刑") is False
    assert condition_holds("甲", "甲") is True
    assert condition_holds("甲", "乙") is False
    # 字符串不许被当成容器：否则 "六合" in "六合六冲" 会误命中
    assert condition_holds("六合六冲", "六合") is False


def test_a_month_restriction_in_the_quote_must_reach_the_condition() -> None:
    """第五条守卫：引文说了月令，条件里必须有月令事实。

    2026-10-15 的真实事故：引文写「申月，煞星会印，俱贵」而 condition 漏了
    ``month_branch``，于是这条吉断语对任何月份的甲辰日甲子时都命中。
    前四条守卫一条都没拦 —— 引文逐字对得上、键都在词表、元数据也一致。
    问题不在引文，在**条件没有表达引文说过的限制**。
    """
    target = next(
        a for a in real_atoms() if a["rule_id"].endswith("jiachen_jiazi_02")
    )
    del target["condition"]["month_branch"]

    with pytest.raises(AtomError, match="引文提到了月令"):
        _load_single(target)


def test_a_year_month_restriction_in_the_quote_must_reach_the_condition() -> None:
    """第五条守卫的第二种形态：引文说「水位年月」也要有年月层的事实。

    「若水位年月，水泛木浮」的限制落在 ``year_month_elements`` 上。
    月令那一侧的正则只认「干支 + 月」，认不出「年月」——
    所以补守卫的同一天就要问一句：**这个洞还有没有第二个口子。**
    有，就是这一条。去掉 ``year_month_elements``，这条凶断就会对任何
    甲辰日甲子时生效，而前四条守卫照样全绿。
    """
    target = next(
        a for a in real_atoms() if a["rule_id"].endswith("jiachen_jiazi_01")
    )
    del target["condition"]["year_month_elements"]

    with pytest.raises(AtomError, match=r"引文提到了月令或年月"):
        _load_single(target)


def _load_single(atom: dict):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "atom.json"
        path.write_text(
            json.dumps({"atom_version": 1, "atoms": [atom]}, ensure_ascii=False),
            encoding="utf-8",
        )
        return load_atom_file(
            path, CORPUS, schools=default_schools(), known_topics=known_topic_ids()
        )


def test_both_restriction_forms_are_reported_together() -> None:
    """一句引文同时提了「年月」和「申月」时，两个口子要一次报全。

    只报第一个是偷懒：录规则的人改完一处、再跑一次、再改一处，
    而这两处本来是同一次录入里一起漏的。

    引文由文件里两条真原子的原文拼接而成，**不手打汉字** ——
    手打的那一版我在验证时打错了一个异体字，`locate` 直接以「引文不是原文」
    报错，白白绕到第二条守卫上去。拼接的两个片段在底本里本来就相邻
    （甲辰日甲子时条「…主移根换叶」紧接着「申月…」），所以拼起来仍是原文。
    """
    atoms = {a["rule_id"].rsplit("_", 1)[-1]: a for a in real_atoms() if "jiachen" in a["rule_id"]}
    target = atoms["02"]
    target["citation"]["exact_quote"] = (
        atoms["01"]["citation"]["exact_quote"] + atoms["02"]["citation"]["exact_quote"]
    )
    del target["condition"]["month_branch"]

    with pytest.raises(AtomError) as caught:
        _load_single(target)

    message = str(caught.value)
    assert "month_branch" in message, "月令那一侧没报出来"
    assert "year_month_elements" in message, "年月那一侧没报出来"


def test_a_quote_without_a_time_restriction_is_not_blocked() -> None:
    """反向不能过严：引文没提月令 / 年月的规则不碰这条守卫。"""
    base = next(a for a in real_atoms() if a["rule_id"].endswith("jiayin_jiazi"))

    assert not any(key.startswith("month") for key in base["condition"])
    _load_single(base)


def test_the_previously_deferred_jiachen_entry_is_now_covered() -> None:
    """甲辰日从「整条暂缓」变成 7 条真原子 —— 事实词表扩展的直接成果。"""
    jiachen = [
        rule for rule in default_registry().select(topic="destiny")
        if "jiachen" in rule.id
    ]

    assert len(jiachen) == 7
    assert {rule.polarity for rule in jiachen} == {"positive", "negative"}
    assert all(rule.citation is not None and rule.citation.is_canonical for rule in jiachen)
    for rule in jiachen:
        assert revalidate_against_corpus(rule, CORPUS)


def test_the_jiachen_atoms_distinguish_the_months_they_state() -> None:
    """申月与酉月必须是两条不同的规则，而不是一条对所有月份生效的规则。"""
    rules = {
        rule.id: rule
        for rule in default_registry().select(topic="destiny")
        if "jiachen" in rule.id
    }
    shen = rules["rule_bazi_sanmingtonghui_j8_jiachen_jiazi_02"]
    you = rules["rule_bazi_sanmingtonghui_j8_jiachen_jiazi_03"]

    assert shen.condition["month_branch"] == "申"
    assert you.condition["month_branch"] == "酉"
    assert shen.id != you.id


def test_problems_reports_a_truncated_manifest_hash() -> None:
    """sha256 少了后半段也要报出来 —— 逐字符比，不是前缀比。"""
    original = (REPO / BASE.path).read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "juan8.txt").write_text(original, encoding="utf-8")
        corpus = Corpus(root, (entry(path="juan8.txt", text_sha256=BASE.text_sha256[:32]),), root)

        assert any("内容与 manifest 不符" in p for p in corpus.problems())


def test_problems_reports_a_hash_taken_from_a_different_file() -> None:
    """拿别卷的哈希来标本卷，也要报 —— 否则「哈希对得上」会被误读成「文件没动」。"""
    other = REPO / "corpus/canonical/bazi_sanmingtonghui/juan8_collation.txt"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "juan8.txt").write_text((REPO / BASE.path).read_text(encoding="utf-8"), encoding="utf-8")
        wrong = entry(
            path="juan8.txt",
            text_sha256=hashlib.sha256(other.read_bytes()).hexdigest(),
        )
        corpus = Corpus(root, (wrong,), root)

        assert any("内容与 manifest 不符" in p for p in corpus.problems())


def test_chapter_keys_of_other_juan_are_not_errors() -> None:
    """篇章表是整部书共用的，别人的卷号不是错误 —— 但也不能拿来标本卷。

    ``_chapter_problems`` 跳过非本卷的键是对的（j9 归 j9 那一卷管）。
    这里钉住这一点，免得后人把「跳过」当成漏校验给「修」成报错。
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "juan8.txt").write_text((REPO / BASE.path).read_text(encoding="utf-8"), encoding="utf-8")
        (root / "chapters.json").write_text(
            json.dumps(
                {"edition_code": "sanmingtonghui",
                 "chapters": {"j9.liujia_ri": "六甲日甲子時斷"}},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        corpus = Corpus(root, (entry(path="juan8.txt"),), root)

        assert corpus.problems() == []
        assert corpus.chapter_label(parse(BASE_URN)) == ""


def test_flatten_drops_whitespace_only() -> None:
    """折叠只动空白，不动字。"""
    from knowledge.corpus import _flatten

    flat, positions = _flatten("甲寅日\n甲子時\t拱丑中辛　貴")

    assert flat == "甲寅日甲子時拱丑中辛貴"
    assert len(positions) == len(flat)

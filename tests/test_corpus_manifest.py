"""Phase 3.4：底本清单、URN 四段键与两份传本的对照。

## 已有的覆盖与这里的缺口

``test_corpus_citation.py`` 已经守住了引证体系的主体：URN 语法、逐字定位、
role 门禁、两级哈希、加载期的十几种拒收路径。**它守的是「引文对不对」**。

这里补的是**清单层**——即「这份 manifest 本身可不可信」：

1. ``text_chars`` 此前**从不校验**。哈希对得上时它一定对，但 manifest 是手写的，
   有人改字数却没改正文（或反过来），没有任何测试会发现。字数不符往往先于
   哈希不符被发现，且能说明「差了多少」。
2. 四段键（system + edition + version + juan）**重复时静默取第一条**。
   ``entry_for_urn`` 返回首个匹配，第二条永远取不到 —— 引文会被核到另一份
   文本上，而 URN、书名、版本看起来全都正常。现在装载时就拒绝。
3. ``normalizer`` 字段只写不读。它声明「这份正文是用哪个规范化器产出的」，
   与 ``scripts/fetch_corpus.py`` 的常量必须一致 —— 否则改了规范化器却没重抓，
   声明与实际就是两回事。
4. 两份传本（底本 / 对照本）的**篇章对齐**此前只数了个数（都是 12 个「## 六甲日」）。
   数对不代表顺序对：两卷里若各少一个不同的篇、各多一个别的篇，计数仍然相等。
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

from knowledge.corpus import Corpus, CorpusEntry, CorpusError, load_corpus
from knowledge.default_rules import default_registry
from knowledge.urn import parse, try_parse

REPO = Path(__file__).resolve().parent.parent
CORPUS = load_corpus()
MANIFEST = json.loads(
    (REPO / "corpus" / "canonical" / "manifest.json").read_text(encoding="utf-8")
)
ATOMS_DIR = REPO / "corpus" / "canonical" / "bazi_sanmingtonghui" / "atoms"

BASE = CORPUS.entry_for_urn(parse("urn:divination:bazi:sanmingtonghui:ws761697:j8"))
COLLATION = CORPUS.entry_for_urn(parse("urn:divination:bazi:sanmingtonghui:ws845354:j8"))


def flat(text: str) -> str:
    return re.sub(r"\s+", "", text)


def entry(**overrides: object) -> CorpusEntry:
    values = {name: getattr(BASE, name) for name in CorpusEntry.__dataclass_fields__}
    values.update(overrides)
    return CorpusEntry(**values)  # type: ignore[arg-type]


def atom_payloads() -> list[dict]:
    """全部原子文件里的 atom 字典（跨目录）。"""
    out: list[dict] = []
    for path in sorted(ATOMS_DIR.glob("*.json")):
        out.extend(json.loads(path.read_text(encoding="utf-8")).get("atoms", []))
    return out


# ── 清单自洽：字数、哈希、出处字段 ────────────────────────────────────


def test_every_entry_declares_its_actual_character_count():
    """``text_chars`` 必须等于文件实际长度。

    哈希能覆盖字数，但两者的诊断价值不同：哈希不符只说「变了」，
    字数不符能说「差了多少」。字数这一项此前完全没人校验。
    """
    for item in CORPUS.entries:
        text = (REPO / item.path).read_text(encoding="utf-8")
        assert len(text) == item.text_chars, (
            f"{item.corpus_id} 声明 {item.text_chars} 字，实际 {len(text)} 字"
        )


def test_problems_reports_a_wrong_character_count(tmp_path):
    """字数被改错时要报出来 —— 而且不能因为哈希是对的就不报。"""
    (tmp_path / "juan8.txt").write_text(
        (REPO / BASE.path).read_text(encoding="utf-8"), encoding="utf-8"
    )
    corpus = Corpus(tmp_path, (entry(path="juan8.txt", text_chars=BASE.text_chars + 1),), tmp_path)

    problems = corpus.problems()

    assert any("字数与 manifest 不符" in problem for problem in problems)
    # 哈希本身是对的，所以不该出现哈希那条 —— 否则诊断会指向错的地方。
    assert not any("内容与 manifest 不符" in problem for problem in problems)


def test_every_entry_has_a_checkable_provenance_record():
    """出处的每个字段都要是「能拿去复核」的形态，不是一句「来自维基文库」。

    复核要能回答：哪一版（revid / sha1）、什么时候取的（日期）、
    在哪儿（https 链接）、什么许可。缺一项，这条引用就不可独立复核。
    """
    for item in CORPUS.entries:
        assert re.fullmatch(r"[0-9a-f]{40}", item.source_revision_sha1), (
            f"{item.corpus_id} 的 revision sha1 不是 40 位小写十六进制"
        )
        assert item.source_revid > 0
        assert str(item.source_revid) in item.source_url, (
            f"{item.corpus_id} 的链接里没有 revid，点开可能不是这一版"
        )
        assert item.source_url.startswith("https://"), "出处链接必须是 https"
        date.fromisoformat(item.retrieved_on)  # 非法日期直接抛
        assert item.license.strip(), f"{item.corpus_id} 没有许可说明"
        assert item.transcription_note.strip(), f"{item.corpus_id} 没有转录状态说明"


def test_the_manifest_declares_the_same_normalizer_as_the_fetch_script():
    """``normalizer`` 必须与抓取脚本里的常量一致。

    这个字段声明「这份正文是用哪个规范化器产出的」，但它此前只写不读 ——
    改了规范化器却没重抓，正文与声明就是两回事，而没有任何测试会发现。
    版本号对不上时，正确做法是重跑 fetch 脚本，不是改这里。
    """
    source = (REPO / "scripts" / "fetch_corpus.py").read_text(encoding="utf-8")
    match = re.search(r'^NORMALIZER\s*=\s*"([^"]+)"', source, re.M)
    assert match, "fetch_corpus.py 里找不到 NORMALIZER 常量"

    assert MANIFEST["normalizer"] == match.group(1)
    for item in CORPUS.entries:
        assert item.normalizer == match.group(1)


# ── URN 四段键的唯一性 ────────────────────────────────────────────────


def test_the_real_manifest_has_unique_urn_keys():
    keys = [(e.system, e.edition_code, e.version_code, e.juan) for e in CORPUS.entries]
    assert len(keys) == len(set(keys))


def test_loading_rejects_two_entries_with_the_same_urn_key(tmp_path):
    """四段键重复必须在装载时失败，而不是静默取第一条。

    ``entry_for_urn`` 返回首个匹配。两条目共用四段键时，第二条永远取不到 ——
    引文会被核到另一份文本上，而 URN、书名、版本看起来全都正常。
    """
    (tmp_path / "a.txt").write_text("甲", encoding="utf-8")
    (tmp_path / "b.txt").write_text("乙", encoding="utf-8")
    first = entry(corpus_id="one", path="a.txt", text_chars=1,
                  text_sha256=__import__("hashlib").sha256("甲".encode()).hexdigest())
    second = entry(corpus_id="two", path="b.txt", text_chars=1,
                   text_sha256=__import__("hashlib").sha256("乙".encode()).hexdigest())
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {"version": 2, "normalizer": "x", "note": "", "entries": [
                {name: getattr(first, name) for name in CorpusEntry.__dataclass_fields__},
                {name: getattr(second, name) for name in CorpusEntry.__dataclass_fields__},
            ]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(CorpusError, match="四段键"):
        load_corpus(root=tmp_path, repo_root=tmp_path)


# ── 两份传本的篇章对齐 ────────────────────────────────────────────────

HEADING = re.compile(r"^##\s*六甲日(\S+?)(?:時斷|时断)", re.M)


def section_branches(text: str) -> list[str]:
    """取出「六甲日 X 時斷」里的地支序列，繁简两版都能读。

    **不能要求「六甲日」后正好一个字。** 上游维基文库把三篇的标题录成了
    ``六甲日申時斷``（丢了「壬」）—— 只认单字的话，正则只会命中这三篇残标题，
    看上去像「底本只有 3 篇」，而实际是 12 篇里 9 篇正常、3 篇被上游截断。
    这里取标题最后一个字作地支，对两种形态都成立。
    """
    out: list[str] = []
    for match in HEADING.finditer(text):
        out.append(match.group(1)[-1])
    return out


def test_the_two_transcriptions_align_section_by_section():
    """两份传本的十二篇必须**逐篇对齐**，不只是数量相同。

    此前只数了「都是 12 个 ## 六甲日」。计数相等不代表顺序对：两卷各少一个
    不同的篇、各多一个别的篇，计数仍然相等，而异文核对会从第一篇起就错位。
    """
    base = section_branches(CORPUS.text(BASE))
    collation = section_branches(CORPUS.text(COLLATION))

    assert len(base) == 12, f"底本应有 12 篇，实得 {base}"
    assert base == collation, f"两本篇章顺序不一致：\n  底本 {base}\n  对照 {collation}"


def test_the_base_transcription_keeps_the_variant_reading_marker():
    """四库本的「（一云）」异读是**底本特征**，对照本没有。

    这不是缺陷，是两份传本的真实差别。它必须可查，因为「引用哪一版」直接
    影响断语 —— 用户看到的原文里有没有这句异读，是能复核的。
    """
    assert flat(CORPUS.text(BASE)).count("（一云）") >= 50
    assert flat(CORPUS.text(COLLATION)).count("（一云）") == 0


# ── 原子与清单的对应关系 ──────────────────────────────────────────────


def test_every_atom_cites_a_citable_entry():
    """原子只能引 ``role="base"`` 的卷册。

    加载器已经拦了，这里直接从原始 JSON 再验一遍 —— 两道检查针对的是
    不同的东西：加载器拦的是「这次加载」，这里拦的是「文件里躺着什么」。
    """
    atoms = atom_payloads()
    assert atoms, "原子目录里没有原子"
    for atom in atoms:
        urn = try_parse(atom["urn"])
        assert urn is not None, f"{atom.get('rule_id')} 的 URN 解析不了：{atom['urn']}"
        target = CORPUS.entry_for_urn(urn)
        assert target.role == "base", f"{atom['rule_id']} 引用了 {target.role} 卷册"


def test_every_citable_entry_is_actually_consumed():
    """可引用的底本必须至少被一条原子用上。

    固化了一份底本却没人引用，说明要么规则没录完，要么这份底本其实该是
    ``reserve``。两种情况都该被看见 —— 否则 corpus 会悄悄堆积无人核对的文本，
    而「底本已固化」这句话会让人以为相关工作已经完成。
    """
    cited = {
        CORPUS.entry_for_urn(parse(atom["urn"])).corpus_id
        for atom in atom_payloads()
    }
    citable = {item.corpus_id for item in CORPUS.entries if item.is_citable}

    assert citable <= cited, f"以下可引用底本没有任何原子在用：{sorted(citable - cited)}"


def test_classical_rules_point_at_entries_that_exist():
    """规则库里的每条典籍断语，URN 都必须能在 corpus 里反查到。

    加载期已经核过，这条守的是**装配之后**：规则被复制、改写、手工注入
    registry 时，URN 可能指向一个不存在的卷册，而引文校验不会再跑。
    """
    for rule in default_registry().select():
        if not rule.urn:
            continue
        parsed = try_parse(rule.urn)
        assert parsed is not None, f"{rule.id} 的 URN 解析不了：{rule.urn}"
        entry = CORPUS.entry_for_urn(parsed)
        assert entry.is_citable, f"{rule.id} 引用了不可引用的卷册：{entry.corpus_id}"

"""规则原子（Rule Atom）：把典籍断语从 JSON 加载成可计算规则。

**作者格式**与**运行格式**分开：``rule_atom.json`` 是给人写、给脚本抽取的
中间产物，:class:`~knowledge.rules.Rule` 是引擎实际用的对象。加载器负责这一跳，
并在这跳上把四条守卫全部走一遍：

1. **URN 必须能解析** —— 解析不出就说明定位信息不完整，后面的反查全是空谈。
2. **引文必须能在底本里逐字找到** —— 这是整套引证体系里最关键的一条。
   一条引文如果在底本里找不到，它就不是引文，是编的。
3. **引文元数据必须与底本一致** —— 原子文件里可以（可选地）重述书名、底本、
   章节名。重述了就要对得上。写死一遍是为了让原子文件自己可读，
   交叉核对是为了让它可以自证 —— 两者都要，不然「可读」会变成「可以撒谎」。
4. **条件键必须在事实词表内、主题与流派必须已登记** —— 拼错的条件键不会报错，
   只会让规则永远匹配不上，变成一条没人发现的死规则。

**出处信息从底本反查，不从原子文件抄。** 原子只给 ``urn`` + ``exact_quote``，
``book`` / ``edition`` / ``chapter`` / ``url`` / ``retrieved_on`` 全部由
:meth:`~knowledge.corpus.Corpus.citation` 从 corpus 生成。这样「引文元数据
与底本不一致」这类漂移在结构上就不可能发生。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from knowledge.corpus import Corpus, CorpusError
from knowledge.facts import FACT_SCHEMA
from knowledge.provenance import ReviewStatus, SourceTier
from knowledge.rules import Rule
from knowledge.schools import SchoolRegistry
from knowledge.urn import DivinationUrn
from knowledge.urn import parse as parse_urn

ATOM_VERSION = 1

REQUIRED_KEYS = ("atom_version", "rule_id", "urn", "citation", "condition", "assertion")
OPTIONAL_KEYS = ("confidence", "school", "category", "review_status", "note",
                 "conflict_slot", "conflict_value", "version")
CITATION_KEYS = ("exact_quote", "book", "edition", "chapter")
ASSERTION_KEYS = ("theme_domain", "polarity", "keywords", "conclusion")


class AtomError(ValueError):
    """原子文件不合法。消息可直接展示给用户。"""


@dataclass(frozen=True)
class LoadReport:
    """加载结果，含每条原子在底本里的落点，便于人工复核。"""

    rules: tuple[Rule, ...]
    located: tuple[tuple[str, str, str], ...]
    """(rule_id, urn, 底本实际原文) —— 逐条可见「引文对到了哪一句」。"""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": len(self.rules),
            "rules": [rule.id for rule in self.rules],
            "located": [
                {"rule_id": rule_id, "urn": urn, "exact": exact}
                for rule_id, urn, exact in self.located
            ],
        }


def load_atom_file(
    path: Path,
    corpus: Corpus,
    *,
    schools: SchoolRegistry,
    known_topics: frozenset[str] | set[str],
) -> LoadReport:
    """加载一个原子文件（可以是单条，也可以是条目数组）。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload["atoms"] if isinstance(payload, dict) and "atoms" in payload else payload
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list) or not items:
        raise AtomError(f"{path.name}：原子文件必须是非空数组，或含 atoms 数组的对象。")

    rules: list[Rule] = []
    located: list[tuple[str, str, str]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise AtomError(f"{path.name} 第 {index + 1} 条：原子必须是 JSON 对象。")
        rule, match = _build_rule(item, path, corpus, schools=schools, known_topics=known_topics)
        rules.append(rule)
        located.append((rule.id, rule.urn, match))
    _reject_duplicate_ids(rules, path)
    return LoadReport(tuple(rules), tuple(located))


def load_atom_dir(
    directory: Path,
    corpus: Corpus,
    *,
    schools: SchoolRegistry,
    known_topics: frozenset[str] | set[str],
) -> LoadReport:
    """加载目录下全部 ``*.json`` 原子文件（按文件名排序，保证可复现）。"""
    files = sorted(directory.glob("*.json"))
    if not files:
        raise AtomError(f"目录下没有原子文件：{directory}")
    rules: list[Rule] = []
    located: list[tuple[str, str, str]] = []
    for path in files:
        report = load_atom_file(
            path, corpus, schools=schools, known_topics=known_topics
        )
        rules.extend(report.rules)
        located.extend(report.located)
    _reject_duplicate_ids(rules, directory)
    return LoadReport(tuple(rules), tuple(located))


def revalidate_against_corpus(rule: Rule, corpus: Corpus) -> str:
    """把一条已建好的典籍规则重新对回底本，返回底本实际原文。

    这个函数的存在本身就是一条约束：**任何时刻都能拿现有规则去问底本
    「你引的这句还在吗」**。底本换了版本、引文被改过一个字，都会在这里暴露。
    """
    if not rule.urn:
        raise AtomError(f"规则 {rule.id} 没有 URN，无法对回底本。")
    urn = parse_urn(rule.urn)
    if rule.citation is None or not rule.citation.original_text.strip():
        raise AtomError(f"规则 {rule.id} 没有引文原文，无法对回底本。")
    return corpus.locate(urn, rule.citation.original_text).exact


def atom_template() -> dict[str, Any]:
    """一份最小可用的原子模板，供文档与 API 展示。"""
    return {
        "atom_version": ATOM_VERSION,
        "rule_id": "rule_<体系>_<底本>_<卷>_<篇>_<条>_<序号>",
        "urn": "urn:divination:<体系>:<底本代码>:<版本>:<卷>.<篇>.<条目>",
        "citation": {"exact_quote": "<底本逐字原文，不得改写>"},
        "condition": {"<事实词表里的键>": "<期望值>"},
        "assertion": {
            "theme_domain": "<已登记主题 ID>",
            "polarity": "positive | negative | neutral",
            "keywords": ["<关键词>"],
            "conclusion": "<对原文的现代汉语转述>",
        },
        "confidence": "LOW | MEDIUM | HIGH",
        "school": "<已登记流派 ID>",
        "category": "<类别标签>",
        "review_status": "UNREVIEWED | REVIEWED | ACTIVE",
    }


# ── 内部 ──────────────────────────────────────────────────────────────


def _build_rule(
    item: dict[str, Any],
    path: Path,
    corpus: Corpus,
    *,
    schools: SchoolRegistry,
    known_topics: frozenset[str] | set[str],
) -> tuple[Rule, str]:
    where = f"{path.name} 的原子 {item.get('rule_id', '<缺 rule_id>')!r}"
    _reject_unknown_keys(item, where)
    for key in REQUIRED_KEYS:
        if key not in item:
            raise AtomError(f"{where} 缺少必需字段：{key}")
    if item["atom_version"] != ATOM_VERSION:
        raise AtomError(
            f"{where} 的 atom_version={item['atom_version']!r}，本加载器只认 {ATOM_VERSION}。"
        )

    rule_id = _require_text(item["rule_id"], f"{where} 的 rule_id")
    urn = _parse_urn(item["urn"], where)

    citation_block = item["citation"]
    if not isinstance(citation_block, dict):
        raise AtomError(f"{where} 的 citation 必须是对象。")
    for key in citation_block:
        if key not in CITATION_KEYS:
            raise AtomError(f"{where} 的 citation 含未知字段：{key}")
    quote = _require_text(citation_block.get("exact_quote"), f"{where} 的 citation.exact_quote")

    # 关键守卫：引文必须在底本里逐字找得到。
    try:
        match = corpus.locate(urn, quote)
    except CorpusError as exc:
        raise AtomError(f"{where} 的引文无法在底本中定位。\n{exc}") from exc

    _cross_check_citation(citation_block, urn, corpus, where)

    condition = item["condition"]
    if not isinstance(condition, dict) or not condition:
        raise AtomError(f"{where} 的 condition 必须是非空对象。")
    unknown_keys = sorted(set(condition) - set(FACT_SCHEMA))
    if unknown_keys:
        raise AtomError(
            f"{where} 的 condition 引用了事实词表里不存在的键：{'、'.join(unknown_keys)}。"
            "条件键拼错不会报错，只会让这条规则永远匹配不上。"
        )

    assertion = item["assertion"]
    if not isinstance(assertion, dict):
        raise AtomError(f"{where} 的 assertion 必须是对象。")
    for key in assertion:
        if key not in ASSERTION_KEYS:
            raise AtomError(f"{where} 的 assertion 含未知字段：{key}")
    for key in ("theme_domain", "conclusion"):
        if key not in assertion:
            raise AtomError(f"{where} 的 assertion 缺少 {key}")

    topic = _require_text(assertion["theme_domain"], f"{where} 的 assertion.theme_domain")
    if topic not in set(known_topics):
        raise AtomError(
            f"{where} 的主题 {topic!r} 未登记；已登记：{'、'.join(sorted(known_topics))}。"
        )
    conclusion = _require_text(assertion["conclusion"], f"{where} 的 assertion.conclusion")

    keywords = assertion.get("keywords", [])
    if not isinstance(keywords, list) or any(not isinstance(w, str) for w in keywords):
        raise AtomError(f"{where} 的 assertion.keywords 必须是字符串数组。")

    school = item.get("school", "zi_ping_orthodox")
    if not schools.has(school):
        # 措辞与 SchoolRegistry.require 对齐。同一个失败（流派没注册）在
        # 两条加载路径上会有两种说法时，读日志的人会以为遇到了两个问题。
        raise AtomError(
            f"{where} 引用了未注册的流派 {school!r}；已注册：{'、'.join(schools.ids())}。"
        )

    status = ReviewStatus(item.get("review_status", ReviewStatus.UNREVIEWED))
    # 与上面的 locate 一样包一层：role 门禁在这里拒绝时（URN 指向对照本或备存本），
    # 裸 CorpusError 不会说「是哪条原子」。报错不带定位信息，读日志的人就得到
    # 一句无从下手的话。
    try:
        citation = corpus.citation(urn, quote)
    except CorpusError as exc:
        raise AtomError(f"{where} 无法构成可引用的出处。\n{exc}") from exc
    rule = Rule(
        id=rule_id,
        source=f"{citation.book}（{citation.edition}）",
        school=school,
        category=item.get("category", "classical"),
        condition=dict(condition),
        conclusion=conclusion,
        confidence=item.get("confidence", "LOW"),
        topic=topic,
        source_tier=SourceTier.CLASSICAL,
        review_status=status,
        citation=citation,
        version=str(item.get("version", "1")),
        conflict_slot=item.get("conflict_slot", ""),
        conflict_value=item.get("conflict_value", ""),
        polarity=assertion.get("polarity", "neutral"),
        keywords=tuple(keywords),
        note=item.get("note", ""),
    )
    return rule, match.exact


def _parse_urn(value: Any, where: str) -> DivinationUrn:
    if not isinstance(value, str) or not value.strip():
        raise AtomError(f"{where} 缺少 urn。")
    try:
        return parse_urn(value)
    except ValueError as exc:
        raise AtomError(f"{where} 的 urn 不合法：{exc}") from exc


def _cross_check_citation(
    block: dict[str, Any], urn: DivinationUrn, corpus: Corpus, where: str
) -> None:
    """原子文件里若重述了出处元数据，必须与底本对得上。

    允许重述是为了让原子文件自己可读（不用去翻 manifest 才知道引的是哪本书）；
    交叉核对是为了让它可以自证。只允许前者的话，「可读」会退化成「可以撒谎」。
    """
    entry = corpus.entry_for_urn(urn)
    expectations = {
        "book": entry.book,
        "edition": entry.edition,
    }
    for key, expected in expectations.items():
        stated = block.get(key)
        if stated and stated != expected:
            raise AtomError(
                f"{where} 的 citation.{key} 与底本不符："
                f"原子写 {stated!r}，底本记录 {expected!r}。"
            )
    chapter = block.get("chapter")
    if chapter:
        label = corpus.chapter_label(urn)
        if label and label not in str(chapter):
            raise AtomError(
                f"{where} 的 citation.chapter 与篇章表不符："
                f"原子写 {chapter!r}，底本篇章表写 {label!r}。"
            )


def _require_text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AtomError(f"{where} 不能为空。")
    return value.strip()


def _reject_unknown_keys(item: dict[str, Any], where: str) -> None:
    unknown = sorted(set(item) - set(REQUIRED_KEYS) - set(OPTIONAL_KEYS))
    if unknown:
        raise AtomError(f"{where} 含未知字段：{'、'.join(unknown)}")


def _reject_duplicate_ids(rules: list[Rule], path: Path) -> None:
    seen: set[str] = set()
    for rule in rules:
        if rule.id in seen:
            raise AtomError(f"{path}：规则 ID 重复：{rule.id}")
        seen.add(rule.id)

"""底本语料库：把「原文」变成可以逐字核对的东西。

``corpus/canonical/`` 下是固化好的公有领域底本，``manifest.json`` 记录每卷的
来源修订、永久链接与两级哈希。本模块负责：

1. **校验完整性** —— 读文件重算 sha256，与 manifest 对不上就报出来。
   这是「原文不可被无痕篡改」的落点：改了 corpus 里的一个字，测试就红。
2. **逐字定位引文** —— :meth:`Corpus.locate` 把一条 ``exact_quote`` 放回底本正文里
   找，找不到就拒绝。这是整套引证体系里最关键的一条守卫：它让「引文写错一个字」
   从「没人发现」变成「加载失败」。
3. **URN 反查** —— :meth:`Corpus.citation` 由 URN 取出书名、底本、版本、永久链接，
   组成一条可核验的 :class:`~knowledge.provenance.Citation`。

关于空白：底本是按版面断行的，同一句话里带着换行；而引用时不会带。所以比对前
把两侧的空白**全部**折叠掉。副作用是它同时抹掉了「这里本来有换行」的信息，
因此折叠形式**只用于比对**，回填引用原文时用的是映射回原串的区间。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from knowledge.provenance import Citation
from knowledge.urn import DivinationUrn

REPO = Path(__file__).resolve().parent.parent
CORPUS_ROOT = REPO / "corpus" / "canonical"

ROLE_BASE = "base"
"""底本：可供规则原子引用。URN 的 ``edition`` + ``version`` 反查的就是它。"""

ROLE_COLLATION = "collation"
"""对照本：同一部书的另一传本。**不可供原子引用** —— 它存在的意义是核异文。"""

ROLE_RESERVE = "reserve"
"""备存：已固化但当前无消费者（例如尚无排盘引擎的系统）。"""

ROLES = (ROLE_BASE, ROLE_COLLATION, ROLE_RESERVE)


class CorpusError(RuntimeError):
    """底本缺失、哈希不符或引文找不到。"""


@dataclass(frozen=True)
class CorpusEntry:
    """一卷已固化的底本。"""

    corpus_id: str
    system: str
    edition_code: str
    book: str
    edition: str
    role: str
    juan: str
    title: str
    source_site: str
    source_page: str
    source_url: str
    source_revid: int
    source_revision_sha1: str
    source_revision_timestamp: str
    version_code: str
    license: str
    transcription_note: str
    """转录状态。维基文库是手录本，不是校勘本 —— 不写清楚就会被当成校勘本用。"""
    retrieved_on: str
    normalizer: str
    path: str
    text_sha256: str
    text_chars: int

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise CorpusError(
                f"{self.corpus_id} 的 role 未登记：{self.role!r}；已登记：{'、'.join(ROLES)}。"
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CorpusEntry:
        missing = [name for name in cls.__dataclass_fields__ if name not in data]
        if missing:
            raise CorpusError(
                f"manifest 条目 {data.get('corpus_id', '?')} 缺字段：{'、'.join(missing)}。"
                "manifest 格式变过，跑 python scripts/fetch_corpus.py --fetch 重新固化。"
            )
        return cls(**{name: data[name] for name in cls.__dataclass_fields__})

    @property
    def is_citable(self) -> bool:
        return self.role == ROLE_BASE

    @property
    def urn_version(self) -> str:
        return self.version_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_id": self.corpus_id,
            "system": self.system,
            "edition_code": self.edition_code,
            "book": self.book,
            "edition": self.edition,
            "role": self.role,
            "is_citable": self.is_citable,
            "juan": self.juan,
            "title": self.title,
            "source_site": self.source_site,
            "source_page": self.source_page,
            "source_url": self.source_url,
            "source_revid": self.source_revid,
            "version_code": self.version_code,
            "license": self.license,
            "transcription_note": self.transcription_note,
            "retrieved_on": self.retrieved_on,
            "path": self.path,
            "text_chars": self.text_chars,
            "text_sha256": self.text_sha256,
        }


@dataclass(frozen=True)
class QuoteMatch:
    """一条引文在底本正文里的落点。"""

    urn: str
    quote: str
    """调用方给的引文。"""

    exact: str
    """底本里的**实际原文**（保留原断行）。可能与 ``quote`` 空白不同。"""

    context_before: str
    context_after: str

    @property
    def is_verbatim(self) -> bool:
        """引文与底本原文是否**逐字符**相同（含空白）。

        为假不代表引文有问题 —— 底本按版面断行，引用时一般不带换行，
        所以空白不同是常态。它只是让调用方知道「要不要展示底本原样」。
        真正有意义的是「字有没有被改过」，那由 :meth:`Corpus.locate`
        找不到就报错来保证，不靠这个属性。
        """
        return self.exact == self.quote

    def to_dict(self) -> dict[str, Any]:
        return {
            "urn": self.urn,
            "quote": self.quote,
            "exact": self.exact,
            "context_before": self.context_before,
            "context_after": self.context_after,
            "is_verbatim": self.is_verbatim,
        }


def _flatten(text: str) -> tuple[str, list[int]]:
    """折叠空白，并保留「折叠后第 i 个字符 = 原串第几个字符」的映射。"""
    chars: list[str] = []
    positions: list[int] = []
    for index, char in enumerate(text):
        if not char.isspace():
            chars.append(char)
            positions.append(index)
    return "".join(chars), positions


class Corpus:
    """已固化的底本集合。

    ``manifest.json`` 里的 ``path`` 是**仓库相对路径**，所以这里必须显式拿到
    仓库根目录 —— 不能靠 ``root.parent.parent`` 去推：corpus 目录将来挪个位置，
    推出来的路径会静默指错地方，而「读到了另一个文件」这种事不会报错。
    """

    def __init__(self, root: Path, entries: tuple[CorpusEntry, ...], repo_root: Path) -> None:
        self.root = root
        self.repo_root = repo_root
        self.entries = entries
        self._texts: dict[str, str] = {}

    def path_of(self, entry: CorpusEntry) -> Path:
        return self.repo_root / entry.path

    # ── 读取 ──────────────────────────────────────────────────────────

    def text(self, entry: CorpusEntry) -> str:
        if entry.corpus_id not in self._texts:
            path = self.path_of(entry)
            if not path.exists():
                raise CorpusError(
                    f"底本文件缺失：{entry.path}。"
                    "先跑 python scripts/fetch_corpus.py --fetch 固化底本。"
                )
            self._texts[entry.corpus_id] = path.read_text(encoding="utf-8")
        return self._texts[entry.corpus_id]

    def entry_for_urn(self, urn: DivinationUrn) -> CorpusEntry:
        """按 URN 定位到具体一卷。

        四段全部要匹配，**包括版本** —— 少比版本就会让两个版本的引用
        指向同一份文本，而这正是 URN 要多带一段版本的理由。
        """
        for entry in self.entries:
            if (
                entry.system == urn.system
                and entry.edition_code == urn.edition
                and entry.version_code == urn.version
                and entry.juan == urn.juan
            ):
                return entry
        raise CorpusError(
            f"URN 指向的底本卷册不在 corpus 里：{urn}。"
            f"已固化：{'、'.join(sorted(f'{e.edition_code}:{e.version_code}:{e.juan}' for e in self.entries))}"
        )

    # ── 校验 ──────────────────────────────────────────────────────────

    def problems(self) -> list[str]:
        """返回全部完整性问题；空列表表示 corpus 与 manifest 完全一致。

        查两类：**文件与 manifest 的哈希是否对得上**，以及**篇章表的标签是否
        真的出现在底本正文里**。后者不是多余的：``chapters.json`` 是手写的，
        标签写错一个字，URN 反查回来的出处就会宣称一个底本里并不存在的篇名 ——
        而 URN 反查的全部意义就是「宣称什么，底本里就得有什么」。
        """
        issues: list[str] = []
        for entry in self.entries:
            path = self.path_of(entry)
            if not path.exists():
                issues.append(f"{entry.path}：文件缺失")
                continue
            text = path.read_text(encoding="utf-8")
            actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if actual != entry.text_sha256:
                issues.append(
                    f"{entry.path}：内容与 manifest 不符"
                    f"（期望 {entry.text_sha256[:16]}，实际 {actual[:16]}）"
                )
                # 到此已经判定这份正文不可信，**不要再往下做派生检查**：
                # 拿一份「不知道被改成了什么样」的文本去核篇章表标签，报出来的
                # 「篇名找不到」只是哈希不符的副产品，却会把诊断指向别的地方。
                # 修好内容再重跑，篇章表那项才会给出有意义的结果。
                continue
            # 篇章表只对底本校验：对照本是另一传本，用字本就可能不同，
            # 拿它的正文去判底本的篇名对不对，只会得到假警报。
            if entry.is_citable:
                issues.extend(self._chapter_problems(entry, text))
        return issues

    def _chapter_problems(self, entry: CorpusEntry, text: str) -> list[str]:
        flat, _ = _flatten(text)
        issues: list[str] = []
        for key, label in self.chapters(entry).items():
            juan, _, _ = key.partition(".")
            if juan != entry.juan:
                continue
            if _flatten(label)[0] not in flat:
                issues.append(
                    f"{entry.path}：篇章表 {key!r} 的标签 {label!r} "
                    "在该卷底本正文里找不到"
                )
        return issues

    # ── 引文定位与反查 ────────────────────────────────────────────────

    def locate(self, urn: DivinationUrn, quote: str) -> QuoteMatch:
        """在 URN 指向的底本里逐字定位引文；找不到直接报错。

        找不到时必须**报错而不是放行**：一条引文如果在底本里找不到，
        它就不是引文，是编的。放行等于把「不编造命理规则」这条红线交给运气。
        """
        needle = quote.strip()
        if not needle:
            raise CorpusError(f"引文为空，无法核对：{urn}")
        entry = self.entry_for_urn(urn)
        text = self.text(entry)
        flat_text, positions = _flatten(text)
        flat_quote, _ = _flatten(needle)
        start = flat_text.find(flat_quote)
        if start < 0:
            raise CorpusError(
                f"引文在底本中找不到：{urn}\n"
                f"  引文：{needle[:80]}{'…' if len(needle) > 80 else ''}\n"
                f"  底本：{entry.path}\n"
                "  引文必须是底本里的逐字原文（空白可以不同），不得改写。"
            )
        end = start + len(flat_quote)
        begin_index = positions[start]
        end_index = positions[end - 1] + 1
        return QuoteMatch(
            urn=urn.to_urn(),
            quote=needle,
            exact=text[begin_index:end_index],
            context_before=text[max(0, begin_index - 40):begin_index],
            context_after=text[end_index:end_index + 40],
        )

    def citation(self, urn: DivinationUrn, quote: str, chapter_label: str = "") -> Citation:
        """由 URN + 引文反查出一条可核验的完整出处。

        只接受 ``role="base"`` 的底本。对照本是同一部书的另一传本，正文也在
        corpus 里、引文同样找得到 —— 这里不拦的话，一条引文可以「核验通过」
        却指向一个没有版本声明的文本，URN 的 ``edition`` 段反查回来是
        「所据底本未标註」。那正是「底本未定」本身，不能算核验通过。
        """
        entry = self.entry_for_urn(urn)
        if not entry.is_citable:
            raise CorpusError(
                f"URN 指向的不是可引用的底本：{urn}\n"
                f"  {entry.corpus_id} 的 role={entry.role!r}，版本说明：{entry.edition}\n"
                "  只有 role='base' 的版本可供引用；对照本与备存本只能用于核异文。"
            )
        match = self.locate(urn, quote)
        label = chapter_label or self.chapter_label(urn)
        return Citation(
            book=entry.book,
            edition=entry.edition,
            chapter=f"{entry.title}·{label}" if label else entry.title,
            original_text=match.quote,
            url=entry.source_url,
            urn=urn.to_urn(),
            retrieved_on=date.fromisoformat(entry.retrieved_on),
        )

    def chapters(self, entry: CorpusEntry) -> dict[str, str]:
        """读取该底本的篇章代码表（``<edition>/chapters.json``）。

        没有这张表，URN 里的 ``chapter`` 段就只是一串 ASCII —— 反查回来的
        出处说明会是「j8.liujia_ri」这种给人看的东西。
        """
        path = self.path_of(entry).parent / "chapters.json"
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {key: value for key, value in payload.get("chapters", {}).items()}

    def chapter_label(self, urn: DivinationUrn) -> str:
        if not urn.chapter:
            return ""
        entry = self.entry_for_urn(urn)
        return self.chapters(entry).get(f"{urn.juan}.{urn.chapter}", "")

    def atom_dirs(self) -> tuple[Path, ...]:
        """全部带 ``atoms/`` 的底本目录（已排序）。

        排序不是为了好看：规则库的装配顺序会影响 ``RuleRegistry`` 的插入顺序，
        进而影响 ``stats()`` 的遍历顺序与任何「取第一条」的行为。目录顺序
        由文件系统决定的话，同一份代码在两台机器上可能给出不同结果。
        """
        return tuple(sorted(
            path for path in self.root.iterdir()
            if path.is_dir() and (path / "atoms").is_dir()
        ))

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "total": len(self.entries),
            "entries": [entry.to_dict() for entry in self.entries],
        }


def load_corpus(root: Path | None = None, repo_root: Path | None = None) -> Corpus:
    """从 manifest 装载 corpus。"""
    base = root or CORPUS_ROOT
    repo = repo_root or REPO
    manifest_path = base / "manifest.json"
    if not manifest_path.exists():
        raise CorpusError(
            f"找不到 corpus manifest：{manifest_path}。"
            "先跑 python scripts/fetch_corpus.py --fetch 固化底本。"
        )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = tuple(CorpusEntry.from_dict(item) for item in payload.get("entries", []))
    return Corpus(base, entries, repo)

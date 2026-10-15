"""底本抓取与固化：把公有领域底本钉成不可变的仓库资产。

为什么必须固化到仓库，而不是运行时联网取：

1. **上游会被编辑。** 维基文库《紫微斗數全書·卷一》的最后修订是 2026-08-07，
   《三命通會·卷五》是 2026-04-23 —— 同一个 URL 的正文是会变的。
   「可核验的原文」如果指向一个会变的页面，那它就不是可核验的。
2. **离线可复现。** 测试不能依赖网络：本机 ctext.org 返回的是拦截页
   （三个不同 URL 返回完全相同的 2781 字节），国图 read.nlc.cn 超时。
   当前唯一可达的全文来源是维基文库。
3. **篡改可见。** manifest 里的 sha256 让「原文被悄悄改过一个字」变成一条红测试，
   而不是一个没人发现的引用漂移。

两级哈希的分工：

- ``source_sha1``：MediaWiki 自己给该修订版本的 sha1，用来确认「上游这一版没变」。
- ``text_sha256``：我们对**规范化后**文本算的哈希，用来确认「仓库里的文件没被改」。

两者都要，因为它们是两件事：前者防上游漂移，后者防本地篡改。

底本裁定（为什么《三命通會》引的是四庫全書本，不是维基文库那个转录本）
------------------------------------------------------------------

维基文库上《三命通會》有两个互不相同的页面：

- ``三命通會/卷八``（revid 845354）——页头只有 ``{{Novel}}``，**没有任何版本声明**。
  母页只给了撰人考证，不说转的是哪个本子。
- ``三命通會 (四庫全書本)/卷08``（revid 761697）——页头 ``{{SKQS header}}``，
  正文首行是「欽定四庫全書／明　萬民英　撰」，页脚有 ``<子部,術數類,命書相書之屬,三命通會>``。

URN 的 ``edition`` 段要能反查到「这是哪一版」。一个不说自己是什么本子的文本
反查不出任何版本信息 —— 那正是「底本未定」这个问题的本体。所以底本取四庫全書本，
转录本降为**对照本**保留。

两个传本**确实有异文**，不是抄手笔误级的差别：甲午日甲子時一条，四庫本作
「…俱貴（一云）髙（一云）身孤有財清貴有名乙巳月破祖夭乙亥月自刑刃死癸亥月旺中惡死」，
转录本止于「俱貴」。留对照本就是为了让这类差异有据可查，而不是被悄悄抹平。

两个页面都**未经扫描校对**（四庫本页头自己写着「請根據四庫全書掃描版校對本頁」）。
这一点记在 manifest 的 ``transcription_note`` 里，不假装它是校勘本。

用法::

    python scripts/fetch_corpus.py --verify     # 只校验本地（默认，不联网）
    python scripts/fetch_corpus.py --fetch      # 联网抓取并更新 manifest
    python scripts/fetch_corpus.py --fetch --proxy http://127.0.0.1:7890
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "corpus" / "canonical" / "manifest.json"
NORMALIZER = "corpus-normalize/2"
"""规范化器版本。

换版本号是必须的：同一份 wikitext 在不同规范化器下产出不同纯文本，
``text_sha256`` 的含义跟着变，不换号就会让旧哈希悄悄对不上新正文。

本版相对最初的差别，全部由四庫本的写法逼出来：

- 最初用非贪婪正则剥模板，在四庫本上**是错的** —— ``{{SK notes|…{{SKchar|2824}}…}}``
  是嵌套的，非贪婪会在内层 ``}}`` 处提前收尾，把半个模板壳留在正文里。
  改成配对匹配（:func:`expand_sk_notes`）。
- ``{{SK anchor|X}}``（四庫本的行内篇题标记）展成 ``## X``，让抽取器能切章节。
- ``{{SKchar|N}}`` 换成 ``□``（见 :data:`GAP_MARK`）。
"""

DEFAULT_PROXY = "http://127.0.0.1:7890"

sys.path.insert(0, str(REPO))

# role 的取值定义在消费侧（knowledge.corpus），不在这里另立一套。
# 生产者和消费者各写一份常量，迟早会漂移成两个不同的字符串，
# 而那时 CorpusEntry.__post_init__ 会把一个合法的 role 判成非法 ——
# 报错信息指向「未登记的 role」，真因却在两处常量不一致。
from knowledge.corpus import (
    ROLE_BASE,
    ROLE_COLLATION,
    ROLE_RESERVE,
)

SITE_CODES: dict[str, str] = {
    "zh.wikisource.org": "ws",
}
"""站点到版本代码前缀的映射。

URN 的版本段必须是 ``[a-z0-9_]``，不能带域名和点号，所以站点要有个短码。
映射表写死在这里，而不是从域名现推 —— 「ws」是人定的约定，不是能从
``zh.wikisource.org`` 里算出来的东西。未登记的站点直接报错，避免出现
两个站点各自推出同一个短码、URN 撞车。
"""


@dataclass(frozen=True)
class Source:
    """一卷底本的抓取来源。"""

    corpus_id: str
    system: str
    edition_code: str
    book: str
    edition: str
    """版本说明。必须是**能裁定**的说法：谁撰、哪个本子。
    写不出具体版本时，就说「所据底本未标註」，别含糊过去 ——
    含糊的版本说明等于没有版本说明。"""

    juan: str
    """卷号，用 URN 的形式（``j8``）。**只保留这一种表示** ——
    底本里若同时存 ``8`` 和 ``j8`` 两种写法，URN 反查时就得在两处之间做转换，
    而「两处表示同一个东西」迟早会漂移。展示用的「卷八」在 ``title`` 里。"""

    title: str
    site: str
    page: str
    path: str
    role: str
    transcription_note: str
    """转录状态。维基文库是手录本，不是校勘本；不写清楚就会被当成校勘本用。"""


SOURCES: tuple[Source, ...] = (
    Source(
        corpus_id="bazi_sanmingtonghui_j8",
        system="bazi",
        edition_code="sanmingtonghui",
        book="三命通會",
        edition="欽定四庫全書本（清乾隆間編定；明 萬民英 撰）",
        juan="j8",
        title="卷八",
        site="zh.wikisource.org",
        page="三命通會 (四庫全書本)/卷08",
        path="corpus/canonical/bazi_sanmingtonghui/juan8.txt",
        role=ROLE_BASE,
        transcription_note=(
            "維基文庫手錄本，頁面自標「請根據四庫全書掃描版校對本頁」，"
            "即尚未對掃描件校對；四庫分類見頁腳〈子部,術數類,命書相書之屬,三命通會〉。"
        ),
    ),
    Source(
        corpus_id="bazi_sanmingtonghui_j8_collation",
        system="bazi",
        edition_code="sanmingtonghui",
        book="三命通會",
        edition="維基文庫轉錄本（所據底本未標註）",
        juan="j8",
        title="卷八",
        site="zh.wikisource.org",
        page="三命通會/卷八",
        path="corpus/canonical/bazi_sanmingtonghui/juan8_collation.txt",
        role=ROLE_COLLATION,
        transcription_note=(
            "維基文庫手錄本，頁頭僅有 {{Novel}} 模板，未聲明所據底本；"
            "已加現代標點、用簡體字。與四庫本互校用。"
        ),
    ),
    Source(
        corpus_id="zwds_qianshu_j1",
        system="zwds",
        edition_code="qianshuchongzhen",
        book="紫微斗數全書",
        edition="維基文庫轉錄本（所據底本未標註）",
        juan="j1",
        title="卷一",
        site="zh.wikisource.org",
        page="紫微斗數全書/卷一",
        path="corpus/canonical/zwds_qianshuchongzhen/juan1.txt",
        role=ROLE_RESERVE,
        transcription_note=(
            "維基文庫手錄本，未聲明所據底本。尚無紫微斗數排盤引擎，"
            "故暫無規則原子可引用 —— 先固化文本，引擎到位後再立原子。"
        ),
    ),
)

# ── 规范化 ────────────────────────────────────────────────────────────

_TABLE = re.compile(r"^\{\|.*?^\|\}", re.S | re.M)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_REF = re.compile(r"<ref[^>]*>.*?</ref>", re.S)
_TAG = re.compile(r"<[^>]+>")
_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
_LINK_ALIAS = re.compile(r"\[\[[^\[\]|]*\|([^\[\]]*)\]\]")
_LINK = re.compile(r"\[\[([^\[\]]*)\]\]")
_EXT_LINK = re.compile(r"\[https?://\S+\s+([^\]]+)\]")
_EXT_LINK_BARE = re.compile(r"\[https?://\S+\]")
_LIST_MARKER = re.compile(r"^[;:#*]+\s*", re.M)
_HEADING = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.M)
_BLANK_RUN = re.compile(r"\n{3,}")

_SK_NOTES_OPEN = "{{SK notes|"
_SK_ANCHOR = re.compile(r"\{\{\s*SK\s*anchor\s*\|\s*([^{}]*?)\s*\}\}")
_SK_CHAR = re.compile(r"\{\{\s*SKchar\s*\|\s*\d+\s*\}\}")

GAP_MARK = "□"
"""底本里读不出字的地方。

四庫本用 ``{{SKchar|NNNN}}`` 表示生僻字，而那个模板**渲染成一张字形图片**
（引自 ``SKQSfont.pdf``），不是 Unicode 字符 —— 文本管道里没有字可拿。
用传统校勘的缺字符 ``□`` 占位，而不是静默删掉：静默删掉会让正文看起来是完整的，
将来有人照着这段写引文，就会引出一句底本里并不存在的话。
"""


def expand_sk_notes(text: str) -> str:
    """把 ``{{SK notes|…}}`` 展成 ``（…）``，返回新文本。

    四庫本用这个模板排小字夹注：命例、异文（``一云``）、范围说明（``下同``）、
    歌訣。夹注是底本正文的一部分 —— 读者看得见 —— 所以**保留内容**，只去掉
    模板壳，并用全角括号标出「这是夹注」，与底本的小字排版对应。

    必须**配对**匹配，不能用正则：夹注里嵌着 ``{{SKchar|…}}``，
    非贪婪正则会在这里提前收尾，把半个模板壳 ``}}`` 留在正文里，
    于是引文里就混进了底本没有的字符。
    """
    out: list[str] = []
    cursor = 0
    while True:
        start = text.find(_SK_NOTES_OPEN, cursor)
        if start < 0:
            out.append(text[cursor:])
            return "".join(out)
        out.append(text[cursor:start])
        depth = 0
        index = start
        while index < len(text):
            if text.startswith("{{", index):
                depth += 1
                index += 2
                continue
            if text.startswith("}}", index):
                depth -= 1
                index += 2
                if depth == 0:
                    break
                continue
            index += 1
        inner = text[start + len(_SK_NOTES_OPEN): index - 2]
        out.append("（" + inner + "）")
        cursor = index


def normalize(wikitext: str) -> str:
    """把 MediaWiki 源码规范成可引用的纯文本。

    顺序有讲究，三条都踩过：

    1. **先剥列表标记，再做任何会产生 ``#`` 的事。** ``_LIST_MARKER`` 会吃掉
       行首的 ``#``，所以它必须跑在「把 ``{{SK anchor|X}}`` 变成 ``## X``」
       和「把 ``== X ==`` 变成 ``## X``」之前。反过来，我们自己生成的标题会被
       当成列表标记剥掉，标题层级全部消失 —— 而标题层级是抽取器切章节的依据。
    2. **展开夹注要早于通用模板剥离。** 夹注里嵌着 ``{{SKchar|…}}``，
       非贪婪正则会在这里提前收尾（见 :func:`expand_sk_notes`）。
    3. **``{{SK anchor|X}}`` 展开成 ``## X``。** 它是四庫本的篇题标记，而且
       **是行内模板**（后面紧接正文，没有换行），所以展开时要自己补换行，
       否则整段正文会被并进标题行。
    4. **``{{SKchar|N}}`` 换成 ``□``**（见 :data:`GAP_MARK`）。

    另外这是**确定性**转换：同一份 wikitext 必须永远产出同一份纯文本，
    否则 ``text_sha256`` 就没有意义。所以这里不用任何依赖时间、随机数或
    环境的东西。
    """
    text = wikitext
    text = _TABLE.sub("", text)
    text = _COMMENT.sub("", text)
    text = _REF.sub("", text)
    text = _LIST_MARKER.sub("", text)
    text = expand_sk_notes(text)
    text = _SK_CHAR.sub(GAP_MARK, text)
    text = _SK_ANCHOR.sub(lambda m: "\n## " + m.group(1) + "\n", text)
    text = _TEMPLATE.sub("", text)
    text = _LINK_ALIAS.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    text = _EXT_LINK.sub(r"\1", text)
    text = _EXT_LINK_BARE.sub("", text)
    text = _TAG.sub("", text)
    text = text.replace("'''", "").replace("''", "")
    text = _HEADING.sub(lambda m: "#" * len(m.group(1)) + " " + m.group(2), text)
    # 四庫本用「　」（表意空格）缩排。行首行尾的缩排是版面，不是文字，
    # 去掉；行内的「　」（如「六甲日生甲子時　敗中印綬官生至」）保留 ——
    # 那是原文的分句停顿，删掉就把两半粘成一句了。
    lines = [line.strip(" \t\u3000") for line in text.splitlines()]
    return _BLANK_RUN.sub("\n\n", "\n".join(lines)).strip() + "\n"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── 抓取 ──────────────────────────────────────────────────────────────


def _opener(proxy: str) -> urllib.request.OpenerDirector:
    handlers: list[Any] = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    opener.addheaders = [
        ("User-Agent", "MingLiAgent-CorpusFetcher/1.0 (offline research; public domain texts)")
    ]
    return opener


def fetch_revision(source: Source, proxy: str) -> tuple[str, int, str, str]:
    """抓取页面当前修订，返回（wikitext, revid, sha1, timestamp）。

    取 ``sha1`` 而不只取正文：MediaWiki 为每个修订版本算了一个 sha1，
    把它记进 manifest，将来就能确认「上游这一版没变」—— 不需要重新抓正文。
    """
    url = "https://%s/w/api.php?%s" % (  # noqa: UP031
        source.site,
        urllib.parse.urlencode({
            "action": "query",
            "titles": source.page,
            "prop": "revisions",
            "rvprop": "content|ids|sha1|timestamp",
            "rvslots": "main",
            "format": "json",
            "formatversion": "2",
        }),
    )
    with _opener(proxy).open(url, timeout=40) as response:
        payload = json.loads(response.read().decode("utf-8"))
    page = payload["query"]["pages"][0]
    if "revisions" not in page:
        raise RuntimeError(f"页面不存在或无法读取：{source.page}")
    revision = page["revisions"][0]
    return (
        revision["slots"]["main"]["content"],
        revision["revid"],
        revision["sha1"],
        revision["timestamp"],
    )


def build_entry(source: Source, proxy: str) -> dict[str, Any]:
    wikitext, revid, sha1, timestamp = fetch_revision(source, proxy)
    text = normalize(wikitext)
    if source.site not in SITE_CODES:
        raise RuntimeError(f"站点未登记短码：{source.site}（见 SITE_CODES）")
    return {
        "corpus_id": source.corpus_id,
        "system": source.system,
        "edition_code": source.edition_code,
        "book": source.book,
        "edition": source.edition,
        "role": source.role,
        "juan": source.juan,
        "title": source.title,
        "source_site": source.site,
        "source_page": source.page,
        # oldid 永久链接：钉住这一版，页面之后被怎么编辑都不影响它。
        "source_url": f"https://{source.site}/w/index.php?oldid={revid}",
        "source_revid": revid,
        "source_revision_sha1": sha1,
        "source_revision_timestamp": timestamp,
        "version_code": f"{SITE_CODES[source.site]}{revid}",
        "license": "Public Domain（原著成書於明代；維基文庫以 {{PD-old}} 收錄）",
        "transcription_note": source.transcription_note,
        "retrieved_on": date.today().isoformat(),
        "normalizer": NORMALIZER,
        "path": source.path,
        "text_sha256": sha256_text(text),
        "text_chars": len(text),
        "text_lines": text.count("\n"),
        "_text": text,
    }


# ── manifest 读写与校验 ───────────────────────────────────────────────


def load_manifest() -> dict[str, Any]:
    if not MANIFEST.exists():
        return {"version": 1, "entries": []}
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def write_manifest(entries: list[dict[str, Any]]) -> None:
    payload = {
        "version": 2,
        "normalizer": NORMALIZER,
        "note": (
            "公有领域底本的不可变版本记录。text_sha256 覆盖规范化后的纯文本；"
            "source_revision_sha1 是上游该修订版本的哈希，用于检测上游漂移。"
            "任何对 corpus/ 下正文的手工修改都会让 text_sha256 对不上。"
            "role 说明每一条为什么在这里：base 供规则原子引用，"
            "collation 是同一部书的另一传本（核异文用），reserve 暂无消费者。"
        ),
        "entries": entries,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def verify(verbose: bool = True) -> int:
    """校验本地正文与 manifest 一致。不联网。"""
    manifest = load_manifest()
    entries = manifest.get("entries", [])
    if not entries:
        print("manifest 为空：尚未固化任何底本。")
        return 1
    failures = 0
    for entry in entries:
        path = REPO / entry["path"]
        if not path.exists():
            print(f"[缺失] {entry['path']}")
            failures += 1
            continue
        text = path.read_text(encoding="utf-8")
        actual = sha256_text(text)
        if actual != entry["text_sha256"]:
            print(
                f"[篡改] {entry['path']}\n"
                f"        manifest 期望 {entry['text_sha256']}\n"
                f"        实际文件     {actual}"
            )
            failures += 1
        elif verbose:
            print(
                f"[一致] {entry['path']}  [{entry.get('role', '?')}]  "
                f"{entry['text_chars']} 字  revid={entry['source_revid']}  {actual[:16]}"
            )
    print(f"--- {len(entries) - failures}/{len(entries)} 卷一致 ---")
    return 0 if failures == 0 else 1


def do_fetch(proxy: str, force: bool) -> int:
    previous = {entry["corpus_id"]: entry for entry in load_manifest().get("entries", [])}
    entries: list[dict[str, Any]] = []
    for source in SOURCES:
        print(f"抓取 {source.book}·{source.title} …", flush=True)
        entry = build_entry(source, proxy)
        old = previous.get(source.corpus_id)
        if old and old["source_revid"] != entry["source_revid"]:
            # 「换了抓取来源」和「上游改了正文」是两件事，混成一句会把人引向
            # 错误的排查方向 —— 前者该去核对新底本，后者该去核对上游历史。
            if old.get("source_page") != source.page:
                print(
                    f"  ⚠ 抓取来源已改指：{old.get('source_page')!r} → {source.page!r}，"
                    f"revid {old['source_revid']} → {entry['source_revid']}。"
                    "已引用旧版本的规则需要重核。"
                )
            else:
                print(
                    f"  ⚠ 上游已改动：revid {old['source_revid']} → {entry['source_revid']}。"
                    "已引用该版本的规则需要复核。"
                )
        if old and old["source_revid"] == entry["source_revid"] and not force:
            if old["text_sha256"] != entry["text_sha256"]:
                raise RuntimeError(
                    f"{source.corpus_id}：revid 未变但规范化结果变了 —— "
                    "要么上游内容变了，要么规范化器变了。确认原因后再改 NORMALIZER 版本。"
                )
        path = REPO / source.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(entry.pop("_text"), encoding="utf-8")
        entries.append(entry)
        print(f"  → {source.path}  revid={entry['source_revid']}  {entry['text_chars']} 字")
    write_manifest(entries)
    print(f"manifest 已更新：{MANIFEST.relative_to(REPO)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="底本抓取与固化")
    parser.add_argument("--fetch", action="store_true", help="联网抓取并更新 manifest")
    parser.add_argument("--verify", action="store_true", help="只校验本地文件（默认）")
    parser.add_argument("--proxy", default=DEFAULT_PROXY, help="HTTP 代理；传空串表示直连")
    parser.add_argument("--force", action="store_true", help="允许同 revid 下覆盖本地正文")
    args = parser.parse_args()
    if args.fetch:
        return do_fetch(args.proxy, args.force)
    return verify()


if __name__ == "__main__":
    sys.exit(main())

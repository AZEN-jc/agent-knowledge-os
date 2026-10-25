"""规则原子抽取管道：从底本正文里切出候选原子。

**它只做机械的那一半。** 一条原子由四部分组成，其中三部分完全由文本决定：

===============  ==========================================
条件             条目标题直接给出（「甲子日甲子时」→ 日柱甲子 + 时柱甲子）
URN              卷号 + 篇章代码 + 条目序号
exact_quote      条目正文
===============  ==========================================

剩下那一部分是**断语的现代汉语转述**（``assertion.conclusion``），它需要判断，
所以不在这里生成 —— 抽取器产出的是**待审队列**，不是规则。队列里每一条都要
人工看过原文、写下转述、置为 ``ACTIVE`` 之后才进 ``atoms/``。

这个分工是刻意的：如果抽取器连转述一起生成，那它就成了一个「用算法编断语」
的东西 —— 而那正是项目红线禁止的。机械的部分交给脚本，判断的部分留给人。

用法::

    python scripts/extract_atoms.py --section 六甲日甲子時斷 --out /tmp/candidates.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from knowledge.corpus import load_corpus
from knowledge.urn import parse as parse_urn

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"

_HEADING = re.compile(r"^(#+)\s*(.+?)\s*$")
# 底本有简繁两种写法（四庫本用「時」，转录本用「时」），两种都要认。
_ENTRY = re.compile(
    rf"^([{STEMS}])([{BRANCHES}])日([{STEMS}])([{BRANCHES}])[时時]",
    re.M,
)

NOTE_OPEN = "（"
"""夹注起始符。由 ``fetch_corpus.normalize`` 生成，见 ``expand_sk_notes``。"""

#: 版面修正清单：底本里**不是章节边界**的标题，以及转录误字。
#:
#: 为什么要有这个文件：卷八第 1044 行有一句诗「明出地上宜為大明君也」，
#: 它和章节标题同级（都是 ``##``），但它属于「六丁日丁未時斷」的正文 ——
#: 按标题级别切分会把该节从中间截断，而且**不会报错**，只是少切出 5 个
#: 条目。同类问题还有转录误字「丁己日戊申時」（应为丁巳日），只认干支的
#: 正则会整条漏掉。
#:
#: 这两类都只能靠人读出来，所以写进清单、由脚本消费，而不是散在代码里
#: 做特判。清单只允许声明「怎么切」，不允许改底本一个字。
LAYOUT_PATH = REPO / "corpus" / "canonical" / "bazi_sanmingtonghui" / "layout.json"


def load_layout() -> dict[str, Any]:
    """读版面修正清单；文件不存在时返回空清单（新底本先能跑）。"""
    if not LAYOUT_PATH.is_file():
        return {"absorbed_headings": [], "entry_aliases": {}, "sections": {}}
    return json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))


def iter_sections(text: str) -> list[str]:
    """列出所有「六X日…時斷」小节标题（不含 ``##``）。"""
    headings: list[str] = []
    for line in text.splitlines():
        match = _HEADING.match(line)
        if not match:
            continue
        title = match.group(2)
        if re.match(rf"^六[{STEMS}]日", title) and ("時斷" in title or "时断" in title):
            headings.append(title)
    return headings


def section_body(text: str, heading_prefix: str, absorbed: tuple[str, ...] = ()) -> str:
    """取出某个章节的正文。

    以**同级或更高级标题**为界，而不是找下一个 ``##``：底本里 ``####`` 的
    小标题（如《紫微斗數全書》「問天府所主若何？」）不能把章节切断。

    ``absorbed`` 里的标题是**正文的一部分**（例如卷八里夹在条目之间的
    诗句），遇到它们不结束本节 —— 否则会把一节从中间截断。
    """
    lines = text.splitlines()
    start: int | None = None
    level = 0
    for index, line in enumerate(lines):
        match = _HEADING.match(line)
        if match and match.group(2).startswith(heading_prefix):
            start, level = index + 1, len(match.group(1))
            break
    if start is None:
        raise SystemExit(f"底本里找不到章节：{heading_prefix}")
    end = len(lines)
    for index in range(start, len(lines)):
        match = _HEADING.match(line := lines[index])
        if not match:
            continue
        if len(match.group(1)) > level:
            continue
        if match.group(2).strip() in absorbed:
            continue  # 诗句标题：属于本节正文，不是边界
        end = index
        break
    return "\n".join(lines[start:end])


def suggest_quote(raw: str) -> str:
    """给出一条**建议**引文，交人工裁剪。

    底本无标点（四庫本），所以「取第一句」无从谈起。能机械判断的边界只有两个：
    第一个句号（转录本有标点），或第一处夹注（四庫本把命例、异文用小字夹注
    排在断语之后）。取两者中靠前的那个。

    **这只是建议。** 引文必须与判定的范围一致 —— 那条断语到底管到哪一句，
    只有人能判断，所以这里给的任何东西都要人工再看一遍。
    """
    stops = [index for index in (raw.find("。"), raw.find(NOTE_OPEN)) if index > 0]
    return raw[: min(stops)].strip() if stops else raw.strip()


def split_entries(body: str, aliases: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """按「X日X时」行首标记切分条目。

    要求匹配在**行首**：正文里「六甲日生甲子时」这类歌诀也含干支字样，
    不锚行首会把歌诀当成条目切出来。

    ``aliases`` 处理底本的转录误字（如「丁己日」应为「丁巳日」）。做法是
    在**等长替换**后的副本上匹配、在原文本上取 ``raw`` —— 这样偏移不变，
    引文仍是底本原字（引文必须逐字回对，不能替底本改字）。
    """
    aliases = aliases or {}
    for wrong, right in aliases.items():
        if len(wrong) != len(right):
            raise SystemExit(f"别名必须等长替换：{wrong!r} → {right!r}")
    match_body = body
    for wrong, right in aliases.items():
        match_body = match_body.replace(wrong, right)

    matches = list(_ENTRY.finditer(match_body))
    entries: list[dict[str, Any]] = []
    for order, match in enumerate(matches, start=1):
        end = matches[order].start() if order < len(matches) else len(match_body)
        raw = body[match.start():end].strip()
        entries.append({
            "order": order,
            "day_stem": match.group(1),
            "day_branch": match.group(2),
            "hour_stem": match.group(3),
            "hour_branch": match.group(4),
            "raw": raw,
            "suggested_quote": suggest_quote(raw),
        })
    return entries


def audit_sections(corpus_id: str) -> dict[str, Any]:
    """逐节对账：每节应有 6 个条目，实际切出几个。

    这是录入 60 节之前的**账本**。没有它，漏掉的条目不会报错 ——
    只是那一节少几条原子，而没人知道少了几条。
    """
    corpus = load_corpus()
    entry = next((item for item in corpus.entries if item.corpus_id == corpus_id), None)
    if entry is None:
        raise SystemExit(f"corpus 里没有 {corpus_id}")
    text = corpus.text(entry)
    layout = load_layout()
    absorbed = tuple(layout.get("absorbed_headings", ()))
    aliases = dict(layout.get("entry_aliases", {}))
    declared = layout.get("sections", {})

    rows: list[dict[str, Any]] = []
    for heading in iter_sections(text):
        body = section_body(text, heading, absorbed)
        found = len(split_entries(body, aliases))
        expected = int(declared.get(heading, {}).get("expected_entries", 6))
        rows.append({
            "section": heading,
            "expected": expected,
            "found": found,
            "ok": found == expected,
            "note": declared.get(heading, {}).get("note", ""),
        })
    unexplained = [row for row in rows if not row["ok"] and not row["note"]]
    return {
        "total_sections": len(rows),
        "total_entries": sum(row["found"] for row in rows),
        "unexplained": unexplained,
        "rows": rows,
    }


def build_candidates(
    corpus_id: str, heading: str, chapter_code: str
) -> dict[str, Any]:
    corpus = load_corpus()
    entry = next((item for item in corpus.entries if item.corpus_id == corpus_id), None)
    if entry is None:
        raise SystemExit(f"corpus 里没有 {corpus_id}")
    layout = load_layout()
    body = section_body(
        corpus.text(entry), heading, tuple(layout.get("absorbed_headings", ()))
    )
    entries = split_entries(body, dict(layout.get("entry_aliases", {})))
    candidates = []
    for item in entries:
        # entry.juan 已经是 URN 形式（"j8"），**不要再加 "j" 前缀** ——
        # 加了会得到 "jj8"，而 "jj8" 恰好也匹配 URN 的卷号正则（j + "j8"），
        # 所以拼错不会报错，只会让所有 URN 指向一个不存在的卷。
        urn = (
            f"urn:divination:{entry.system}:{entry.edition_code}:{entry.version_code}:"
            f"{entry.juan}.{chapter_code}.{_entry_code(item)}"
        )
        parse_urn(urn)  # 早失败：URN 拼错在抽取阶段就该报，不该等到加载规则
        candidates.append({
            "rule_id": f"rule_{entry.system}_{entry.edition_code}_{entry.juan}_{_entry_code(item)}",
            "urn": urn,
            "condition": {
                "day_stem": item["day_stem"],
                "day_branch": item["day_branch"],
                "hour_stem": item["hour_stem"],
                "hour_branch": item["hour_branch"],
            },
            "exact_quote": item["suggested_quote"],
            "raw": item["raw"],
            "assertion": {
                "theme_domain": "destiny",
                "polarity": "neutral",
                "keywords": [],
                "conclusion": "",
            },
            "review_status": "UNREVIEWED",
        })
    return {
        "atom_version": 1,
        "section": heading,
        "corpus_id": corpus_id,
        "urn_edition": f"{entry.system}:{entry.edition_code}:{entry.version_code}",
        "note": (
            "待审队列。conclusion 为空 —— 断语的现代汉语转述需要判断，"
            "不由脚本生成。人工核对原文、写好转述、置为 ACTIVE 后才移入 atoms/。"
        ),
        "extracted": len(candidates),
        "atoms": candidates,
    }


def _entry_code(item: dict[str, Any]) -> str:
    return f"{_pinyin_stub(item['day_stem'])}{_pinyin_stub(item['day_branch'])}" \
           f"_{_pinyin_stub(item['hour_stem'])}{_pinyin_stub(item['hour_branch'])}"


_PINYIN = {
    "甲": "jia", "乙": "yi", "丙": "bing", "丁": "ding", "戊": "wu",
    "己": "ji", "庚": "geng", "辛": "xin", "壬": "ren", "癸": "gui",
    "子": "zi", "丑": "chou", "寅": "yin", "卯": "mao", "辰": "chen",
    "巳": "si", "午": "wu", "未": "wei", "申": "shen", "酉": "you",
    "戌": "xu", "亥": "hai",
}


def _pinyin_stub(char: str) -> str:
    """干支 → 拼音代码。

    条目代码必须是 ``[a-z0-9_]``（URN 的字符集约束），所以中文干支要转写。
    用拼音而不是序号（``d1_z1``）：代码会出现在 URN 和日志里，
    ``jiazi_jiazi`` 比 ``d01_z01`` 一眼能看懂是什么。
    """
    return _PINYIN.get(char, "unknown")


def main() -> int:
    parser = argparse.ArgumentParser(description="从底本抽取规则原子候选")
    parser.add_argument("--corpus-id", default="bazi_sanmingtonghui_j8")
    parser.add_argument("--section", default="六甲日甲子時斷")
    parser.add_argument("--chapter-code", default="liujia_ri")
    parser.add_argument("--out", default="/tmp/atoms_candidates.json")
    parser.add_argument(
        "--audit", action="store_true",
        help="逐节对账（60 节应有 360 条），有未登记的缺条时退出码非 0",
    )
    args = parser.parse_args()

    if args.audit:
        report = audit_sections(args.corpus_id)
        print(f"章节 {report['total_sections']} 节 / 条目 {report['total_entries']} 条")
        for row in report["rows"]:
            mark = "OK " if row["ok"] else "!! "
            print(f"  {mark}{row['section']}  应有 {row['expected']}  实际 {row['found']}"
                  + (f"  （已登记：{row['note']}）" if row["note"] else ""))
        if report["unexplained"]:
            print(f"\n未登记的缺条 {len(report['unexplained'])} 节：")
            for row in report["unexplained"]:
                print(f"  {row['section']}：应有 {row['expected']}，实际 {row['found']}")
            return 1
        print("\n全部对齐。")
        return 0

    payload = build_candidates(args.corpus_id, args.section, args.chapter_code)
    Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"抽出 {payload['extracted']} 条候选 → {args.out}")
    for atom in payload["atoms"]:
        print(f"  {atom['rule_id']}")
        print(f"    {atom['exact_quote'][:60]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main())

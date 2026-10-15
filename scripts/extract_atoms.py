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


def section_body(text: str, heading_prefix: str) -> str:
    """取出某个章节的正文。

    以**同级或更高级标题**为界，而不是找下一个 ``##``：底本里 ``####`` 的
    小标题（如《紫微斗數全書》「問天府所主若何？」）不能把章节切断。
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
        match = _HEADING.match(lines[index])
        if match and len(match.group(1)) <= level:
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


def split_entries(body: str) -> list[dict[str, Any]]:
    """按「X日X时」行首标记切分条目。

    要求匹配在**行首**：正文里「六甲日生甲子时」这类歌诀也含干支字样，
    不锚行首会把歌诀当成条目切出来。
    """
    matches = list(_ENTRY.finditer(body))
    entries: list[dict[str, Any]] = []
    for order, match in enumerate(matches, start=1):
        end = matches[order].start() if order < len(matches) else len(body)
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


def build_candidates(
    corpus_id: str, heading: str, chapter_code: str
) -> dict[str, Any]:
    corpus = load_corpus()
    entry = next((item for item in corpus.entries if item.corpus_id == corpus_id), None)
    if entry is None:
        raise SystemExit(f"corpus 里没有 {corpus_id}")
    body = section_body(corpus.text(entry), heading)
    entries = split_entries(body)
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
    args = parser.parse_args()
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

"""卷八 60 节的录入账本：把散在 13 份 JSON 与 chapters.json 里的状态摆到一处。

**为什么要这个脚本**：每录完一节，状态就散在四个地方 —— 底本切出来的节标题、
``chapters.json`` 的章节登记、原子文件里的 ``coverage``、以及见证表。
靠人记「还剩几节、哪节暂缓了几处」必然漂移。这个脚本只做**读取与对账**，
不改任何数据文件；输出是给人看的一张表，也是给测试用的一份结构化结果。

用法::

    python scripts/chapter_ledger.py                 # 打印 markdown 表格
    python scripts/chapter_ledger.py --check        # 只做不变量检查，不打印
    python scripts/chapter_ledger.py --json         # 输出结构化账本
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from extract_atoms import audit_sections, iter_sections

from knowledge.corpus import load_corpus

CORPUS_ID = "bazi_sanmingtonghui_j8"
ROOT = REPO / "corpus" / "canonical" / "bazi_sanmingtonghui"
ATOMS_DIR = ROOT / "atoms"
CHAPTERS_FILE = ROOT / "chapters.json"
LEDGER_FILE = REPO / "docs" / "reports" / "juan8-chapter-ledger.md"


def _corpus_text() -> str:
    corpus = load_corpus()
    entry = next(item for item in corpus.entries if item.corpus_id == CORPUS_ID)
    return corpus.text(entry)


def _atom_files() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(ATOMS_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        section = payload["section"]
        if section in result:
            raise ValueError(f"两份原子文件都声明了同一节：{section}")
        result[section] = {
            "file": path.name,
            "atoms": len(payload["atoms"]),
            "declared": payload["coverage"]["atoms"],
            "entries_covered": payload["coverage"]["entries_covered"],
            "deferred": payload["coverage"].get("deferred_clauses", 0),
        }
    return result


def build_ledger() -> dict[str, Any]:
    text = _corpus_text()
    titles = iter_sections(text)
    audit = {row["section"]: row for row in audit_sections(CORPUS_ID)["rows"]}
    chapters = json.loads(CHAPTERS_FILE.read_text(encoding="utf-8"))["chapters"]
    title_to_key = {title: key for key, title in chapters.items()}
    atoms = _atom_files()

    rows: list[dict[str, Any]] = []
    for order, title in enumerate(titles, start=1):
        record = atoms.get(title)
        rows.append({
            "order": order,
            "section": title,
            "chapter_key": title_to_key.get(title),
            "expected_entries": audit[title]["expected"],
            "found_entries": audit[title]["found"],
            "status": "recorded" if record else "pending",
            "file": record["file"] if record else None,
            "atoms": record["atoms"] if record else 0,
            "declared": record["declared"] if record else None,
            "entries_covered": record["entries_covered"] if record else 0,
            "deferred": record["deferred"] if record else 0,
        })

    recorded = [row for row in rows if row["status"] == "recorded"]
    return {
        "corpus_id": CORPUS_ID,
        "total_sections": len(rows),
        "recorded_sections": len(recorded),
        "pending_sections": len(rows) - len(recorded),
        "total_entries": sum(row["found_entries"] for row in rows),
        "total_atoms": sum(row["atoms"] for row in rows),
        "total_deferred": sum(row["deferred"] for row in rows),
        "rows": rows,
    }


def problems(ledger: dict[str, Any]) -> list[str]:
    """账本自身的不变量。任何一条不成立都说明有节被漏登或计数漂移。"""
    issues: list[str] = []
    rows = ledger["rows"]
    chapters = json.loads(CHAPTERS_FILE.read_text(encoding="utf-8"))["chapters"]
    keys = {row["chapter_key"] for row in rows if row["chapter_key"]}

    if ledger["total_sections"] != 60:
        issues.append(f"底本切出 {ledger['total_sections']} 节，不是 60 节")
    if ledger["total_entries"] != 360:
        issues.append(f"底本切出 {ledger['total_entries']} 条，不是 360 条")
    if len(set(row["section"] for row in rows)) != len(rows):
        issues.append("节标题重复")
    if keys != set(chapters):
        issues.append(f"chapters.json 里有对不上标题的键：{sorted(set(chapters) - keys)}")
    for row in rows:
        if row["found_entries"] != row["expected_entries"]:
            issues.append(f"第 {row['order']} 节条目数 {row['found_entries']} != {row['expected_entries']}")
        if row["status"] == "recorded":
            if not row["chapter_key"]:
                issues.append(f"第 {row['order']} 节有原子但未登记章节：{row['section']}")
            if row["atoms"] != row["declared"]:
                issues.append(f"{row['file']} 声明 {row['declared']} 条，实际 {row['atoms']} 条")
            if row["entries_covered"] != row["found_entries"]:
                issues.append(f"{row['file']} 覆盖 {row['entries_covered']} 条，底本有 {row['found_entries']} 条")
        elif row["chapter_key"]:
            issues.append(f"第 {row['order']} 节登记了章节却没有原子文件：{row['section']}")
    return issues


def markdown(ledger: dict[str, Any]) -> str:
    lines = [
        "# 卷八录入账本",
        "",
        f"共 {ledger['total_sections']} 节 / {ledger['total_entries']} 条；"
        f"已录 {ledger['recorded_sections']} 节、{ledger['total_atoms']} 条原子、"
        f"暂缓 {ledger['total_deferred']} 处；待录 {ledger['pending_sections']} 节。",
        "",
        "| # | 底本节标题 | 章节键 | 条目 | 状态 | 原子 | 暂缓 | 文件 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in ledger["rows"]:
        lines.append(
            f"| {row['order']} | {row['section']} | {row['chapter_key'] or '—'} | "
            f"{row['found_entries']} | {'已录' if row['status'] == 'recorded' else '待录'} | "
            f"{row['atoms'] if row['status'] == 'recorded' else '—'} | "
            f"{row['deferred'] if row['status'] == 'recorded' else '—'} | "
            f"{row['file'] or '—'} |"
        )
    lines.append("")
    lines.append("由 `python scripts/chapter_ledger.py` 生成，只读取底本与原子文件，不改数据。")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="卷八 60 节录入账本")
    parser.add_argument("--check", action="store_true", help="只检查不变量，不打印表格")
    parser.add_argument("--json", action="store_true", help="输出结构化账本")
    parser.add_argument("--write", action="store_true", help="把 markdown 写入 corpus 目录")
    args = parser.parse_args()

    ledger = build_ledger()
    issues = problems(ledger)
    if args.write and not issues:
        LEDGER_FILE.write_text(markdown(ledger), encoding="utf-8")
        print(f"已写入 {LEDGER_FILE.relative_to(REPO)}")
    if args.check:
        for issue in issues:
            print(issue)
        print("账本自洽。" if not issues else f"发现 {len(issues)} 处不一致")
        return 0 if not issues else 1
    if args.json:
        print(json.dumps(ledger, ensure_ascii=False, indent=2))
    else:
        print(markdown(ledger), end="")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())

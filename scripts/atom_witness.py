"""卷八原子的见证盘工具：找见证、写进测试表。

    python scripts/atom_witness.py find _gengwu_ --steps 60 --out /tmp/w.json
    python scripts/atom_witness.py apply /tmp/w.json --note "卷八 · 六甲日庚午时断"
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from atom_checklist import HOUR_OF_BRANCH, _day_pillar_of

from engines.bazi import BaziCalculator, BirthInput, SxtwlBaziProvider
from knowledge.default_rules import default_registry
from knowledge.facts import extract_facts
from knowledge.provenance import SourceTier

TEST_FILE = REPO / "tests" / "test_structural_rules.py"


def chapter_map(registry: Any) -> dict[str, str]:
    return {
        rule.id: f"{rule.citation.parsed_urn.juan}.{rule.citation.parsed_urn.chapter}"
        for rule in registry.select(source_tier=SourceTier.CLASSICAL)
        if rule.citation is not None
    }


def find(needle: str, steps: int, out: Path, chapter_filter: str | None = None) -> int:
    registry = default_registry()
    calc = BaziCalculator(SxtwlBaziProvider())
    chapter = chapter_map(registry)
    targets = [
        rule
        for rule in registry.select(source_tier=SourceTier.CLASSICAL)
        if needle in rule.id
        and (chapter_filter is None or chapter[rule.id] == chapter_filter)
    ]
    if not targets:
        print(f"没有 rule id 含 {needle!r} 的典籍规则")
        return 2

    index: dict[tuple[str, str], dt.date] = {}
    start = dt.date(1950, 1, 1)
    for offset in range(60):
        day = start + dt.timedelta(days=offset)
        index.setdefault(_day_pillar_of(day), day)

    groups: dict[tuple[str, str, str], list[Any]] = {}
    for rule in targets:
        condition = rule.condition
        key = (condition["day_stem"], condition["day_branch"], condition["hour_branch"])
        groups.setdefault(key, []).append(rule)

    candidates: dict[str, list[tuple[dt.date, int, set[str]]]] = {}
    for (stem, branch, hour_branch), rules in groups.items():
        base = index[(stem, branch)]
        hour = HOUR_OF_BRANCH[hour_branch]
        for step in range(steps):
            day = base + dt.timedelta(days=60 * step)
            chart = calc.calculate_chart(BirthInput(day.year, day.month, day.day, hour))
            matched = {m.rule.id for m in registry.match(extract_facts(chart))}
            for rule in rules:
                if rule.id in matched:
                    candidates.setdefault(rule.id, []).append((day, hour, matched))

    assigned: dict[str, tuple[int, int, int, int]] = {}
    missing: list[str] = []
    for rule in targets:
        options = candidates.get(rule.id, [])
        if not options:
            missing.append(rule.id)
            continue
        group = chapter[rule.id]

        def cost(item: tuple[dt.date, int, set[str]], rule_id: str = rule.id, group: str = group) -> tuple:
            day, _hour, matched = item
            same = {x for x in matched if chapter.get(x) == group} - {rule_id}
            used = sum(
                1
                for value in assigned.values()
                if value[:3] == (day.year, day.month, day.day)
            )
            return (used, len(same), day)

        best = min(options, key=cost)
        assigned[rule.id] = (best[0].year, best[0].month, best[0].day, best[1])

    overlaps: dict[str, list[str]] = {}
    for rule_id, (year, month, day_num, hour) in assigned.items():
        chart = calc.calculate_chart(BirthInput(year, month, day_num, hour))
        matched = {m.rule.id for m in registry.match(extract_facts(chart))}
        group = chapter[rule_id]
        overlaps[rule_id] = sorted(
            x for x in matched if chapter.get(x) == group and x != rule_id
        )

    out.write_text(
        json.dumps(
            {
                "witness": {k: list(v) for k, v in assigned.items()},
                "overlap": overlaps,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"目标 {len(targets)} 条 | 见证 {len(assigned)} 条 | 缺失 {missing}")
    print(f"有重叠 {sum(1 for v in overlaps.values() if v)} 条 -> {out}")
    return 0 if not missing else 1


def insert(text: str, marker: str, block: str) -> str:
    start = text.index(marker)
    end = text.index("\n}\n", start)
    return text[:end] + "\n" + block + text[end:]


def apply(path: Path, note: str) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    witness, overlap = payload["witness"], payload["overlap"]
    text = TEST_FILE.read_text(encoding="utf-8")

    incoming = set(witness) | {k for k, v in overlap.items() if v}
    existing = set(re.findall(r'^    "(rule_[a-z0-9_]+)":', text, re.M))
    duplicates = sorted(incoming & existing)
    if duplicates:
        print(f"重复键，拒绝写入：{duplicates}")
        return 3

    header = [
        f"    # ── 典籍层（{note}）",
        "    # 见证由 scripts/atom_witness.py 实算，同组共命中一并登记。",
        "    # Constraint: 同条目的无条件断语是条件断语的真子集，重叠是必然结果。",
    ]

    block = list(header)
    for rule_id in sorted(witness):
        year, month, day, hour = witness[rule_id]
        block.append(f'    "{rule_id}": ({year}, {month}, {day}, {hour}),')
    text = insert(text, "RULE_WITNESS: dict[str, tuple[int, int, int, int]] = {", "\n".join(block))

    block = list(header)
    for rule_id in sorted(overlap):
        others = overlap[rule_id]
        if not others:
            continue
        inner = "".join(f'\n        "{o}",' for o in others)
        block.append(f'    "{rule_id}": frozenset({{{inner}\n    }}),')
    text = insert(text, "WITNESS_ALSO_MATCHES: dict[str, frozenset[str]] = {", "\n".join(block))

    TEST_FILE.write_text(text, encoding="utf-8")
    print(f"插入见证 {len(witness)} 条，重叠 {sum(1 for v in overlap.values() if v)} 条")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="典籍原子的见证盘工具")
    sub = parser.add_subparsers(dest="command", required=True)

    finder = sub.add_parser("find", help="为新规则找见证命盘")
    finder.add_argument("needle", help="rule id 的子串")
    finder.add_argument("--steps", type=int, default=60)
    finder.add_argument("--out", type=Path, default=Path("/tmp/atom_witness.json"))
    finder.add_argument("--chapter", default=None, help="URN 章节键，跨章节 needle 会误命中时必填")

    applier = sub.add_parser("apply", help="把结果写进测试表")
    applier.add_argument("path", type=Path)
    applier.add_argument("--note", default="卷八")

    args = parser.parse_args()
    if args.command == "find":
        return find(args.needle, args.steps, args.out, args.chapter)
    return apply(args.path, args.note)


if __name__ == "__main__":
    raise SystemExit(main())

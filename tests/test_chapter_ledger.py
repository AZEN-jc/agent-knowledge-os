"""卷八录入账本的守卫：60 节的状态必须能从一处读出来，且不能自相矛盾。

Why: 每录一节，状态就散在底本切分、chapters.json、原子文件 coverage 与见证表
四处。漏登一节不会报错，只是那一节永远停在「待录」而没人发现。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from chapter_ledger import build_ledger, markdown, problems  # noqa: E402

CHAPTERS_FILE = REPO / "corpus/canonical/bazi_sanmingtonghui/chapters.json"
ATOMS_DIR = REPO / "corpus/canonical/bazi_sanmingtonghui/atoms"


def test_the_ledger_covers_all_sixty_sections():
    ledger = build_ledger()

    assert ledger["total_sections"] == 60
    assert ledger["total_entries"] == 360
    assert ledger["recorded_sections"] + ledger["pending_sections"] == 60


def test_recorded_sections_match_the_files_and_the_chapter_registry():
    ledger = build_ledger()
    recorded = [row for row in ledger["rows"] if row["status"] == "recorded"]
    chapters = json.loads(CHAPTERS_FILE.read_text(encoding="utf-8"))["chapters"]

    assert len(recorded) == len(list(ATOMS_DIR.glob("*.json")))
    assert {row["chapter_key"] for row in recorded} == set(chapters)
    assert ledger["total_atoms"] == sum(len(json.loads(
        (ATOMS_DIR / row["file"]).read_text(encoding="utf-8")
    )["atoms"]) for row in recorded)


def test_the_ledger_is_internally_consistent():
    assert problems(build_ledger()) == []


def test_a_registered_chapter_without_atoms_is_caught():
    """守卫不空转：登记了章节却把状态写成待录，必须报出来。"""
    ledger = build_ledger()
    first = next(row for row in ledger["rows"] if row["status"] == "recorded")
    first["status"] = "pending"

    assert any("登记了章节却没有原子文件" in issue for issue in problems(ledger))


def test_a_drifted_atom_count_is_caught():
    ledger = build_ledger()
    first = next(row for row in ledger["rows"] if row["status"] == "recorded")
    first["declared"] += 1

    assert any("声明" in issue for issue in problems(ledger))


def test_the_markdown_table_has_one_row_per_section():
    table = markdown(build_ledger()).splitlines()

    assert sum(1 for line in table if (line.startswith("| ") and "時斷" in line) or
               (line.startswith("| ") and "时断" in line)) == 60

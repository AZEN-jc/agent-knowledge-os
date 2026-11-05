"""原子文件的结构不变量。

Why: 原子是手工录入的 JSON，加载器只读语法，不读计数与唯一性。
声明数写错、ID 撞车、章节漏登记都能静默通过加载，直到见证测试才炸。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge.facts import FACT_SCHEMA

ATOMS_DIR = (
    Path(__file__).resolve().parents[1]
    / "corpus"
    / "canonical"
    / "bazi_sanmingtonghui"
    / "atoms"
)
CHAPTERS_FILE = ATOMS_DIR.parent / "chapters.json"


def _atom_files() -> list[Path]:
    return sorted(ATOMS_DIR.glob("*.json"))


def _payloads() -> list[tuple[Path, dict]]:
    return [
        (path, json.loads(path.read_text(encoding="utf-8")))
        for path in _atom_files()
    ]


def _chapter_of(urn: str) -> str:
    tail = urn.rsplit(":", 1)[-1]
    parts = tail.split(".")
    return ".".join(parts[:2])


def test_one_atom_file_per_registered_chapter():
    registered = json.loads(CHAPTERS_FILE.read_text(encoding="utf-8"))["chapters"]
    files = _atom_files()
    assert len(files) == len(registered), (
        f"原子文件 {len(files)} 份，已登记章节 {len(registered)} 个。"
        "每录一节必须同时落一份原子文件与一条章节登记。"
    )


@pytest.mark.parametrize("path,payload", _payloads(), ids=lambda v: getattr(v, "name", ""))
def test_coverage_count_matches_atoms_array(path: Path, payload: dict):
    assert payload["coverage"]["atoms"] == len(payload["atoms"]), (
        f"{path.name} 声明 {payload['coverage']['atoms']} 条，实际 {len(payload['atoms'])} 条"
    )


def test_rule_ids_and_urns_are_globally_unique():
    seen_ids: dict[str, str] = {}
    seen_urns: dict[str, str] = {}
    for path, payload in _payloads():
        for atom in payload["atoms"]:
            for label, key, table in (
                ("rule_id", "rule_id", seen_ids),
                ("urn", "urn", seen_urns),
            ):
                value = atom[key]
                assert value not in table, (
                    f"{path.name} 的 {label}={value} 与 {table[value]} 重复"
                )
                table[value] = path.name


def test_every_atom_chapter_is_registered():
    registered = set(
        json.loads(CHAPTERS_FILE.read_text(encoding="utf-8"))["chapters"]
    )
    missing = sorted(
        {
            _chapter_of(atom["urn"])
            for _, payload in _payloads()
            for atom in payload["atoms"]
        }
        - registered
    )
    assert not missing, f"章节未登记进 chapters.json：{missing}"


def test_every_condition_key_is_in_fact_schema():
    unknown = sorted(
        {
            key
            for _, payload in _payloads()
            for atom in payload["atoms"]
            for key in atom["condition"]
            if key not in FACT_SCHEMA
        }
    )
    assert not unknown, f"条件键不在 FACT_SCHEMA：{unknown}"

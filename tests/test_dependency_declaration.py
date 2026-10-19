"""依赖声明的一致性：清单不漂移，未使用的依赖不悄悄增长。

**这个文件守两件事。**

1. ``requirements.txt`` 与 ``pyproject.toml`` 的 ``[project.dependencies]``
   必须逐项一致。两份清单各写一遍就会漂移 —— 这是依赖文件最常见的腐烂方式，
   而漂移的症状是「按文档装完跑不起来」，且往往隔几周才被发现。

2. **声明了却没有任何文件 import 的依赖，必须登记在册。**
   Phase 2.4 实测发现 ``everos`` / ``python-dotenv`` / ``rich`` 三条属于此类：
   全仓（含 tests/）AST 扫过，零 import。它们不在本文件的删除清单里 ——
   删依赖是破坏性变更，要老板确认；但**必须写明**，否则「装了但没用」
   这件事没有任何测试会发现，清单会越积越长。

**为什么不顺手删掉那三个。** 任务书的硬性约束含「不删除 CreatorOS」。
这三个包可能服务于尚未接线的 CreatorOS 功能（``everos`` 从名字看就是），
删之前需要确认。登记 + 等确认，比猜着删安全。

**2026-10-18 更新**：老板确认删除，三个包已从两份清单移除，本表现在为空。
机制保留 —— 以后再有「声明了却没人 import」的依赖，仍会被
:func:`test_every_declared_dependency_is_either_used_or_registered` 抓住。
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: 声明了但全仓零 import 的依赖。每一条都要写理由 —— 没有理由的条目
#: 应当被删掉，而不是躺在这里。
#:
#: 2026-10-18：曾有三个（everos / python-dotenv / rich），老板确认后删除。
#: 现在是空表，但**机制保留**：空表意味着「当前没有未登记的多余依赖」。
DECLARED_BUT_UNUSED: dict[str, str] = {}


def _parse_requirement_lines(text: str) -> dict[str, str]:
    """把 requirements 格式解析成 ``{包名: 版本约束}``。"""
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-r"):
            continue
        match = re.match(
            r"^([A-Za-z0-9_.\-]+)\s*(?:[=<>!~]=?\s*([0-9][0-9A-Za-z.\-]*))?", line
        )
        if match:
            name = _canonical(match.group(1))
            parsed[name] = match.group(2) or ""
    return parsed


#: 分发名与 import 名不一致的包。PyPI 用连字符、Python 模块用下划线，
#: 还有 ``python-dotenv`` 这种分发名与模块名完全不同的情况。
#: 不做这张映射，「已声明但没人 import」会报出一堆假阳性。
MODULE_TO_DISTRIBUTION: dict[str, str] = {
    "dotenv": "python-dotenv",
    "lunar_python": "lunar-python",
    "arbiter_lite": "arbiter-lite",
}


def _canonical(name: str) -> str:
    """把分发名或模块名归一到同一种形式：小写 + 连字符。"""
    return name.lower().replace("_", "-")


def _runtime_imports() -> set[str]:
    """全仓（含 tests）实际 import 的第三方**分发名**（归一化后）。"""
    third_party = {
        "sxtwl", "lunar_python", "fastapi", "uvicorn", "pydantic", "pytest",
        "rich", "requests", "dotenv", "everos", "arbiter_lite", "ruff", "mypy",
    }
    found: set[str] = set()
    for path in sorted(REPO.rglob("*.py")):
        relative = str(path.relative_to(REPO))
        if "__pycache__" in relative or ".venv" in relative:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module.split(".")[0])
    return {_canonical(MODULE_TO_DISTRIBUTION.get(m, m)) for m in found & third_party}


# ── 两份清单不漂移 ─────────────────────────────────────────────────────


def test_requirements_and_pyproject_declare_the_same_dependencies():
    """两份运行时依赖清单必须逐项一致，含版本约束。"""
    requirements = _parse_requirement_lines(
        (REPO / "requirements.txt").read_text(encoding="utf-8")
    )
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    declared = _parse_requirement_lines(
        "\n".join(project["project"]["dependencies"])
    )

    only_in_requirements = sorted(set(requirements) - set(declared))
    only_in_pyproject = sorted(set(declared) - set(requirements))
    assert not only_in_requirements, f"只在 requirements.txt：{only_in_requirements}"
    assert not only_in_pyproject, f"只在 pyproject.toml：{only_in_pyproject}"

    mismatched = {
        name: (requirements[name], declared[name])
        for name in set(requirements) & set(declared)
        if requirements[name] != declared[name]
    }
    assert not mismatched, f"版本约束不一致：{mismatched}"


def test_dev_dependencies_are_declared_somewhere():
    """ruff 与 mypy 必须出现在某个依赖清单里。

    这是审计报告 §5 的 R4：两个工具在 pyproject 里配了，却没有任何地方声明
    为依赖，于是新克隆后 ``ruff check .`` 直接 command not found ——
    「ruff 干净」「mypy 有处置方案」两条验收无法从仓库复现。
    """
    dev = _parse_requirement_lines(
        (REPO / "requirements-dev.txt").read_text(encoding="utf-8")
    )
    for tool in ("ruff", "mypy"):
        assert tool in dev, f"{tool} 未在 requirements-dev.txt 中声明"
        assert dev[tool], f"{tool} 未钉版本 —— 不钉则 CI 与本地可能不同版"


def test_test_scaffolding_dependencies_are_declared():
    """测试脚手架 import 的包也必须在 dev 清单里。

    **这条是 Phase 3.1 补的，起因是一次真实的翻车**：重建隔离环境后
    ``pytest`` 在 collection 阶段直接报 4 个错误 —— ``fastapi.testclient``
    要 httpx，而它没被任何清单声明。早期环境里 httpx 是被别的包顺带装进来
    的，于是「新克隆能不能跑测试」这件事一直没人真正验过。

    与 R4（ruff/mypy 配了却没声明）是同一类缺陷，只是更隐蔽：
    ``test_every_declared_dependency_is_either_used_or_registered`` 查的是
    **多声明**，这条查的是**漏声明**，方向相反。

    这里的清单不是从 AST 自动推的 —— 测试脚手架用的是间接 import
    （``from fastapi.testclient import TestClient`` 里看不出 httpx），
    自动推会漏。所以显式列出「测试实际需要、但不是被直接 import 的包」。
    """
    dev = _parse_requirement_lines(
        (REPO / "requirements-dev.txt").read_text(encoding="utf-8")
    )
    #: 间接依赖，但缺了整个测试套件跑不起来。
    required_scaffolding = {
        "httpx": "fastapi.testclient / starlette.testclient 需要它",
    }
    missing = [
        f"{name}（{why}）"
        for name, why in required_scaffolding.items()
        if name not in dev
    ]
    assert not missing, (
        "以下测试脚手架依赖未在 requirements-dev.txt 中声明：\n  "
        + "\n  ".join(missing)
    )


def test_dev_file_includes_the_runtime_list():
    """dev 清单必须 ``-r requirements.txt``，而不是重抄一份。

    重抄就有两份真相，改一处忘另一处正是这类文件最常见的漂移方式。
    """
    text = (REPO / "requirements-dev.txt").read_text(encoding="utf-8")
    assert re.search(r"^-r\s+requirements\.txt\s*$", text, re.M), (
        "requirements-dev.txt 应通过 `-r requirements.txt` 引用运行时依赖"
    )


# ── 未使用的依赖必须登记 ──────────────────────────────────────────────


def test_every_declared_dependency_is_either_used_or_registered():
    """声明 = 被 import，或登记在 :data:`DECLARED_BUT_UNUSED` 里。

    这条测试的价值在**防止静默增长**：没有任何约束时，「加一个依赖但没人
    import」是不会被发现的，清单会越积越长，而每一条都是新克隆时的一次下载
    和一个潜在的安全面。
    """
    requirements = _parse_requirement_lines(
        (REPO / "requirements.txt").read_text(encoding="utf-8")
    )
    imported = _runtime_imports()

    unregistered = sorted(
        name for name in requirements
        if name not in imported and name not in DECLARED_BUT_UNUSED
    )
    assert not unregistered, (
        "以下依赖已声明但全仓无人 import，也未登记理由：\n  "
        + "\n  ".join(unregistered)
        + "\n请把它们加进 DECLARED_BUT_UNUSED 并写明原因，或从清单中移除。"
    )


def test_the_registered_unused_list_has_not_gone_stale():
    """登记表不能唱反调：登记为「未使用」的包，其实已经被用上了。

    有这条在，DECLARED_BUT_UNUSED 就不是一张写完就忘的清单 ——
    谁给 CreatorOS 接上了 everos，这条会提醒他把登记删掉。
    """
    imported = _runtime_imports()
    stale = sorted(name for name in DECLARED_BUT_UNUSED if name in imported)
    assert not stale, f"以下包已登记为未使用，但实际已被 import：{stale}"


def test_every_registered_entry_explains_itself():
    """登记条目必须带理由。没有理由的条目应当被删掉，不是躺平。"""
    for name, reason in DECLARED_BUT_UNUSED.items():
        assert reason and reason.strip(), f"{name} 的登记缺少理由"

"""agents 包的惰性导入：MingLi 启动不该连带加载 CreatorOS。

**为什么这必须用子进程测。** 断言的是「``sys.modules`` 里没有
``agents.planner``」。而 ``sys.modules`` 是**全局状态** —— 测试进程里任何
一个先跑的用例只要 import 过 CreatorOS 的东西，这条断言就恒真或恒假，
与 ``__init__.py`` 无关。所以核心断言全部在干净解释器里跑。

**这条测试守的是什么。** 审计发现仅 ``import agents.mingli`` 就连带加载 37 个
非 MingLi 模块，而两套系统在文件层早已零耦合。改成惰性导入消除了这层耦合。
但它是**加载时机**这种看不见的东西：任何人哪天在 ``__init__.py`` 里加一行
普通 import，MingLi 的启动依赖就会悄悄变重，而**不会有任何现有测试变红** ——
现有 CreatorOS 测试全靠 ``from agents import X``，两种加载方式下都是绿的。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: CreatorOS 侧的模块，MingLi 加载路径上一条都不该出现。
CREATOROS_MARKERS = (
    "agents.analytics",
    "agents.base_agent",
    "agents.briefing",
    "agents.coder",
    "agents.content",
    "agents.daily",
    "agents.feedback_loop",
    "agents.planner",
    "agents.researcher",
    "agents.reviewer",
    "agents.strategist",
    "agents.x_workflow",
    "runtime.orchestrator",
    "runtime.analytics_collector",
    "runtime.aihot_bridge",
    "workflows",
)


def run_snippet(snippet: str) -> subprocess.CompletedProcess[str]:
    """在干净解释器里跑一段代码，返回其输出与退出码。"""
    return subprocess.run(
        [sys.executable, "-c", snippet],
        cwd="/tmp",  # 仓库根作 cwd 会被沙箱 SIGTERM（已知坑）
        capture_output=True,
        text=True,
        timeout=300,
        env={"PYTHONPATH": str(REPO), "PATH": "/usr/bin:/bin", "HOME": "/tmp"},
    )


def _probe(import_statement: str) -> set[str]:
    """在干净解释器里执行一条 import，返回随后 sys.modules 里的模块名。"""
    snippet = (
        "import sys\n"
        f"{import_statement}\n"
        "print('\\n'.join(sorted(sys.modules)))\n"
    )
    completed = run_snippet(snippet)
    assert completed.returncode == 0, (
        f"子进程失败：{import_statement}\n{completed.stdout}\n{completed.stderr}"
    )
    return set(completed.stdout.splitlines())


# ── 核心断言：MingLi 的加载路径上没有 CreatorOS ────────────────────────


def test_importing_mingli_does_not_pull_in_creatoros():
    """只碰 MingLi 时，CreatorOS 一条都不该被加载。"""
    loaded = _probe("import agents.mingli")

    leaked = [name for name in CREATOROS_MARKERS
              if any(mod == name or mod.startswith(name + ".") for mod in loaded)]
    assert leaked == [], f"import agents.mingli 连带加载了 CreatorOS：{leaked}"


def test_importing_the_birth_engine_does_not_pull_in_creatoros():
    """更深一层：连 engines 一起导入也不该带出 CreatorOS。"""
    loaded = _probe("import engines.bazi, agents.mingli")

    leaked = [name for name in CREATOROS_MARKERS
              if any(mod == name or mod.startswith(name + ".") for mod in loaded)]
    assert leaked == [], f"engines 导入连带加载了 CreatorOS：{leaked}"


# ── 兼容性：惰性不能把现有用法弄坏 ─────────────────────────────────────


def test_exported_names_still_resolve_to_the_right_classes():
    """``from agents import X`` 必须拿到真正的类，不是 None 或代理。

    这条守的是惰性化的**回归风险**：``__getattr__`` 写错时照样能 import，
    只是拿到的不是原来的东西。``__name__`` 比 ``is not None`` 严格得多。
    """
    snippet = (
        "from agents import (AnalyticsAgent, Briefing, CoderAgent, ContentAgent,\n"
        "                   DailyPipeline, FeedbackLoop, PlannerAgent, ResearcherAgent,\n"
        "                   ReviewerAgent, StrategyAgent, XWorkflow)\n"
        "for cls in (AnalyticsAgent, Briefing, CoderAgent, ContentAgent, DailyPipeline,\n"
        "            FeedbackLoop, PlannerAgent, ResearcherAgent, ReviewerAgent,\n"
        "            StrategyAgent, XWorkflow):\n"
        "    assert isinstance(cls, type), f'{cls!r} 不是类'\n"
        "print('ok')\n"
    )
    completed = run_snippet(snippet)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "ok" in completed.stdout


def test_each_export_lands_in_the_module_it_belongs_to():
    """逐个核对导出名与来源模块的对应关系。

    上面那条只证明「是个类」；这一条证明「是**对的**那个类」——
    导出表键值写串时，两条都会过，但调用的 agent 是另一个。
    """
    expected = {
        "AnalyticsAgent": "agents.analytics",
        "Briefing": "agents.briefing",
        "CoderAgent": "agents.coder",
        "ContentAgent": "agents.content",
        "DailyPipeline": "agents.daily",
        "FeedbackLoop": "agents.feedback_loop",
        "PlannerAgent": "agents.planner",
        "ResearcherAgent": "agents.researcher",
        "ReviewerAgent": "agents.reviewer",
        "StrategyAgent": "agents.strategist",
        "XWorkflow": "agents.x_workflow",
    }
    lines = "\n".join(
        f"assert {name}.__module__ == '{module}', {name}.__module__"
        for name, module in expected.items()
    )
    snippet = (
        "from agents import (" + ", ".join(expected) + ")\n" + lines + "\nprint('ok')\n"
    )
    completed = run_snippet(snippet)

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_submodule_import_still_works():
    """``from agents import prompt`` 这类子模块导入不能被打断。

    惰性化之前它靠 ``__init__`` 里没有 prompt 导入、由导入系统回退完成；
    惰性化之后 ``__getattr__`` 必须先抛 AttributeError 才会走到那条回退路径。
    这条测试就是钉住那个 AttributeError —— 改成抛 KeyError 的话，
    子模块导入会被无声挡掉。
    """
    completed = run_snippet(
        "from agents import prompt\n"
        "assert hasattr(prompt, '__name__')\n"
        "print('ok')\n"
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "ok" in completed.stdout


def test_an_unknown_name_raises_attribute_error_not_key_error():
    """拿不存在的名字必须报 AttributeError。

    这是上面那条子模块导入能成立的前提，也符合 Python 对模块属性的约定。
    """
    completed = run_snippet(
        "import agents\n"
        "try:\n"
        "    agents.NoSuchAgent\n"
        "except AttributeError:\n"
        "    print('ok')\n"
        "except Exception as exc:\n"
        "    print('WRONG', type(exc).__name__)\n"
    )

    assert "ok" in completed.stdout, completed.stdout + completed.stderr


def test_requesting_an_export_actually_loads_it():
    """惰性的另一面：要了就得真给，不能永远不加载。

    只测「不加载」会漏掉一种退化解耦 —— 把 ``__getattr__`` 写成永远抛错，
    CreatorOS 是没了，但 CreatorOS 自己的测试会全挂。所以这边补上。
    """
    loaded = _probe("from agents import PlannerAgent")

    assert "agents.planner" in loaded, "请求 PlannerAgent 后 agents.planner 应被加载"


def test_the_export_table_matches_dunder_all():
    """``__all__`` 与导出表必须一致，否则 ``from agents import *`` 会漏名字。"""
    from agents import _EXPORTS, __all__

    assert set(__all__) == set(_EXPORTS)

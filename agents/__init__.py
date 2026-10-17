"""Agent 模块集合。

**为什么从急切导入改成惰性。** 这个文件原本在导入时就拉齐全部 11 个 CreatorOS
agent。后果不只是慢：Python 导入 ``agents.mingli`` 时会**先执行本文件**，
于是 MingLi 的服务/测试只要碰到任一 agent，就连带加载 37 个非 MingLi 模块
（``agents.planner`` / ``runtime.orchestrator`` / ``workflows.*`` …，实测）。

两套系统在文件层早已零耦合（AST 扫全仓，双向 0 条 import），这层急切导入是
仅剩的耦合点，也是 ``mingli-split`` 分支靠删文件拆包的原因 —— 但删文件违反
本阶段的硬性约束，所以这里只改**加载时机**，一个文件都不动。

**兼容性保证**：``from agents import CoderAgent`` 照旧可用（触发下面的
``__getattr__`` 时按需加载）；``from agents import prompt`` 这类子模块导入
也不受影响 —— PEP 562 规定 ``__getattr__`` 抛 AttributeError 后，导入系统
会回退去导入 ``agents.prompt``。
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # 仅供类型检查器与 IDE：运行时不产生导入，否则就白改了。
    # 有这一段，`from agents import CoderAgent` 在调用方仍然是 CoderAgent 类型
    # 而不是 Any。
    #
    # `X as X` 是 PEP 484 标记「这是刻意重导出」的写法。不用它，ruff 会报
    # F401 —— 因为 __all__ 由下面的 _EXPORTS 在运行时算出，静态分析看不出
    # 这些名字是要被 re-export 的。
    from agents.analytics import AnalyticsAgent as AnalyticsAgent
    from agents.briefing import Briefing as Briefing
    from agents.coder import CoderAgent as CoderAgent
    from agents.content import ContentAgent as ContentAgent
    from agents.daily import DailyPipeline as DailyPipeline
    from agents.feedback_loop import FeedbackLoop as FeedbackLoop
    from agents.planner import PlannerAgent as PlannerAgent
    from agents.researcher import ResearcherAgent as ResearcherAgent
    from agents.reviewer import ReviewerAgent as ReviewerAgent
    from agents.strategist import StrategyAgent as StrategyAgent
    from agents.x_workflow import XWorkflow as XWorkflow

#: 导出名 → 所在模块。键的顺序即 ``__all__`` 的顺序，与改动前一致。
_EXPORTS: dict[str, str] = {
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

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    """按需加载导出名。

    必须抛 AttributeError 而不是 KeyError —— 前者会让导入系统继续尝试
    ``agents.<name>`` 子模块导入（``from agents import prompt`` 靠这个），
    后者会直接把子模块导入也挡掉。
    """
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(module_name), name)


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(globals()))

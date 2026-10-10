"""典籍层规则的待录入清单（backlog），以及它们卡在哪里。

这里**故意不放任何 ``Rule`` 对象**。原因很直接：规则模型要求 condition 和
conclusion，而写这两样就等于把某句命理断语写进了系统。在拿到可核验的底本
之前，这样做就是在编造典籍 —— MINGLI_PLAN.md 第一条「不做什么」明确禁止。

所以这个模块只记录「要录什么、按什么顺序、卡在哪一步」，让阻塞点变成
一份可执行的清单，而不是一句「等以后补」。等到 :class:`Citation` 能填满
``book / edition / original_text / url`` 四个字段，对应条目才允许写成
``source_tier=CLASSICAL`` 且 ``review_status=ACTIVE`` 的规则。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class BacklogStatus(StrEnum):
    BLOCKED_SOURCE = "BLOCKED_SOURCE"
    """缺可核验的底本，无法录入。"""

    BLOCKED_LEGAL = "BLOCKED_LEGAL"
    """无公有领域文本可引（口传系统或现代著作权作品）。"""

    READY = "READY"
    """底本已确认，可以开始逐条校核录入。"""


@dataclass(frozen=True)
class BacklogEntry:
    """一条待录入的典籍规则来源。"""

    id: str
    book: str
    priority: int
    topic: str
    status: BacklogStatus
    blocker: str
    needed_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "book": self.book,
            "priority": self.priority,
            "topic": self.topic,
            "status": str(self.status),
            "blocker": self.blocker,
            "needed_action": self.needed_action,
        }


CLASSICAL_BACKLOG: tuple[BacklogEntry, ...] = (
    BacklogEntry(
        id="BACKLOG_DTS",
        book="《滴天髓》",
        priority=1,
        topic="用神、通关、调候",
        status=BacklogStatus.BLOCKED_SOURCE,
        blocker="尚未确定采用哪一个底本。同一部书在通行本、任铁樵注本与各家辑本之间条文有出入，"
                "只写书名无法复核；且当前环境无法访问维基文库等公版文本站点，原文无从逐字核对。",
        needed_action="由项目所有者指定一个可获取、可引用页码或章节的公版底本（注明版本与出处），"
                      "再按卷章逐条录入，并在 Citation.url 填入可打开的地址。",
    ),
    BacklogEntry(
        id="BACKLOG_YHZP",
        book="《渊海子平》",
        priority=2,
        topic="子平体系基础、十神与格局",
        status=BacklogStatus.BLOCKED_SOURCE,
        blocker="同上：底本未定。另需确认是取明刊本还是后世整理本，两者的篇目编排不同。",
        needed_action="确认底本后录入；结构层已覆盖的十神定义不必重复录入，只补断语部分。",
    ),
    BacklogEntry(
        id="BACKLOG_ZPZQ",
        book="《子平真诠》",
        priority=3,
        topic="格局理论与取用",
        status=BacklogStatus.BLOCKED_SOURCE,
        blocker="同上：底本未定。此书是「本气定格法」与「透干定格法」分歧的关键文献，"
                "底本选择会直接决定两种定格法的取舍表述。",
        needed_action="确认底本；同时用于给 STRUCT_PATTERN_* 与 STRUCT_PATTERN_EXT_* 的"
                      "流派归属定性（当前两者都挂在公共结构层，未做流派归属）。",
    ),
    BacklogEntry(
        id="BACKLOG_SMTH",
        book="《三命通会》",
        priority=4,
        topic="神煞体系",
        status=BacklogStatus.BLOCKED_SOURCE,
        blocker="同上：底本未定。神煞起例在流传中存在多条口诀（如天乙贵人一项即有"
                "「甲戊庚牛羊」与「甲戊兼牛羊」等差异），必须按底本逐字确定，不能凭印象取其一。",
        needed_action="确认底本后按起例原文录入；同时需要新增神煞事实计算（当前事实词表不含神煞）。",
    ),
    BacklogEntry(
        id="BACKLOG_QTBJ",
        book="《穷通宝鉴》",
        priority=5,
        topic="调候用神",
        status=BacklogStatus.BLOCKED_SOURCE,
        blocker="同上：底本未定。调候表按日干与月令逐格给出，条目多且互相牵制，"
                "底本错一处会连带错一片。",
        needed_action="确认底本后整表录入，并补一组覆盖十二月的校核用例。",
    ),
    BacklogEntry(
        id="BACKLOG_MANGPAI",
        book="盲派口诀",
        priority=6,
        topic="做功理论",
        status=BacklogStatus.BLOCKED_LEGAL,
        blocker="盲派体系以口传口诀为主，没有公有领域文本；现行流传的整理本多为现代人的"
                "著作权作品，直接录入存在侵权风险，且不同师承口诀不一致，无法确定「正确版本」。",
        needed_action="需要项目所有者明确：要么放弃盲派，要么取得授权文本并指定师承口径。"
                      "在此之前，流派注册表中盲派条目只作为「已知分歧方」存在，不挂任何规则。",
    ),
    BacklogEntry(
        id="BACKLOG_XIANGFA",
        book="象法新派著作",
        priority=7,
        topic="象法取事",
        status=BacklogStatus.BLOCKED_LEGAL,
        blocker="现代流派，代表著作均在著作权保护期内，不能直接录入原文。",
        needed_action="如需支持，只能做「方法论抽象」而非原文录入，且必须事先明确这是转述而非引用，"
                      "并在结论中标注来源性质。",
    ),
)


def backlog_by_status(status: BacklogStatus) -> tuple[BacklogEntry, ...]:
    return tuple(entry for entry in CLASSICAL_BACKLOG if entry.status is status)


def blocked_entries() -> tuple[BacklogEntry, ...]:
    """全部被阻塞的条目；当前等于全集。"""
    return tuple(entry for entry in CLASSICAL_BACKLOG if entry.status is not BacklogStatus.READY)


def next_action() -> BacklogEntry:
    """按优先级返回下一步该处理的那一条。"""
    return min(CLASSICAL_BACKLOG, key=lambda entry: entry.priority)

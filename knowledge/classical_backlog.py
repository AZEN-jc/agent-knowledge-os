"""典籍层规则的待录入清单（backlog），以及它们卡在哪里。

这里**故意不放任何 ``Rule`` 对象**。原因很直接：规则模型要求 condition 和
conclusion，而写这两样就等于把某句命理断语写进了系统。在拿到可核验的底本
之前，这样做就是在编造典籍 —— MINGLI_PLAN.md 第一条「不做什么」明确禁止。

所以这个模块只记录「要录什么、按什么顺序、卡在哪一步」，让阻塞点变成
一份可执行的清单，而不是一句「等以后补」。

底本裁定状态（Phase 5 更新）
--------------------------

这张表最初写于 Phase 2，当时的阻塞语是「当前环境无法访问维基文库等公版
文本站点」。**那句话现在不成立了** —— 维基文库可达，而且已经用
``scripts/fetch_corpus.py`` 把《三命通會》卷八固化进仓库（见
``corpus/canonical/manifest.json``）。所以阻塞语改成了各书**真正的**阻塞点：
底本未裁定、或该站根本未收录。分三类：

- **已裁定** —— 《三命通會》：底本取欽定四庫全書本（revid 761697），
  已录入「六甲日甲子時斷」一段共 6 条原子。神煞部分仍未录，但底本不再是障碍。
- **站内有，但未裁定** —— 《滴天髓》（``滴天髓/01``–``/20``，revid 844410）、
  《淵海子平》（整页长文，revid 2593607，2025-08-24 仍有修订）。两者都是
  同一部书有多个本子，只写书名无法复核。
- **站内未收录** —— 《子平真詮》《窮通寶鑑》：维基文库没有这两个标题的页面，
  得另找可核验的公版底本。

**不要把「站内没有」写成「底本未定」** —— 前者要去找源，后者只要做选择，
两者的下一步动作完全不同。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

WIKISOURCE = "zh.wikisource.org"
"""当前唯一可达的公版全文站点。ctext.org 返回拦截页且许可证禁止非商业以外的使用，
国图 read.nlc.cn 在本机超时 —— 两者都不能作为底本源（见 PHASE5_REPORT.md）。"""


class BacklogStatus(StrEnum):
    BLOCKED_SOURCE = "BLOCKED_SOURCE"
    """缺可核验的底本，无法录入。"""

    BLOCKED_LEGAL = "BLOCKED_LEGAL"
    """无公有领域文本可引（口传系统或现代著作权作品）。"""

    BLOCKED_SCHEMA = "BLOCKED_SCHEMA"
    """底本已裁定，但**当前管道表达不了这条规则的条件**。

    和「缺底本」是两回事：前者要去找源，这个要改事实词表或规则模型。
    混成一个状态，就会把「底本已定」读成「马上能录」。
    """

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
        blocker="维基文库有全文（滴天髓/01–/20，revid 844410），但**采用哪个本子尚未裁定**。"
                "通行本、任铁樵注本与各家辑本之间条文有出入，只写书名无法复核。",
        needed_action="由项目所有者指定一个本子（注明版本与出处），再按卷章逐条录入。"
                      "裁定后即可照《三命通會》的路子走：加一个 Source、固化、立原子。",
    ),
    BacklogEntry(
        id="BACKLOG_YHZP",
        book="《渊海子平》",
        priority=2,
        topic="子平体系基础、十神与格局",
        status=BacklogStatus.BLOCKED_SOURCE,
        blocker="维基文库有主页面（revid 2593607，2025-08-24 仍有修订），"
                "但是**整页长文、没有分卷子页**，也没有版本声明 —— 与《三命通會》转录本同病。",
        needed_action="先找有分卷结构、有版本声明的底本；若只有这一份，就要先裁定卷次划分，"
                      "否则 URN 的卷号段无处落地。结构层已覆盖的十神定义不必重复录入，只补断语。",
    ),
    BacklogEntry(
        id="BACKLOG_ZPZQ",
        book="《子平真诠》",
        priority=3,
        topic="格局理论与取用",
        status=BacklogStatus.BLOCKED_SOURCE,
        blocker="**维基文库未收录此书名下的任何页面**（检索命中的是《地理眞詮》《仙學真詮》等同名异书）。"
                "此书是「本气定格法」与「透干定格法」分歧的关键文献，"
                "底本选择会直接决定两种定格法的取舍表述。",
        needed_action="另找可核验的公版底本（扫描件或权威排印本的公有领域部分），"
                      "确认后再录入；同时用于给 STRUCT_PATTERN_* 与 STRUCT_PATTERN_EXT_* 定性"
                      "（当前两者都挂在公共结构层，未做流派归属）。",
    ),
    BacklogEntry(
        id="BACKLOG_SMTH",
        book="《三命通会》",
        priority=4,
        topic="神煞体系",
        status=BacklogStatus.BLOCKED_SCHEMA,
        blocker="底本已裁定（欽定四庫全書本，revid 761697），卡在**事实词表不含神煞** —— "
                "神煞规则的 condition 无处落地。神煞起例在流传中另有多条口诀"
                "（如天乙贵人一项即有「甲戊庚牛羊」与「甲戊兼牛羊」等差异），"
                "录入时须按底本逐字确定，不能凭印象取其一。",
        needed_action="先给事实词表加神煞计算（含起例的流派归属），再按底本录入起例原文。"
                      "日时断一段已走通整条管道（corpus → URN → 原子 → 规则），可照此办理。",
    ),
    BacklogEntry(
        id="BACKLOG_QTBJ",
        book="《穷通宝鉴》",
        priority=5,
        topic="调候用神",
        status=BacklogStatus.BLOCKED_SOURCE,
        blocker="**维基文库未收录此书名下的任何页面**（检索命中的是《東醫寶鑒》《司牧寶鑑》等）。"
                "调候表按日干与月令逐格给出，条目多且互相牵制，底本错一处会连带错一片。",
        needed_action="另找可核验的公版底本，确认后整表录入，并补一组覆盖十二月的校核用例。",
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
    """全部被阻塞的条目。"""
    return tuple(entry for entry in CLASSICAL_BACKLOG if entry.status is not BacklogStatus.READY)


def next_action() -> BacklogEntry:
    """按优先级返回下一步该处理的那一条。"""
    return min(CLASSICAL_BACKLOG, key=lambda entry: entry.priority)

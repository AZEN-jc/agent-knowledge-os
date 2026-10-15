"""分析主题与「这个主题到底有没有规则可用」。

修掉一个真问题：原实现的 ``build_evidence(chart, registry, topic="事业")``
把**全部**结构规则都标成「事业」主题输出。规则匹配根本没按主题过滤，topic
只是一个贴上去的标签。于是用户会看到一份题为「事业」、内容却是十神与地支
结构的报告 —— 这正是 MINGLI_PLAN.md 禁止的「混淆推测和事实」。

本模块把主题拆成两层，让覆盖状态可以如实报出来：

- **基础层**（``structure``）：十神、藏干、五行生克、地支关系。所有主题共享，
  它只说明「命盘里有什么」。
- **主题层**（``destiny`` / ``career`` / ``marriage`` / …）：针对该主题的断语规则。
  ``destiny``（命局）自 Phase 5 起有规则：底本是《三命通會》卷八的日时断，
  原文已固化到 ``corpus/`` 并逐条核对。其余主题仍然为空 —— 它们的底本还没定，
  见 :mod:`knowledge.classical_backlog`。

于是 ``build_evidence`` 的语义变成：返回基础层 + 该主题专属层，并如实报告
主题层是否为空。用户看到的不再是「事业分析」，而是「公共结构层证据，该主题
尚无断语规则」。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TopicStatus(StrEnum):
    """某个主题当前有没有可用的规则。"""

    COVERED = "covered"
    """该主题有专属规则命中。"""

    BASE_ONLY = "base_only"
    """只有公共结构层证据，没有该主题的断语规则。"""

    UNKNOWN = "unknown"
    """未登记的主题；仍返回基础层，但主题层必然为空。"""


STRUCTURAL_TOPIC = "structure"
"""基础层主题 ID；所有结构层规则都挂在这个主题上。"""


@dataclass(frozen=True)
class Topic:
    """一个分析主题的元数据。"""

    id: str
    name: str
    description: str
    aliases: tuple[str, ...] = ()
    blocked_by: str = ""

    def matches(self, text: str) -> bool:
        """主题 ID 或任一别名命中即可。

        别名是必要的：用户问的是「事业」，而主题 ID 是 ``career``。
        没有别名，中文提问会全部落进「未登记的主题」。
        """
        return text == self.id or text in self.aliases

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "aliases": list(self.aliases),
            "blocked_by": self.blocked_by,
        }


CLASSICAL_BLOCKER = (
    "该主题的断语规则需要可核验的典籍原文，本主题的底本尚未确认"
    "（见 /api/classics/backlog）。"
)

TOPICS: tuple[Topic, ...] = (
    Topic(
        id=STRUCTURAL_TOPIC,
        name="公共结构层",
        description="十神、藏干、五行生克、地支关系的结构描述；只说明命盘里有什么，不做吉凶判断。",
        aliases=("结构", "structure", "命盘结构"),
    ),
    Topic(
        id="destiny",
        name="命局",
        description=(
            "日时组合与格局成败的综合断语。底本为《三命通會》卷八（欽定四庫全書本，"
            "明 萬民英 撰），当前覆盖「六甲日甲子時斷」一段的 6 个日时组合；"
            "其余日时组合尚未录入。"
        ),
        aliases=("命局", "格局", "命格", "日时断", "destiny"),
    ),
    Topic(
        id="career",
        name="事业",
        description="职业倾向、官杀与财星的结构解读。",
        aliases=("事业", "工作", "职业", "career"),
        blocked_by=CLASSICAL_BLOCKER,
    ),
    Topic(
        id="marriage",
        name="婚姻",
        description="配偶宫、夫妻星的结构解读。",
        aliases=("婚姻", "感情", "婚恋", "marriage"),
        blocked_by=CLASSICAL_BLOCKER,
    ),
    Topic(
        id="health",
        name="健康",
        description="五行偏枯与身体部位的结构对应。",
        aliases=("健康", "身体", "health"),
        blocked_by=CLASSICAL_BLOCKER,
    ),
    Topic(
        id="wealth",
        name="财运",
        description="财星与食伤生财的结构解读。",
        aliases=("财运", "财富", "money", "wealth"),
        blocked_by=CLASSICAL_BLOCKER,
    ),
)


def known_topic_ids() -> frozenset[str]:
    """全部已登记主题的规范 ID。"""
    return frozenset(topic.id for topic in TOPICS)


def is_registered(text: str) -> bool:
    """该主题（按 ID 或别名）是否已登记。"""
    return any(topic.matches(text) for topic in TOPICS)


def resolve(text: str) -> Topic:
    """把主题 ID 或别名解析成 :class:`Topic`。

    未登记的主题不报错，而是返回一个 ``id`` 原样保留的占位条目 —— 调用方
    仍能拿到基础层证据，同时从 ``status`` 知道主题层必然为空。
    """
    for topic in TOPICS:
        if topic.matches(text):
            return topic
    return Topic(
        id=text,
        name=text,
        description="未登记的主题；仅返回公共结构层证据。",
        blocked_by="未登记的主题，没有对应的规则层。",
    )


def status_for(resolved: Topic, domain_match_count: int) -> TopicStatus:
    """由主题层的命中条数判定覆盖状态。

    刻意不接受「主题是否已登记」作为 COVERED 的依据：登记了但一条规则都没录
    的主题（career 等）必须报 ``BASE_ONLY``，否则又会变成「挂个名字就算覆盖」。
    """
    if domain_match_count > 0:
        return TopicStatus.COVERED
    return TopicStatus.BASE_ONLY if resolved.id in known_topic_ids() else TopicStatus.UNKNOWN

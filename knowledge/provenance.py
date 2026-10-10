"""规则来源治理：把「不编造命理规则」写成代码级约束。

项目原则（MINGLI_PLAN.md 一、2.1）要求每个结论都能追溯到可核验的依据。
只靠文档约定守不住这条线 —— 只要有人往规则库里塞一条没有出处的断语，
系统就会把它当成和典籍原文同等权威的东西引用出去。所以这里把约束前移到
构造期：数据模型自己拒绝非法状态。

两个正交的维度：

``SourceTier``  —— 这条规则的依据**凭什么成立**
    - ``structural``：可由命盘结构直接验证。十神、藏干、五行生克、地支关系、
      月令本气，这些由 ``engines.bazi`` 的定义表唯一确定，跑一遍代码就能证伪。
      它可以没有典籍引文，但它的来源必须诚实写成「算法/定义」，不能冒充典籍。
    - ``classical``：典籍断语。它的正确性不来自代码，只来自原文。因此它必须
      指向可核验的原文，否则不许激活。

``ReviewStatus`` —— 这条规则**走到哪一步了**
    ``UNREVIEWED → REVIEWED → ACTIVE``，``ACTIVE`` 可以转 ``DEPRECATED``。

关键守卫在 :meth:`Rule.__post_init__`（见 :mod:`knowledge.rules`）：一条
``classical`` 规则想进入 ``ACTIVE``，必须带齐典籍名、底本、原文摘录和可核验
地址。缺任何一项都直接抛错，而不是留一条「待补」的规则混在生产规则库里。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class SourceTier(StrEnum):
    """规则依据的性质。"""

    STRUCTURAL = "structural"
    """可由命盘结构直接验证（定义表、算法、算术）。"""

    CLASSICAL = "classical"
    """典籍断语，正确性只能由原文支撑。"""


class ReviewStatus(StrEnum):
    """人工校核状态。

    ``UNREVIEWED`` 与 ``REVIEWED`` 都只能用于内部演示和测试；
    只有 ``ACTIVE`` 允许进入面向用户的生产报告。
    """

    UNREVIEWED = "UNREVIEWED"
    REVIEWED = "REVIEWED"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


@dataclass(frozen=True)
class Citation:
    """一条规则的文献出处。

    刻意要求 ``edition``（底本/版本）：同一部典籍不同底本的条文有出入，
    只写书名无法复核。「甲戊庚牛羊」与「甲戊兼牛羊」这类分歧，差别恰恰在
    底本，不在书名。
    """

    book: str
    edition: str
    chapter: str = ""
    original_text: str = ""
    url: str = ""
    retrieved_on: date | None = None

    def __post_init__(self) -> None:
        if not self.book.strip():
            raise ValueError("引文必须标明典籍名。")
        if not self.edition.strip():
            raise ValueError(f"引文《{self.book}》必须标明底本或版本。")

    @property
    def is_verifiable(self) -> bool:
        """可核验 = 有逐字原文，且有能打开的出处地址。

        两个条件都不可省：只有地址没有原文，无法判断引用是否走样；
        只有原文没有地址，别人无从复核是不是转抄自二手断语。
        """
        return bool(self.original_text.strip() and self.url.strip())

    def to_dict(self) -> dict[str, str | None]:
        return {
            "book": self.book,
            "edition": self.edition,
            "chapter": self.chapter,
            "original_text": self.original_text,
            "url": self.url,
            "retrieved_on": self.retrieved_on.isoformat() if self.retrieved_on else None,
        }

"""典籍引用的规范标识（Canonical Citation URN）。

一条断语要能被复核，光有书名不够 —— 书名相同的版本，条文可以不一样
（Phase 2 已经踩过：「甲戊庚牛羊」与「甲戊兼牛羊」的差别在底本，不在书名）。
所以每条引用需要一个**能定位到具体版本、具体卷、具体篇、具体条目**的标识。

语法::

    urn:divination:<体系>:<底本代码>:<版本>:<卷>[.<篇>[.<条目>]]

例::

    urn:divination:bazi:sanmingtonghui:ws845354:j8.liujia_ri.jiazi_jiazi_01
                    │     │              │        │  │         └ 条目
                    │     │              │        │  └ 篇
                    │     │              │        └ 卷
                    │     │              └ 版本（维基文库 revid 845354）
                    │     └ 底本代码（三命通會）
                    └ 体系（子平八字）

**为什么比老板给的示例多一段「版本」。** 原示例是
``urn:divination:bazi:sanming:v8.liujia_ri.jiazi_jiazi_01`` —— 五段，
没有版本位。但同一个底本代码可以对应多个版本（明万历刻本 / 文渊阁四库全书本 /
维基文库转录本），条文不同。URN 的用途是「反查出完整出处元数据」，
如果两版共用同一个 URN，反查回来的元数据就是错的。所以版本必须是 URN 的一部分。

段位的字符集限定为 ``[a-z0-9_]``：URN 是要写进 JSON、URL、命令行、日志的东西，
不允许出现需要转义的字符。中文放在**元数据**里，不放在 URN 里 ——
标识要稳定，展示要好看，这是两件事。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

URN_PREFIX = "urn:divination"

SYSTEMS: dict[str, str] = {
    "bazi": "子平八字",
    "zwds": "紫微斗數",
}
"""已登记的数术体系。

不在表里的体系直接拒绝：体系名如果可以是任意字符串，URN 的「体系」段
就退化成了注释 —— 拼错的体系不会报错，只会让反查永远查不到东西。
"""

MAX_CHAPTER_DEPTH = 3
"""``卷.篇.条目`` 最多三段。"""

_SEGMENT = r"[a-z0-9_]+"
_URN_PATTERN = re.compile(
    rf"^{re.escape(URN_PREFIX)}:(?P<system>{_SEGMENT}):(?P<edition>{_SEGMENT}):"
    rf"(?P<version>{_SEGMENT}):(?P<unit>{_SEGMENT}(?:\.{_SEGMENT}){{0,{MAX_CHAPTER_DEPTH - 1}}})$"
)
_JUAN_PATTERN = re.compile(r"^j[a-z0-9]+$")


@dataclass(frozen=True)
class DivinationUrn:
    """一条可定位到具体版本的典籍标识。"""

    system: str
    edition: str
    version: str
    juan: str
    chapter: str = ""
    entry: str = ""

    def __post_init__(self) -> None:
        if self.system not in SYSTEMS:
            raise ValueError(
                f"未登记的体系 {self.system!r}；已登记：{'、'.join(sorted(SYSTEMS))}。"
            )
        for name, value in (("底本代码", self.edition), ("版本", self.version)):
            if not re.fullmatch(_SEGMENT, value):
                raise ValueError(f"URN 的{name}必须是 [a-z0-9_]：{value!r}")
        if not _JUAN_PATTERN.fullmatch(self.juan):
            raise ValueError(
                f"URN 的卷号必须是 j 加字母数字（如 j8、j1）：{self.juan!r}"
            )
        for name, value in (("篇", self.chapter), ("条目", self.entry)):
            if value and not re.fullmatch(_SEGMENT, value):
                raise ValueError(f"URN 的{name}代码必须是 [a-z0-9_]：{value!r}")
        if self.entry and not self.chapter:
            raise ValueError("URN 给了条目却缺篇代码：无法定位。")

    @property
    def system_name(self) -> str:
        return SYSTEMS[self.system]

    def to_urn(self) -> str:
        unit = ".".join(part for part in (self.juan, self.chapter, self.entry) if part)
        return f"{URN_PREFIX}:{self.system}:{self.edition}:{self.version}:{unit}"

    def __str__(self) -> str:
        return self.to_urn()

    def to_dict(self) -> dict[str, Any]:
        return {
            "urn": self.to_urn(),
            "system": self.system,
            "system_name": self.system_name,
            "edition": self.edition,
            "version": self.version,
            "juan": self.juan,
            "chapter": self.chapter,
            "entry": self.entry,
        }


def parse(text: str) -> DivinationUrn:
    """解析 URN；不合法时抛 ``ValueError``，消息可直接展示给用户。"""
    candidate = text.strip()
    if not candidate:
        raise ValueError("URN 不能为空。")
    match = _URN_PATTERN.fullmatch(candidate)
    if match is None:
        raise ValueError(
            f"URN 格式不合法：{text!r}。"
            f"应为 {URN_PREFIX}:<体系>:<底本>:<版本>:<卷>[.<篇>[.<条目>]]，"
            "各段只允许 [a-z0-9_]。"
        )
    parts = match.group("unit").split(".")
    return DivinationUrn(
        system=match.group("system"),
        edition=match.group("edition"),
        version=match.group("version"),
        juan=parts[0],
        chapter=parts[1] if len(parts) > 1 else "",
        entry=parts[2] if len(parts) > 2 else "",
    )


def try_parse(text: str) -> DivinationUrn | None:
    """解析失败返回 ``None``，不抛异常。用于「这串东西是不是 URN」的判断。"""
    try:
        return parse(text)
    except ValueError:
        return None


def is_urn(text: str) -> bool:
    return try_parse(text) is not None


def make(
    system: str, edition: str, version: str, juan: str, chapter: str = "", entry: str = ""
) -> DivinationUrn:
    """构造 URN。与 :func:`parse` 共用同一套校验，不存在「能构造但解析不了」。"""
    return DivinationUrn(system, edition, version, juan, chapter, entry)

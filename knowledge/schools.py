"""流派注册表：把 ``school`` 从自由字符串收敛为显式、可扩展的取值域。

原实现里 ``school`` 只是一个字符串字段，谁都可以随手写一个新的。结果是
「流派」这个概念在系统里没有实际约束力：既无法枚举，也无法回答「本系统
支持哪些流派」。这里把它变成注册表，规则必须挂到已注册的流派上。

设计取舍：注册表**可扩展但显式**。新增流派要写一条 :class:`School` 记录，
说明核心方法、代表典籍和已知分歧点。这样流派差异在代码里是看得见的，
而不是散落在各条规则的注释里。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

STRUCTURAL_SCHOOL = "structural_common"
"""公共结构层：各流派共用的定义性事实，本身不构成流派判断。"""


@dataclass(frozen=True)
class School:
    """一个流派的元数据。"""

    id: str
    name: str
    method: str
    classics: tuple[str, ...] = ()
    divergences: tuple[str, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("流派必须有 id。")
        if not self.name.strip():
            raise ValueError(f"流派 {self.id} 必须有中文名。")
        if not self.method.strip():
            raise ValueError(f"流派 {self.id} 必须说明核心方法。")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "method": self.method,
            "classics": list(self.classics),
            "divergences": list(self.divergences),
            "note": self.note,
        }


DEFAULT_SCHOOLS: tuple[School, ...] = (
    School(
        id=STRUCTURAL_SCHOOL,
        name="公共结构层",
        method="只描述命盘结构事实，不做吉凶取舍；十神、藏干、五行生克、地支关系的定义由 "
               "engines.bazi 唯一确定，可执行验证。",
        classics=(),
        divergences=(),
        note="这一层不是流派，是所有流派共同接受的定义层。它只负责「命盘里有什么」，"
             "不负责「这意味着什么」。",
    ),
    School(
        id="zi_ping_orthodox",
        name="子平正统",
        method="以月令为纲定格局，据格局与日主强弱取用神。",
        classics=("《渊海子平》", "《子平真诠》"),
        divergences=(
            "格局取用与调候取用冲突时的优先级",
            "月令本气不透时，是取月令本气定格还是取透干者定格",
        ),
        note="断语类规则自 Phase 5 起录入：底本为《三命通會》卷八（维基文库转录本，"
             "版本已固化并逐条核对原文）。当前仅覆盖六甲日甲子时一段，范围有限。",
    ),
    School(
        id="di_tian_sui",
        name="滴天髓派",
        method="以通关、调候、气势顺逆论命，重全局流通而不拘泥格局名称。",
        classics=("《滴天髓》",),
        divergences=(
            "与子平正统在「格局名称是否具有独立解释力」上的分歧",
            "从格与化格的成立条件",
        ),
        note="MINGLI_PLAN.md 指定的优先录入对象，但原文底本未确认，规则暂不录入。",
    ),
    School(
        id="mang_pai",
        name="盲派",
        method="以「做功」论命，重干支作用关系与制化，轻格局名称与神煞。",
        classics=(),
        divergences=(
            "对神煞的取舍：盲派基本不用神煞，子平体系则大量使用",
            "对「做功」路径的认定依赖师承口诀，缺少可公开核验的文本",
        ),
        note="无公有领域典籍可引，其口诀属口传系统。若要录入，必须先解决来源合法性问题。",
    ),
    School(
        id="xiang_fa",
        name="象法新派",
        method="以干支象义和类象直接取事，弱化五行旺衰的量化判断。",
        classics=(),
        divergences=(
            "象义取用的随意性较大，同一命盘可给出多种类象",
        ),
        note="现代流派，无公有领域典籍。录入前需明确采用哪一家的成文体系。",
    ),
)


@dataclass
class SchoolRegistry:
    """流派注册表；重复 ID 直接拒绝，避免静默覆盖。"""

    _schools: dict[str, School] = field(default_factory=dict)

    def register(self, school: School) -> None:
        if school.id in self._schools:
            raise ValueError(f"流派 ID 已存在：{school.id}")
        self._schools[school.id] = school

    def get(self, school_id: str) -> School:
        try:
            return self._schools[school_id]
        except KeyError as exc:
            raise KeyError(f"未知流派：{school_id}") from exc

    def has(self, school_id: str) -> bool:
        return school_id in self._schools

    def ids(self) -> tuple[str, ...]:
        """全部已注册流派 ID（已排序）。

        给报错消息用：把「已注册的有哪些」直接摆出来，比只报「你写错了」
        少一轮来回。排序是为了让消息可复现 —— 字典序不确定的话，
        同一条错误每次跑出来顺序都不一样，测试没法断言。
        """
        return tuple(sorted(self._schools))

    def require(self, school_id: str) -> School:
        """校验一个流派已注册；规则挂载时用它挡住拼错的 school。"""
        if not self.has(school_id):
            known = "、".join(sorted(self._schools))
            raise ValueError(f"规则引用了未注册的流派 {school_id!r}；已注册：{known}")
        return self.get(school_id)

    def select(self) -> tuple[School, ...]:
        """返回全部已注册流派。

        方法名不叫 ``list`` —— 在类体里 ``list`` 会遮蔽内置类型，任何
        ``list[Rule]`` 形式的注解都会被 mypy 解析成这个方法而报错。
        :class:`~knowledge.rules.RuleRegistry` 因此统一改用 ``select``。
        """
        return tuple(self._schools.values())


def default_school_registry() -> SchoolRegistry:
    registry = SchoolRegistry()
    for school in DEFAULT_SCHOOLS:
        registry.register(school)
    return registry

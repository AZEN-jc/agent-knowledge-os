"""结构层规则库：只收录可由命盘结构直接验证的规则。

这一层刻意不引典籍。原因不是典籍不重要，而是**现在没有可核验的底本**：
在拿到可复核的原文之前，任何写成「《滴天髓》云……」的断语都可能是转抄的
二手话术，那正是 MINGLI_PLAN.md 明令禁止的「编造命理规则」。

所以这里收录的全部是另一类东西：由 :mod:`engines.bazi` 的定义表唯一确定的
结构事实。十神是什么、藏干有哪几个、五行怎么生克、六冲是哪六对 —— 这些
跑一遍代码就能证伪，不需要文献背书。它们的来源诚实地写成「结构定义」，
不冒充经典。

``classical`` 层级的骨架见 :mod:`knowledge.classical_backlog` —— 那里**故意
不放任何 ``Rule`` 对象**，只记录「要录什么、卡在哪一步」，等底本确认后才允许
逐条写成 ``ACTIVE``。

关于「冲突」：本模块收录了两种**格局命名法**（本气定格 / 透干定格）。它们是
真实存在的分歧，但只在两法给出不同格局名时才算冲突，所以用 ``conflict_slot``
表达，而不是静态的 ``conflicts_with`` —— 后者会在两法结论一致时误报。
"""

from __future__ import annotations

from engines.bazi.ten_gods import TEN_GODS
from knowledge.evidence import ELEMENT_NAMES
from knowledge.provenance import ReviewStatus, SourceTier
from knowledge.rules import Rule
from knowledge.schools import STRUCTURAL_SCHOOL

PATTERN_TEN_GODS = tuple(god for god in TEN_GODS if god not in ("比肩", "劫财"))
"""可作为格局名的八种十神；比肩与劫财另立建禄、月刃两条。

从 :data:`engines.bazi.ten_gods.TEN_GODS` 派生而不是另写一份，避免两处
十神表各自漂移。
"""

ELEMENTS = ELEMENT_NAMES
"""五行名，与事实词表共用同一份定义。"""

RELATIONS = ("六冲", "六合", "六害", "相破", "自刑", "三刑")
"""地支关系类型，与 :mod:`engines.bazi.sxtwl_provider` 的关系表一一对应。"""

STRUCTURAL_SOURCE = "命盘结构定义（engines.bazi 的十神、藏干、五行生克与地支关系表，可执行验证）"

_PATTERN_SLOT = "pattern_name"
"""格局命名槽：两种定格法在同一槽位上给出不同格局名时才算真冲突。"""


def _rule(
    rule_id: str,
    category: str,
    condition: dict[str, object],
    conclusion: str,
    *,
    confidence: str = "HIGH",
    evidence: tuple[str, ...] = (),
    note: str = "",
    conflict_slot: str = "",
    conflict_value: str = "",
) -> Rule:
    return Rule(
        id=rule_id,
        source=STRUCTURAL_SOURCE,
        school=STRUCTURAL_SCHOOL,
        category=category,
        topic="structure",
        condition=condition,
        conclusion=conclusion,
        confidence=confidence,
        evidence_required=evidence,
        note=note,
        source_tier=SourceTier.STRUCTURAL,
        review_status=ReviewStatus.ACTIVE,
        conflict_slot=conflict_slot,
        conflict_value=conflict_value,
    )


def ten_god_rules() -> tuple[Rule, ...]:
    """十神透干：有根 / 虚透。"""
    rules: list[Rule] = [
        _rule(
            "STRUCT_TEN_GOD_001", "ten_god",
            {"month_ten_god": "正官"},
            "正官透于月柱天干；月干为用事之地，此处只说明结构位置，不推出职业结论。",
            evidence=("month_ten_god",),
        ),
    ]
    for index, god in enumerate(TEN_GODS, start=1):
        rules.append(_rule(
            f"STRUCT_ROOT_{index:03d}", "ten_god",
            {"ten_god_with_root": god},
            f"{god}透于天干且四支藏干中有同类，属有根之透。",
            evidence=("ten_god_with_root",),
        ))
        rules.append(_rule(
            f"STRUCT_VOID_{index:03d}", "ten_god",
            {"ten_god_without_root": god},
            f"{god}透于天干而四支藏干中不见同类，属虚透；结构上缺少地支支撑。",
            confidence="MEDIUM",
            evidence=("ten_god_without_root",),
        ))
    return tuple(rules)


def pattern_rules() -> tuple[Rule, ...]:
    """格局命名：本气定格法与透干定格法。

    两法并列收录。它们在月支本气不透、而中气或余气透干时给出不同格局名 ——
    这是真实分歧，系统并列输出，不投票选出「真格局」。
    """
    rules: list[Rule] = []
    for index, god in enumerate(PATTERN_TEN_GODS, start=1):
        rules.append(_rule(
            f"STRUCT_PATTERN_{index:03d}", "pattern",
            {"month_branch_ten_god": god},
            f"月支本气对日主为{god}，按本气定格法得{god}格；格局名只是结构标签，不含吉凶。",
            evidence=("month_branch_ten_god",),
            conflict_slot=_PATTERN_SLOT,
            conflict_value=f"{god}格",
        ))
    for index, god in enumerate(PATTERN_TEN_GODS, start=1):
        rules.append(_rule(
            f"STRUCT_PATTERN_EXT_{index:03d}", "pattern",
            {"month_branch_extended_ten_god": god},
            f"月支藏干中的{god}透于年月时天干，按透干定格法得{god}格。",
            confidence="MEDIUM",
            evidence=("month_branch_extended_ten_god",),
            note="透干定格法：以月支藏干中透出天干者为格。与本气定格法分歧。",
            conflict_slot=_PATTERN_SLOT,
            conflict_value=f"{god}格",
        ))
    return tuple(rules)


def month_command_rules() -> tuple[Rule, ...]:
    """月令与日主的关系，以及建禄、月刃。"""
    return (
        _rule(
            "STRUCT_JIANLU_001", "pattern",
            {"month_branch_ten_god": "比肩"},
            "月支本气为比肩，日主临官于月支，结构上称建禄。",
            evidence=("month_branch_ten_god",),
            note="建禄是否算「格局」，各体系处理不同：有列为专格者，也有主张不入八格另论者。"
                 "本实现只做结构命名，不站队。",
        ),
        _rule(
            "STRUCT_YUEREN_001", "pattern",
            {"month_branch_ten_god": "劫财"},
            "月支本气为劫财，日主帝旺于月支，结构上称月刃（羊刃）。",
            evidence=("month_branch_ten_god",),
        ),
        _rule(
            "STRUCT_MONTH_001", "strength",
            {"day_master_vs_month": "同我"},
            "月令与日主同五行，月令为比劫之地。",
            evidence=("day_master_vs_month",),
        ),
        _rule(
            "STRUCT_MONTH_002", "strength",
            {"day_master_vs_month": "生我"},
            "月令生日主，月令为印之地。",
            evidence=("day_master_vs_month",),
        ),
        _rule(
            "STRUCT_MONTH_003", "strength",
            {"day_master_vs_month": "我生"},
            "日主生月令，月令为食伤之地。",
            evidence=("day_master_vs_month",),
        ),
        _rule(
            "STRUCT_MONTH_004", "strength",
            {"day_master_vs_month": "我克"},
            "日主克月令，月令为财之地。",
            evidence=("day_master_vs_month",),
        ),
        _rule(
            "STRUCT_MONTH_005", "strength",
            {"day_master_vs_month": "克我"},
            "月令克日主，月令为官杀之地。",
            evidence=("day_master_vs_month",),
        ),
    )


def day_master_rules() -> tuple[Rule, ...]:
    """日主根气与同类多寡。"""
    return (
        _rule(
            "STRUCT_DM_ROOT_001", "strength",
            {"day_master_root": "有根"},
            "日主在四支藏干中有同类，结构上为有根。",
            evidence=("day_master_root",),
        ),
        _rule(
            "STRUCT_DM_ROOT_002", "strength",
            {"day_master_root": "无根"},
            "日主在四支藏干中不见同类，结构上为无根（虚浮）。",
            confidence="MEDIUM",
            evidence=("day_master_root",),
            note="本实现按「同五行」判有根。更严格的本气根口径要求同五行且同阴阳，"
                 "属另一分歧点，尚未录入。",
        ),
        _rule(
            "STRUCT_DM_LEVEL_001", "strength",
            {"day_master_same_element_level": "偏少"},
            "日主同类（比劫与印）在命局中出现次数偏少。",
            confidence="MEDIUM",
            evidence=("day_master_same_element_level",),
        ),
        _rule(
            "STRUCT_DM_LEVEL_002", "strength",
            {"day_master_same_element_level": "中等"},
            "日主同类在命局中出现次数中等。",
            confidence="MEDIUM",
            evidence=("day_master_same_element_level",),
        ),
        _rule(
            "STRUCT_DM_LEVEL_003", "strength",
            {"day_master_same_element_level": "偏多"},
            "日主同类在命局中出现次数偏多。",
            confidence="MEDIUM",
            evidence=("day_master_same_element_level",),
        ),
    )


def element_rules() -> tuple[Rule, ...]:
    """五行计数的结构描述。

    计数口径是「四柱天干 + 四支本气」共 8 项，由本实现选定并明示；不同流派
    对藏干是否计入、计几位存在分歧，所以这些规则只描述本口径下的计数，
    不宣称是唯一正确口径。
    """
    rules: list[Rule] = []
    for index, element in enumerate(ELEMENTS, start=1):
        rules.append(_rule(
            f"STRUCT_ELEMENT_MISS_{index:03d}", "element",
            {"missing_elements": element},
            f"按本实现计数口径，四柱不见{element}。",
            confidence="MEDIUM",
            evidence=("missing_elements",),
            note="「缺某五行」高度依赖计数口径：把藏干全部计入后，原本判缺的五行常常并不缺。",
        ))
    for index, element in enumerate(ELEMENTS, start=1):
        rules.append(_rule(
            f"STRUCT_ELEMENT_DOM_{index:03d}", "element",
            {"dominant_elements": element},
            f"按本实现计数口径，{element}出现三次以上，计数偏旺。",
            confidence="MEDIUM",
            evidence=("dominant_elements",),
        ))
    return tuple(rules)


def relation_rules() -> tuple[Rule, ...]:
    """地支关系与关系密度。"""
    rules: list[Rule] = []
    for index, relation in enumerate(RELATIONS, start=1):
        rules.append(_rule(
            f"STRUCT_RELATION_{index:03d}", "relation",
            {"has_relation": relation},
            f"四支中存在{relation}结构；具体取象需结合流派与其他证据。",
            evidence=("has_relation",),
        ))
    rules.extend((
        _rule(
            "STRUCT_RELATION_DENSITY_001", "relation",
            {"relation_density": "无"},
            "四支之间没有任何合冲刑害破关系，结构上彼此孤立。",
            evidence=("relation_density",),
        ),
        _rule(
            "STRUCT_RELATION_DENSITY_002", "relation",
            {"relation_density": "少"},
            "四支之间存在少量关系（一至两条）。",
            evidence=("relation_density",),
        ),
        _rule(
            "STRUCT_RELATION_DENSITY_003", "relation",
            {"relation_density": "多"},
            "四支之间存在三条以上关系，结构上互动密集。",
            evidence=("relation_density",),
        ),
    ))
    return tuple(rules)


def structural_rules() -> tuple[Rule, ...]:
    """结构层规则全集。

    顺序有意义：``STRUCT_PATTERN_*`` 必须排在 ``STRUCT_PATTERN_EXT_*`` 之前，
    因为注册表在 ``add`` 时会校验 ``conflicts_with`` 引用的规则是否已存在。
    """
    return (
        ten_god_rules()
        + pattern_rules()
        + month_command_rules()
        + day_master_rules()
        + element_rules()
        + relation_rules()
    )

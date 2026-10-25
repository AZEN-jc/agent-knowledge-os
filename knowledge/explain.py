"""术语与人话解释：把结构语言翻成普通中文（Phase 6.1）。

## 这个文件守什么

产品里最劝退的一句话是：「比肩透于天干且四支藏干中有同类，属有根之透。」
懂命理的人一眼明白，不懂的人一个字都读不进去 —— 而「让人看懂」是老板
明确提的要求。

这一层只做**翻译**，不做解释性发挥：

- 术语表给的是**结构定义**（偏财＝日主所克且阴阳相同），不是吉凶含义
  （「偏财代表横财」是判断，不能写）；
- 条件模板描述**命盘里实际有什么**，不推导「所以你会怎样」；
- 每条模板都必须能在 `FACT_SCHEMA` 里找到对应的键 —— 词表加了新键却
  没写人话，测试会红。

## 一条纪律

模板里不许出现吉凶词（吉、凶、好、坏、旺夫、克妻、富贵、贫贱……）。
它们属于断语，不属于翻译。`tests/test_explain.py` 用禁用词表守着。
"""

from __future__ import annotations

from typing import Any

from knowledge.facts import FACT_SCHEMA

#: 术语表：结构定义，不含吉凶。
#:
#: 每个词条三段：``term`` 词本身、``plain`` 一句话定义、``example`` 一个
#: 具体例子（可选）。写定义时反复问一句：这句话换成任何一个流派会反对吗？
#: 会，就说明它不是定义。
GLOSSARY: tuple[dict[str, str], ...] = (
    {
        "term": "四柱",
        "plain": "出生的年、月、日、时各用一个天干加一个地支表示，合起来八个字，所以也叫八字。",
        "example": "1990 年 2 月 28 日 0 时 → 庚午 戊寅 甲子 甲子",
    },
    {
        "term": "日主",
        "plain": "日柱的天干，代表命盘的主人。所有十神都以它为参照算出来。",
        "example": "甲子日 → 日主是甲",
    },
    {
        "term": "天干 / 地支",
        "plain": "天干十个（甲乙丙丁戊己庚辛壬癸），地支十二个（子丑寅卯辰巳午未申酉戌亥）。每柱上干下支。",
    },
    {
        "term": "藏干",
        "plain": "每个地支内部还藏着 1–3 个天干，叫藏干。地支的力量通过藏干体现。",
        "example": "寅藏甲、丙、戊",
    },
    {
        "term": "透干",
        "plain": "某个十神出现在四个天干上（年干、月干、时干），叫透干 —— 露在外面，看得见。",
    },
    {
        "term": "有根 / 虚透",
        "plain": "透在天干上的十神，如果地支藏干里也有同类，叫「有根」；没有，叫「虚透」—— 浮在上面，底下没支撑。",
    },
    {
        "term": "十神",
        "plain": "以日主为参照，把其他天干与日主的生克和阴阳关系分成十类：比肩、劫财、食神、伤官、偏财、正财、七杀、正官、偏印、正印。它只描述结构关系，不判断好坏。",
    },
    {
        "term": "比肩 / 劫财",
        "plain": "与日主同五行的十神。阴阳相同叫比肩，阴阳不同叫劫财。",
    },
    {
        "term": "食神 / 伤官",
        "plain": "日主所生（我生）的十神。阴阳相同叫食神，不同叫伤官。",
    },
    {
        "term": "偏财 / 正财",
        "plain": "日主所克（我克）的十神。阴阳相同叫偏财，不同叫正财。",
    },
    {
        "term": "七杀 / 正官",
        "plain": "克日主（克我）的十神。阴阳相同叫七杀，不同叫正官。",
    },
    {
        "term": "偏印 / 正印",
        "plain": "生日主（生我）的十神。阴阳相同叫偏印，不同叫正印。",
    },
    {
        "term": "月令",
        "plain": "月柱的地支，代表出生的季节环境。命理里它权重最高，很多断语先看月令。",
    },
    {
        "term": "五行计数",
        "plain": "把四柱的四个天干和四个地支本气（共 8 项）按五行归类后数个数。这是计数口径，不是旺衰判定。",
        "example": "木3 火1 土1 金1 水2",
    },
    {
        "term": "偏旺 / 缺失",
        "plain": "某个五行计数达到 3 次以上叫偏旺；计数为 0 叫缺失。都只是计数结果。",
    },
    {
        "term": "地支关系",
        "plain": "四支两两之间的固定组合：六合、六冲、六害、相破、自刑、三刑。它们是结构关系，不直接等于好坏。",
    },
    {
        "term": "大运",
        "plain": "每十年一步的运程，由月柱顺推或逆推得到。顺逆取决于年干阴阳与性别。",
    },
    {
        "term": "流年",
        "plain": "某一年的干支，用来和命盘四支比对，看这一年激活了哪些结构关系。",
    },
    {
        "term": "证据强度",
        "plain": "本次分析命中了多少条规则、各自置信度多高，折算成 0–1 的一个数。它是证据等级，不是事件概率。",
    },
    {
        "term": "覆盖状态",
        "plain": "这个主题有没有专属的典籍断语。有 = 已覆盖；只有公共结构层 = 仅基础；未登记 = 未知主题。",
    },
)

#: 禁用词：翻译层不许出现吉凶判断。断语里有这些字是正常的（那是底本原文），
#: 但解释文本里出现，说明翻译滑成了判断。
FORBIDDEN_IN_EXPLANATION = (
    "吉", "凶", "富贵", "贫贱", "旺夫", "克妻", "克夫", "旺子",
    "大富", "大贵", "灾", "祸", "福气", "倒霉", "注定",
)


def _fmt(value: Any) -> str:
    """把事实值写成中文可读形式：列表用顿号、字符串加引号。"""
    if isinstance(value, (list, tuple)):
        return "、".join(_fmt(item) for item in value)
    if isinstance(value, str):
        return f"「{value}」"
    if value is None:
        return "空"
    return str(value)


def _ten_god_sentence(name: str) -> str:
    return f"{name}"


#: 键 → (expected, actual) → 一句人话。
#:
#: 只描述**命盘里有什么**，不推导结论。每个 FACT_SCHEMA 的键都必须在这里
#: 有对应条目（测试枚举），否则新加的事实对读者永远是黑话。
TEMPLATES: dict[str, Any] = {
    # 日主
    "day_master": lambda expected, actual: f"日主是{_fmt(actual)}。",
    "day_master_element": lambda expected, actual: f"日主属{_fmt(actual)}。",
    "day_master_polarity": lambda expected, actual: f"日主是{_fmt(actual)}干。",
    "day_master_root": lambda expected, actual: (
        f"日主在四支藏干里{'有' if actual == '有根' else '没有'}同类，术语叫{_fmt(actual)}。"
    ),
    "day_master_same_element_count": lambda expected, actual: (
        f"四柱天干与藏干中，与日主同五行的共 {actual} 个。"
    ),
    # 四柱干支
    "year_stem": lambda expected, actual: f"年干是{_fmt(actual)}。",
    "month_stem": lambda expected, actual: f"月干是{_fmt(actual)}。",
    "day_stem": lambda expected, actual: f"日干是{_fmt(actual)}（也就是日主）。",
    "hour_stem": lambda expected, actual: f"时干是{_fmt(actual)}。",
    "year_branch": lambda expected, actual: f"年支是{_fmt(actual)}。",
    "month_branch": lambda expected, actual: f"月支是{_fmt(actual)}。",
    "day_branch": lambda expected, actual: f"日支是{_fmt(actual)}。",
    "hour_branch": lambda expected, actual: f"时支是{_fmt(actual)}。",
    "four_branches": lambda expected, actual: f"四支分别是{_fmt(actual)}。",
    "repeated_branches": lambda expected, actual: (
        f"{_fmt(actual)}在四支中重复出现。"
        if actual else "四支没有重复。"
    ),
    "year_pillar": lambda expected, actual: f"年柱是{_fmt(actual)}。",
    "month_pillar": lambda expected, actual: f"月柱是{_fmt(actual)}。",
    "day_pillar": lambda expected, actual: f"日柱是{_fmt(actual)}。",
    "hour_pillar": lambda expected, actual: f"时柱是{_fmt(actual)}。",
    # 十神
    "year_ten_god": lambda expected, actual: f"年干对日主是{_ten_god_sentence(_fmt(actual))}。",
    "month_ten_god": lambda expected, actual: f"月干对日主是{_ten_god_sentence(_fmt(actual))}。",
    "hour_ten_god": lambda expected, actual: f"时干对日主是{_ten_god_sentence(_fmt(actual))}。",
    "transparent_ten_gods": lambda expected, actual: (
        f"露在天干上的十神有：{_fmt(actual)}。"
    ),
    "hidden_ten_gods": lambda expected, actual: (
        f"四支藏干对应的十神有：{_fmt(actual)}。"
    ),
    "ten_god_with_root": lambda expected, actual: (
        f"{_fmt(expected)}出现在天干上，地支藏干里也有同类 —— 术语叫「有根」。"
    ),
    "ten_god_without_root": lambda expected, actual: (
        f"{_fmt(expected)}出现在天干上，但地支藏干里没有同类 —— 术语叫「虚透」。"
    ),
    # 月令
    "month_branch_element": lambda expected, actual: f"月支本气属{_fmt(actual)}。",
    "month_branch_ten_god": lambda expected, actual: (
        f"月支本气对日主是{_fmt(actual)}，也就是月令{_fmt(actual)}。"
    ),
    "month_branch_extended_ten_god": lambda expected, actual: (
        f"月支藏干里透到天干上的十神是{_fmt(actual)}。"
    ),
    "day_master_vs_month": lambda expected, actual: (
        f"日主与月令的关系是{_fmt(actual)}"
        + {"同我": "（同类）", "生我": "（月令生日主）",
           "我生": "（日主生月令）", "我克": "（日主克月令）",
           "克我": "（月令克日主）"}.get(str(actual), "")
        + "。"
    ),
    "year_month_elements": lambda expected, actual: (
        f"年月两柱出现的五行有：{_fmt(actual)}。"
    ),
    # 五行计数
    "count_木": lambda expected, actual: f"木出现 {actual} 次（天干 + 四支本气共 8 项）。",
    "count_火": lambda expected, actual: f"火出现 {actual} 次（天干 + 四支本气共 8 项）。",
    "count_土": lambda expected, actual: f"土出现 {actual} 次（天干 + 四支本气共 8 项）。",
    "count_金": lambda expected, actual: f"金出现 {actual} 次（天干 + 四支本气共 8 项）。",
    "count_水": lambda expected, actual: f"水出现 {actual} 次（天干 + 四支本气共 8 项）。",
    "missing_elements": lambda expected, actual: (
        f"四柱天干与四支本气里没有{_fmt(actual)}。" if actual else "五行不缺。"
    ),
    "dominant_elements": lambda expected, actual: (
        f"{_fmt(actual)}出现 3 次以上，术语叫「偏旺」。" if actual else "没有偏旺的五行。"
    ),
    # 地支结构
    "has_relation": lambda expected, actual: (
        f"四支之间存在{_fmt(actual)}。" if actual else "四支之间没有结构关系。"
    ),
    "relation_count": lambda expected, actual: f"四支之间共 {actual} 组关系。",
    "relation_density": lambda expected, actual: f"地支关系密度：{_fmt(actual)}。",
    "day_master_same_element_level": lambda expected, actual: (
        f"日主的同类（比肩、劫财与印）在命局里{_fmt(actual)}。"
    ),
    # 时间轴
    "liunian_pillar": lambda expected, actual: f"这一年的干支是{_fmt(actual)}。",
    "liunian_stem_ten_god": lambda expected, actual: (
        f"这一年天干对日主是{_fmt(actual)}。"
    ),
    "liunian_branch_ten_god": lambda expected, actual: (
        f"这一年地支本气对日主是{_fmt(actual)}。"
    ),
    "liunian_relations": lambda expected, actual: (
        f"这一年与命盘四支的关系有{_fmt(actual)}。" if actual else "这一年与四支没有结构关系。"
    ),
    "liunian_relation_pairs": lambda expected, actual: (
        f"具体是{_fmt(actual)}。" if actual else "这一年与四支没有具体关系。"
    ),
    "liunian_stem_ten_god_root": lambda expected, actual: (
        f"这一年天干的十神在四支藏干里{_fmt(actual)}。"
    ),
    "dayun_pillar": lambda expected, actual: f"这一步大运的干支是{_fmt(actual)}。",
    "dayun_stem_ten_god": lambda expected, actual: (
        f"这一步大运天干对日主是{_fmt(actual)}。"
    ),
    "dayun_branch_ten_god": lambda expected, actual: (
        f"这一步大运地支本气对日主是{_fmt(actual)}。"
    ),
    "dayun_relations": lambda expected, actual: (
        f"这一步大运与命盘四支的关系有{_fmt(actual)}。" if actual else "这一步大运与四支没有结构关系。"
    ),
    "dayun_relation_pairs": lambda expected, actual: (
        f"具体是{_fmt(actual)}。" if actual else "这一步大运与四支没有具体关系。"
    ),
    "dayun_stem_ten_god_root": lambda expected, actual: (
        f"这一步大运天干的十神在四支藏干里{_fmt(actual)}。"
    ),
}

#: 覆盖状态的普通说法。
STATUS_PLAIN: dict[str, str] = {
    "covered": "这个主题有专属的典籍断语，下面的结论来自底本原文。",
    "base_only": "这个主题还没有专属的典籍断语，下面的证据全部来自公共结构层 —— 它描述的是命盘结构，不构成对这个主题的判断。",
    "unknown": "这个主题没有登记，下面的证据只来自公共结构层。",
}


def explain_condition(key: str, expected: Any, actual: Any) -> str:
    """把一个条件翻成人话。

    没有模板时退回 ``FACT_SCHEMA`` 的描述加实际值 —— 那是兜底，不是
    正常路径：``tests/test_explain.py`` 要求每个键都有模板。
    """
    template = TEMPLATES.get(key)
    if template is not None:
        return template(expected, actual)
    description = FACT_SCHEMA.get(key, key)
    return f"{description}：{_fmt(actual)}。"


def explain_strength(strength: float, breakdown: dict[str, Any]) -> str:
    """证据强度的人话说明。强调「等级不是概率」。"""
    supporting = breakdown.get("supporting_rules", 0)
    raw = breakdown.get("raw_support", 0)
    return (
        f"这次命中了 {supporting} 条规则，按各自的置信度加总为 {raw}，"
        f"折算成 0–1 的证据等级 {strength:.2f}。"
        f"这个数字衡量的是「证据有多少」，不是「事情会发生」的概率。"
    )


def explain_status(status: str) -> str:
    """覆盖状态的人话说明。"""
    return STATUS_PLAIN.get(status, STATUS_PLAIN["unknown"])


def explain_evidence(evidence: Any) -> str:
    """给整段证据写一句总述：先说结论来自哪里，再说命中多少条。

    ``evidence`` 是 ``knowledge.evidence.Evidence``（鸭子类型：只要求有
    ``status`` 与 ``matches``）。``matches`` 里每一项是 ``RuleMatch``，
    典籍层规则的 ``rule.urn`` 非空。
    """
    status_line = explain_status(str(evidence.status))
    matches = list(getattr(evidence, "matches", ()))
    if not matches:
        return f"{status_line}这次没有命中任何规则。"
    classical = [
        match for match in matches if getattr(getattr(match, "rule", None), "urn", None)
    ]
    head = f"这次共命中 {len(matches)} 条规则"
    if classical:
        head += f"，其中 {len(classical)} 条有典籍原文可查"
    return f"{status_line}{head}。下面按顺序列出每条的结构条件与出处。"

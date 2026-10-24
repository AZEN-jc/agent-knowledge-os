"""天干地支的基础定义表与十神计算。

这些是**定义**，不是流派判断：五行归属、阴阳、生克、十神对应关系由
天干地支本身唯一确定，任何流派都接受。因此它们不属于某个 provider，
也不属于某个流派 —— 谁需要谁引用。

原先这些表放在 :mod:`engines.bazi.sxtwl_provider` 里，导致证据层要算
藏干十神时只能去 import 一个 provider 适配器。拆出来之后，provider 只负责
「把 sxtwl 的结果转成项目模型」，定义表由本模块统一持有。
"""

from __future__ import annotations

from typing import Any

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"

ELEMENTS = {
    "甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土", "己": "土",
    "庚": "金", "辛": "金", "壬": "水", "癸": "水",
}

POLARITY = {
    "甲": "阳", "乙": "阴", "丙": "阳", "丁": "阴", "戊": "阳", "己": "阴",
    "庚": "阳", "辛": "阴", "壬": "阳", "癸": "阴",
}

GENERATES = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
CONTROLS = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}

TEN_GODS = (
    "比肩", "劫财", "食神", "伤官", "偏财", "正财", "七杀", "正官", "偏印", "正印",
)
"""十神全表；不含「日主」，日主是日柱天干本身，不是一个十神。"""

#: 五行名称，按相生顺序（木火土金水）。计数、缺失、偏旺的枚举顺序都用它 ——
#: 顺序本身是口径的一部分：``missing``/``dominant`` 的元组顺序可被断语与
#: 测试直接比较。
#:
#: 生产侧曾有两份拷贝：``knowledge.facts`` 定义一份，
#: ``knowledge.structural_rules`` 经 facts 转手再用。Phase 5.3 收编到本模块，
#: facts 改为转口 import。**``tests/test_evidence_audit`` 里那份不算** ——
#: 它是刻意独立重写的审计实现（同 lunar_python 差分测试的套路），
#: 与被测实现同源就失去了复核的意义。
ELEMENT_NAMES: tuple[str, ...] = ("木", "火", "土", "金", "水")

#: 「偏旺」的计数阈值。三命通会一系的断语里「旺」多以三重为旺（三刑、
#: 三合皆以三为数），取 3。改这个数会同时改变 facts 层的
#: ``dominant_elements`` 与 chart.elements 的 ``dominant`` —— 那是
#: 有意的：一个阈值，两个消费者。
DOMINANT_THRESHOLD = 3


def element_census(pillars: Any) -> dict[str, Any]:
    """五行普查：四柱天干 + 四支本气，共 8 项的计数与派生。

    口径（Phase 5.3 固定）：**只看天干与四支本气**，不含余气、不含
    纳音。这是「三命通会」系的计数法 —— 余气杂气各地支分量不同，混进来
    会让同一个「水数」在不同实现间差出两三个，而断语的范围容不下这种
    噪声。

    返回 ``{"count": {...}, "missing": (...), "dominant": (...)}``：

    - ``count`` 以 :data:`ELEMENT_NAMES` 为键序；
    - ``missing`` 是计数为 0 的补集；
    - ``dominant`` 是计数 ≥ :data:`DOMINANT_THRESHOLD` 的子集。

    ``pillars`` 是任何带 ``heavenly_stem``/``hidden_stems`` 的对象序列
    （``engines.bazi.models.Pillar`` 或其 dataclass 替换品）—— 不 import
    具体类型，provider 与 facts 层都能用。
    """
    counts = dict.fromkeys(ELEMENT_NAMES, 0)
    for pillar in pillars:
        counts[ELEMENTS[pillar.heavenly_stem]] += 1
        counts[ELEMENTS[pillar.hidden_stems[0]]] += 1
    return {
        "count": counts,
        "missing": tuple(e for e in ELEMENT_NAMES if counts[e] == 0),
        "dominant": tuple(e for e in ELEMENT_NAMES if counts[e] >= DOMINANT_THRESHOLD),
    }


def ten_god(day_master: str, stem: str, *, is_day_pillar: bool = False) -> str:
    """按日主五行、生克和阴阳计算天干十神。

    判定顺序（互斥且穷尽）：同五行 → 比劫；日主生 → 食伤；生 日主 → 印；
    日主克 → 财；克 日主 → 官杀。同阴阳取前一个（比肩/食神/偏财/七杀/偏印），
    异阴阳取后一个。
    """
    if is_day_pillar:
        return "日主"
    master_element = ELEMENTS[day_master]
    stem_element = ELEMENTS[stem]
    same_polarity = POLARITY[day_master] == POLARITY[stem]
    if stem_element == master_element:
        return "比肩" if same_polarity else "劫财"
    if stem_element == GENERATES[master_element]:
        return "食神" if same_polarity else "伤官"
    if master_element == GENERATES[stem_element]:
        return "偏印" if same_polarity else "正印"
    if stem_element == CONTROLS[master_element]:
        return "偏财" if same_polarity else "正财"
    return "七杀" if same_polarity else "正官"


def stem_relation(day_master_element: str, other_element: str) -> str:
    """日主五行与另一五行的关系，用于描述月令与日主的关系。

    返回 ``同我`` / ``生我`` / ``我生`` / ``我克`` / ``克我``，是纯粹的生克
    结构描述，不带旺衰吉凶判断。
    """
    if other_element == day_master_element:
        return "同我"
    if GENERATES[other_element] == day_master_element:
        return "生我"
    if GENERATES[day_master_element] == other_element:
        return "我生"
    if CONTROLS[day_master_element] == other_element:
        return "我克"
    return "克我"

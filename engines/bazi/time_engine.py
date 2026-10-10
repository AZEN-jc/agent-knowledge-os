"""八字时间轴基础能力：大运、流年和流月。

时间轴上的每个节点都由**节气的精确时刻**划定，而不是由日期零点划定。
这一点和年月柱的分界规则一致：节气日当天、节气时刻之前属于上一个区间。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from engines.bazi.jieqi import (
    as_instant,
    ganzhi_year,
    jie_terms_in,
    lichun_moment,
    month_pillar,
    surrounding_jie,
)
from engines.bazi.models import Chart
from engines.bazi.ten_gods import BRANCHES, POLARITY, STEMS

DAYS_PER_YEAR = 3.0  # 三日折一年
MONTHS_PER_DAY = 4  # 一日折四个月
DAYS_PER_MONTH = 30  # 折算用的整月天数


@dataclass(frozen=True)
class YearContext:
    year: int
    heavenly_stem: str
    earthly_branch: str
    sexagenary_index: int
    chart_provider: str


@dataclass(frozen=True)
class MonthContext:
    """一个流月：由某个「节」开启，到下个「节」结束。"""

    jie_name: str
    start: datetime
    end: datetime
    heavenly_stem: str
    earthly_branch: str
    ganzhi_year: int


def start_age_parts(offset_days: float) -> tuple[int, int, int]:
    """把「出生到相邻节的天数」折成年月日。

    折算口径：三日折一年、一日折四个月、一月按三十日计。这是传统起运的
    常用近似，不宣称覆盖按刻/分精算的流派。
    """
    if offset_days < 0:
        raise ValueError("offset_days 不能为负。")
    years = int(offset_days // DAYS_PER_YEAR)
    remainder = offset_days - years * DAYS_PER_YEAR
    months = int(remainder * MONTHS_PER_DAY)
    days = round((remainder * MONTHS_PER_DAY - months) * DAYS_PER_MONTH)
    if days >= DAYS_PER_MONTH:
        days -= DAYS_PER_MONTH
        months += 1
    if months >= 12:
        months -= 12
        years += 1
    return years, months, days


class DayunPolicy:
    """大运计算策略的显式边界；未选择流派前不提供默认顺逆。"""

    name = "unspecified"

    def calculate(self, chart: Chart) -> tuple[dict[str, object], ...]:
        raise NotImplementedError("尚未选择大运顺逆和起运策略。")


class ClassicalApproxDayunPolicy(DayunPolicy):
    """传统顺逆与三日折一年规则的显式近似实现。

    顺逆：阳年男、阴年女顺行，阴年男、阳年女逆行。
    起运：顺行数到出生后的**下一个节**，逆行数到出生前的**上一个节**，
    天数按三日折一年折算。相邻节取的是节气精确时刻，不是固定日期。

    这是可替换策略，不宣称覆盖所有流派；真实生产使用前必须用 golden cases 校核。
    """

    name = "classical_approx_v2"

    def calculate(self, chart: Chart) -> tuple[dict[str, object], ...]:
        if chart.birth.gender not in ("男", "女", "male", "female"):
            raise ValueError("计算大运需要 gender；不同流派的顺逆规则必须显式选择。")
        year_stem = chart.pillars[0].heavenly_stem
        male = chart.birth.gender in ("男", "male")
        forward = (POLARITY[year_stem] == "阳") == male
        month_index = _pillar_index(chart.pillars[1].heavenly_stem, chart.pillars[1].earthly_branch)
        direction = 1 if forward else -1

        instant = chart.birth.instant()
        previous, following = surrounding_jie(instant)
        boundary = following if forward else previous
        offset_days = abs((boundary.moment - instant).total_seconds()) / 86400
        years, months, days = start_age_parts(offset_days)
        start_age = offset_days / DAYS_PER_YEAR

        return tuple(
            {
                # 大运从月柱起，按六十甲子逐位顺/逆推，不是每隔十位取一个。
                "sequence": sequence,
                "heavenly_stem": STEMS[(month_index + direction * sequence) % 60 % 10],
                "earthly_branch": BRANCHES[(month_index + direction * sequence) % 60 % 12],
                "start_age_years": round(start_age + (sequence - 1) * 10, 2),
                "direction": "forward" if forward else "backward",
                "policy": self.name,
                "approximate": True,
                "start_offset_days": round(offset_days, 3),
                "start_boundary": boundary.name,
                "start_age_text": f"{years}年{months}个月{days}天",
            }
            for sequence in range(1, 9)
        )


def _pillar_index(stem: str, branch: str) -> int:
    return next(index for index in range(60) if index % 10 == STEMS.index(stem) and index % 12 == BRANCHES.index(branch))


def sexagenary_year(year: int) -> tuple[str, str, int]:
    """返回公历年份对应的干支年。

    只接受整年，因此不处理立春分界；要按立春精确时刻判定请用
    :func:`engines.bazi.jieqi.ganzhi_year`。
    """
    index = (year - 4) % 60
    return STEMS[index % 10], BRANCHES[index % 12], index


def year_context(chart: Chart, year: int) -> YearContext:
    stem, branch, index = sexagenary_year(year)
    return YearContext(year, stem, branch, index, chart.provider)


def year_contexts(chart: Chart, start_year: int, end_year: int) -> tuple[YearContext, ...]:
    if start_year > end_year:
        raise ValueError("start_year 不能大于 end_year。")
    return tuple(year_context(chart, year) for year in range(start_year, end_year + 1))


def month_contexts(start: datetime, end: datetime) -> tuple[MonthContext, ...]:
    """返回 ``[start, end)`` 区间内由「节」开启的每个流月。"""
    left = as_instant(start)
    right = as_instant(end)
    if left >= right:
        raise ValueError("start 必须早于 end。")
    terms = jie_terms_in(range(left.year - 1, right.year + 2))
    result: list[MonthContext] = []
    for index, term in enumerate(terms):
        if not left <= term.moment < right:
            continue
        stem, branch = month_pillar(term.moment)
        result.append(
            MonthContext(
                jie_name=term.name,
                start=term.moment,
                end=terms[index + 1].moment,
                heavenly_stem=stem,
                earthly_branch=branch,
                ganzhi_year=ganzhi_year(term.moment),
            )
        )
    return tuple(result)


def flow_months(year: int) -> tuple[MonthContext, ...]:
    """返回以 ``year`` 年立春起、次年立春止的十二个流月。"""
    return month_contexts(lichun_moment(year), lichun_moment(year + 1))

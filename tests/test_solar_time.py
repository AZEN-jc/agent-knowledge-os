"""真太阳时换算的测试。

**为什么这些测试现在才出现。** ``_solar_time_datetime`` 此前**零覆盖** ——
全仓搜 ``solar_time`` / ``longitude`` / ``真太阳`` 在 tests/ 下无一条命中。
而 Phase 2 给 ``utcoffset()`` 加了可空分支，那是本阶段唯一的新增运行行为，
没有测试盯着的话，下一次有人重构这里就会把它悄悄改回 AttributeError。

**验证口径**：不拿「跑出来的值」当预期，而是用可手算的算术关系 ——
经度每偏 1° 差正好 4 分钟，位于标准经线时只剩均时差。这两条都能在纸上验，
不依赖本文件以外的任何实现。

**一个差点写错的假设**：第一版测试拿 1990-06-15 当「北京 UTC+8」的样本，
结果差了一小时。原因不是代码错，是**中国 1986–1991 年实行夏令时**，
那一天的 Asia/Shanghai 实际是 UTC+9。所以标准经线是 135°E 而不是 120°E。
下面的测试全部改用无夏令时的年份，并单独留一条把夏令时行为钉住。
"""

from datetime import datetime, timedelta, tzinfo

import pytest

from engines.bazi.models import BirthInput
from engines.bazi.sxtwl_provider import (
    _equation_of_time_minutes,
    _solar_time_datetime,
)

#: 无夏令时的取样日。选 2020-06-15：Asia/Shanghai 恒为 UTC+8，
#: 标准经线 120°E，便于纸上验算。
SAMPLE = (2020, 6, 15, 12, 0)

#: 北京时间（UTC+8）的标准经线是 120°E。
CN_STANDARD_MERIDIAN = 120.0


def birth_at(longitude: float, timezone: str = "Asia/Shanghai", when=SAMPLE) -> BirthInput:
    year, month, day, hour, minute = when
    return BirthInput(
        year=year, month=month, day=day, hour=hour, minute=minute,
        longitude=longitude, timezone=timezone,
    )


def local_naive(result: datetime) -> datetime:
    """与 result 同时区的民用时间，用于算墙钟差。"""
    return datetime(*(SAMPLE[:4]), tzinfo=result.tzinfo)


# ── 正常路径：与可手算的算术一致 ───────────────────────────────────────


def test_on_the_standard_meridian_only_the_equation_of_time_applies():
    """位于标准经线时，经度校正为 0，只剩均时差。

    这是整条链路上唯一能「纸上验算」的锚点：120°E 对 UTC+8 的标准经线，
    校正量必须恰好等于均时差，而不是任何别的组合。
    """
    result = _solar_time_datetime(birth_at(CN_STANDARD_MERIDIAN))

    local = local_naive(result)
    correction = result - local
    expected = timedelta(minutes=_equation_of_time_minutes(local.timetuple().tm_yday))

    assert correction == expected
    # 均时差的物理上限约 ±17 分钟；超出说明公式或符号错了。
    assert abs(correction) <= timedelta(minutes=17)


def test_one_degree_east_adds_exactly_four_minutes():
    """偏东 1° 早过中天 4 分钟，真太阳时应比钟表快 4 分钟。"""
    on_meridian = _solar_time_datetime(birth_at(CN_STANDARD_MERIDIAN))
    east = _solar_time_datetime(birth_at(CN_STANDARD_MERIDIAN + 1))

    assert east - on_meridian == timedelta(minutes=4)


def test_one_degree_west_subtracts_exactly_four_minutes():
    """对称性：偏西 1° 必须正好慢 4 分钟，不能只测一边。"""
    on_meridian = _solar_time_datetime(birth_at(CN_STANDARD_MERIDIAN))
    west = _solar_time_datetime(birth_at(CN_STANDARD_MERIDIAN - 1))

    assert on_meridian - west == timedelta(minutes=4)


def test_the_standard_meridian_follows_the_actual_utc_offset():
    """标准经线由时区的**实际** UTC 偏移算出，不写死 120°E。

    中国 1986–1991 年实行夏令时：1990-06-15 的 Asia/Shanghai 是 UTC+9，
    于是标准经线是 135°E。把 120°E 当标准经线的实现会在这类日期上
    整体偏一小时，而这个错误不抛异常、只是数字偏。
    """
    dst_birth = birth_at(120.0, when=(1990, 6, 15, 12, 0))
    result = _solar_time_datetime(dst_birth)
    local = datetime(1990, 6, 15, 12, 0, tzinfo=result.tzinfo)

    # 120°E 相对 135°E 偏西 15°，正好 −60 分钟，再加均时差。
    expected = timedelta(minutes=-60 + _equation_of_time_minutes(166))  # 6/15 是第 166 天
    assert result - local == expected


def test_a_non_utc_offset_timezone_uses_its_own_meridian():
    """东五区（UTC+5）标准经线是 75°E，不是 120°E。"""
    birth = birth_at(75.0, timezone="Asia/Karachi")  # UTC+5，无夏令时
    result = _solar_time_datetime(birth)
    local = datetime(2020, 6, 15, 12, 0, tzinfo=result.tzinfo)

    assert result - local == timedelta(
        minutes=_equation_of_time_minutes(local.timetuple().tm_yday)
    )


# ── 错误路径 ───────────────────────────────────────────────────────────


def test_missing_longitude_is_rejected_with_a_readable_reason():
    """缺 longitude 必须报「开启真太阳时必须提供 longitude」。

    这是既有行为，此前没测 —— 没有测试钉住，下一个人重构时把它改成
    静默按 0° 算也不会有人发现。
    """
    birth = BirthInput(year=1990, month=6, day=15, hour=12)  # longitude=None

    with pytest.raises(ValueError, match="longitude"):
        _solar_time_datetime(birth)


class _NoOffsetTZ(tzinfo):
    """一个构造成功但给不出 UTC 偏移的时区。

    ZoneInfo 不会产生这种对象（键无效时 BirthInput 就早失败了），
    但 ``datetime.utcoffset()`` 的签名允许它，所以代码必须防。
    """

    def utcoffset(self, dt):
        return None

    def tzname(self, dt):
        return "NOOFFSET"

    def dst(self, dt):
        return None


def test_a_timezone_without_an_offset_gets_a_readable_error(monkeypatch):
    """拿不出 UTC 偏移时报 ValueError，不是 AttributeError。

    加这个分支之前，这里是 ``'NoneType' object has no attribute
    'total_seconds'`` —— 一条读完还不知道该改哪里的报错。
    """
    monkeypatch.setattr(
        "engines.bazi.sxtwl_provider.ZoneInfo", lambda key: _NoOffsetTZ()
    )

    with pytest.raises(ValueError, match="UTC 偏移"):
        _solar_time_datetime(birth_at(CN_STANDARD_MERIDIAN))

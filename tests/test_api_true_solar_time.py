"""Phase 5.2：真太阳时从 API 到 provider 的贯通。

引擎的 ``SxtwlBaziProvider(use_true_solar_time=True)`` 自 Phase 3 起就支持
真太阳时校正，但 API 层一直没有暴露这个开关 —— 用户在界面上填了经纬度
也没有用。本文件钉住四件事：

1. 开关存在且**默认关闭** —— 默认行为不变是硬约束，老请求的结果一个字节
   都不能变；
2. 开启时缺经度必须被拒绝，且拒绝发生在请求模型层（中文可读，不是排盘深处
   的英文 ValueError）；
3. 开启后结果真的走真太阳时 —— 时柱会变，不是收下 flag 然后假装；
4. 口径必须可复现 —— 算法版本号带 ``+tst`` 后缀，两个版本号不同的命盘
   不允许被当成同一口径的结果。

真太阳时的参照点：上海（东经 121.5°，时区 Asia/Shanghai）民用时 23:50
真太阳时约晚 7 分钟，仍在子时；乌鲁木齐（东经 87.6°，同样挂
Asia/Shanghai）民用时 23:50 的真太阳时约 21:28，落在亥时 —— 时柱跨了。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.server import app
from engines.bazi import BirthInput, SxtwlBaziProvider
from runtime.mingli_service import MingLiService

client = TestClient(app)

#: 西端城市：民用时与真太阳时差约 142 分钟，跨时柱。
URUMQI = {"longitude": 87.6, "latitude": 43.8, "timezone": "Asia/Shanghai"}
#: 23:50 民用时 —— 差一分钟就进次日，边界附近的输入才睡得踏实。
LATE_EVENING = {"year": 1990, "month": 2, "day": 1, "hour": 23, "minute": 50}


def _chart_payload(**overrides: object) -> dict[str, object]:
    return {**LATE_EVENING, **URUMQI, **overrides}


def _hour_pillar(chart: dict[str, object]) -> str:
    pillars = chart["pillars"]
    assert isinstance(pillars, list)
    hour = pillars[3]
    assert isinstance(hour, dict)
    return f"{hour['heavenly_stem']}{hour['earthly_branch']}"


# ── 1. 默认关闭 ───────────────────────────────────────────────────────


def test_default_request_does_not_use_true_solar_time():
    response = client.post("/api/chart", json=_chart_payload())

    assert response.status_code == 200
    chart = response.json()
    assert chart["algorithm_version"] == "sxtwl-2.0.7-bazi-v2"
    # 民用时 23:50 在乌鲁木齐也按子时算 —— 默认口径不收经纬度影响。
    assert _hour_pillar(chart) == "壬子"


def test_omitted_flag_and_explicit_false_agree():
    omitted = client.post("/api/chart", json=_chart_payload())
    explicit = client.post("/api/chart", json=_chart_payload(true_solar_time=False))

    assert omitted.status_code == explicit.status_code == 200
    assert omitted.json() == explicit.json()


# ── 2. 开启时缺经度必须拒绝 ────────────────────────────────────────────


def test_true_solar_time_without_longitude_is_rejected_with_a_chinese_reason():
    payload = {k: v for k, v in _chart_payload().items() if k != "longitude"}
    response = client.post("/api/chart", json={**payload, "true_solar_time": True})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "经度" in detail
    # 拒绝必须来自请求模型层：消息是中文，且不经过引擎。
    assert "排盘失败" not in detail


def test_true_solar_time_without_longitude_is_rejected_on_every_endpoint():
    payload = {k: v for k, v in _chart_payload().items() if k != "longitude"}
    payload["true_solar_time"] = True

    cases = [
        ("/api/chart", {}),
        ("/api/analyze", {"question": "事业如何？"}),
        ("/api/analyze/multi", {"topics": ["事业"]}),
        ("/api/timeline", {"start_year": 2024, "end_year": 2030}),
    ]
    for path, extra in cases:
        response = client.post(path, json={**payload, **extra})
        assert response.status_code == 422, f"{path} 应拒绝缺经度的真太阳时请求"
        assert "经度" in response.json()["detail"], path


# ── 3. 开启后真的走真太阳时 ────────────────────────────────────────────


def test_true_solar_time_moves_the_hour_pillar_in_the_far_west():
    civil = client.post("/api/chart", json=_chart_payload())
    solar = client.post("/api/chart", json=_chart_payload(true_solar_time=True))

    assert civil.status_code == solar.status_code == 200
    civil_chart, solar_chart = civil.json(), solar.json()
    # 23:50 民用时按子时；真太阳时约 21:28，落在亥时。
    assert _hour_pillar(civil_chart) == "壬子"
    assert _hour_pillar(solar_chart) != _hour_pillar(civil_chart)
    # 日期没跨：变的只有时柱，前三柱不动。
    assert solar_chart["pillars"][:3] == civil_chart["pillars"][:3]


def test_true_solar_time_result_carries_the_tst_version_suffix():
    response = client.post("/api/chart", json=_chart_payload(true_solar_time=True))

    assert response.status_code == 200
    assert response.json()["algorithm_version"].endswith("+tst")


def test_true_solar_time_flag_reaches_multi_analysis():
    response = client.post(
        "/api/analyze/multi",
        json=_chart_payload(true_solar_time=True, topics=["事业", "财运"]),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["succeeded"] == 2
    assert payload["chart"]["algorithm_version"].endswith("+tst")
    assert _hour_pillar(payload["chart"]) != "壬子"


def test_true_solar_time_flag_reaches_timeline():
    """时间轴也排盘，flag 必须贯通到那条路径。

    直接观察点是「不报错」：flag 若漏进引擎的 ``BirthInput``，会以
    TypeError 变成 422「排盘失败」—— 那是把配置错误伪装成数据错误。
    """
    response = client.post(
        "/api/timeline",
        json=_chart_payload(true_solar_time=True, start_year=2024, end_year=2026),
    )

    assert response.status_code == 200
    assert response.json()["total"] == 3


# ── 4. 服务层：flag 不漏进 BirthInput ─────────────────────────────────


def test_service_keeps_the_flag_out_of_birth_input():
    service = MingLiService()

    civil = service.analyze(dict(LATE_EVENING, **URUMQI), "事业")
    solar = service.analyze(dict(LATE_EVENING, **URUMQI), "事业", true_solar_time=True)

    assert civil.chart["algorithm_version"] == "sxtwl-2.0.7-bazi-v2"
    assert solar.chart["algorithm_version"].endswith("+tst")
    assert _hour_pillar(solar.chart) != _hour_pillar(civil.chart)


def test_service_flag_does_not_leak_into_the_birth_record():
    """``chart.birth`` 是引擎的出生信息；排盘口径开关不属于它。"""
    service = MingLiService()
    payload = service.analyze(dict(LATE_EVENING, **URUMQI), "事业", true_solar_time=True)

    assert "true_solar_time" not in payload.chart["birth"]
    assert payload.chart["birth"]["longitude"] == 87.6


# ── 5. 引擎层：版本后缀（Phase 3 的 provider，Phase 5.2 补后缀）─────────


def test_provider_records_true_solar_time_in_its_version():
    civil = SxtwlBaziProvider()
    solar = SxtwlBaziProvider(use_true_solar_time=True)

    birth = BirthInput(1990, 2, 1, 23, 50, longitude=87.6, latitude=43.8)
    assert civil.calculate(birth).algorithm_version == "sxtwl-2.0.7-bazi-v2"
    assert solar.calculate(birth).algorithm_version == "sxtwl-2.0.7-bazi-v2+tst"


def test_provider_stacks_both_non_default_options_in_its_version():
    """两个非默认口径叠加时，版本号必须同时带两者，不能互相覆盖。"""
    provider = SxtwlBaziProvider(use_true_solar_time=True, late_zi_policy="roll")

    birth = BirthInput(1990, 2, 1, 23, 50, longitude=87.6, latitude=43.8)
    assert provider.calculate(birth).algorithm_version == "sxtwl-2.0.7-bazi-v2+roll+tst"

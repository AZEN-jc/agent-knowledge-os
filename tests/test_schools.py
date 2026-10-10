"""Phase 2：流派注册表测试。

流派不是注释里的一个词，而是有取值域的实体。这一组测试要证明：拼错的流派
活不下来，新流派可以加进来，而且没有公版典籍的流派会被明确标出来。
"""

import pytest

from knowledge.default_rules import build_registry, default_registry, default_schools
from knowledge.rules import Rule
from knowledge.schools import STRUCTURAL_SCHOOL, School, SchoolRegistry, default_school_registry


def school(**overrides) -> School:
    values: dict[str, object] = {
        "id": "test_school",
        "name": "测试流派",
        "method": "测试方法",
    }
    values.update(overrides)
    return School(**values)  # type: ignore[arg-type]


def test_school_requires_id_name_and_method():
    with pytest.raises(ValueError, match="必须有 id"):
        school(id=" ")
    with pytest.raises(ValueError, match="中文名"):
        school(name="")
    with pytest.raises(ValueError, match="核心方法"):
        school(method="")


def test_registry_rejects_duplicate_school_id():
    registry = SchoolRegistry()
    registry.register(school())

    with pytest.raises(ValueError, match="已存在"):
        registry.register(school(name="另一个"))


def test_require_reports_unknown_school_with_the_registered_list():
    registry = default_school_registry()

    with pytest.raises(ValueError, match="未注册的流派") as excinfo:
        registry.require("zi_ping_structrual")  # 故意拼错

    assert STRUCTURAL_SCHOOL in str(excinfo.value)


def test_registry_is_extensible():
    registry = default_school_registry()
    registry.register(school(id="new_school"))

    assert registry.has("new_school") is True
    assert "new_school" in {item.id for item in registry.select()}


def test_default_schools_are_unique_and_include_the_structural_layer():
    ids = [item.id for item in default_schools().select()]

    assert len(ids) == len(set(ids))
    assert STRUCTURAL_SCHOOL in ids


def test_every_default_rule_belongs_to_a_registered_school():
    schools = default_schools()

    for rule in default_registry().select():
        assert schools.has(rule.school), f"{rule.id} 挂在未注册流派 {rule.school} 上"


def test_rule_on_unknown_school_is_rejected_during_assembly():
    schools = SchoolRegistry()  # 空注册表
    schools.register(school(id="only_this_one"))

    with pytest.raises(ValueError, match="未注册的流派"):
        build_registry(schools=schools)


def test_schools_without_public_domain_classics_are_flagged():
    """没有公版典籍的流派必须留白并写明原因，不能默默挂上规则。

    盲派与象法新派都属此类。它们的 ``classics`` 必须为空，且 ``note`` 要
    说清为什么 —— 否则后人会以为「只是还没录」，而不是「不能录」。
    """
    schools = default_schools()

    for school_id in ("mang_pai", "xiang_fa"):
        item = schools.get(school_id)
        assert item.classics == ()
        assert item.note.strip(), f"{school_id} 必须说明为何没有典籍"

    assert all(
        rule.school != "mang_pai" for rule in default_registry().select()
    ), "盲派无公版文本，当前不应挂任何规则"


def test_school_records_divergence_points_for_interpretive_schools():
    schools = default_schools()

    for school_id in ("zi_ping_orthodox", "di_tian_sui"):
        assert schools.get(school_id).divergences, f"{school_id} 应记录已知分歧点"

    assert schools.get(STRUCTURAL_SCHOOL).divergences == ()


def test_school_to_dict_is_serialisable():
    payload = default_schools().get("di_tian_sui").to_dict()

    assert payload["name"] == "滴天髓派"
    assert payload["classics"] == ["《滴天髓》"]
    assert isinstance(payload["divergences"], list)


def test_rule_model_accepts_a_newly_registered_school():
    """新增流派后规则立刻可用，不需要改任何枚举。"""
    registry = SchoolRegistry()
    registry.register(school(id="brand_new"))
    rule = Rule(
        id="R1",
        source="测试来源",
        school="brand_new",
        category="test",
        condition={"x": 1},
        conclusion="测试结论",
    )

    registry.require(rule.school)
    assert rule.school == "brand_new"

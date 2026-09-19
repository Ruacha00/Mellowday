"""F 项网页层测试：技能规则正文的查看、编辑保存与历史正文。

只挂载 mellowday.web_app.skills_api.router（不经过 create_app），用
httpx.ASGITransport 直接打接口：

    GET  /api/skills/{name}
    PUT  /api/skills/{name}
    GET  /api/skills/{name}/versions/{version}

重点：中文技能名可用；保存真的换了正文并生成新版本；没有变化时不升版本；
空正文与已停用技能被拒绝而不是 500；历史正文可回看，回退仍然可用。

全部离线：技能建在隔离的 MELLOWDAY_DATA_DIR 下，不发网络请求。
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from fastapi import FastAPI

from mellowday.runtime.skills import create_skill_file, get_skill_by_name, reset_skill_cache
from mellowday.web_app import skills_api

NAME = "每周回顾"
DESC = "梳理本周完成与未完成的待办，生成本周总结与下周计划"
WHEN = "当用户要求做每周回顾、周总结或复盘本周安排时使用"
RULE_A = "先列已完成"
RULE_B = "再列未完成"
BODY = f"# 步骤\n\n1. {RULE_A}\n2. {RULE_B}"


@pytest.fixture(autouse=True)
def _isolated_skill_cache():
    reset_skill_cache()
    yield
    reset_skill_cache()


@pytest.fixture
def skill_path(isolated_data_dir: Path) -> Path:
    result = create_skill_file(name=NAME, description=DESC, instructions=BODY, when_to_use=WHEN)
    assert result["ok"] is True, result
    reset_skill_cache()
    return Path(result["file"])


def make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(skills_api.router)
    return app


def api() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app()), base_url="http://mellowday.test")


def url(*parts: str) -> str:
    return "/api/skills" + "".join("/" + quote(str(part), safe="") for part in parts)


# ------------------------------------------------------------------ 路由契约


def test_router_exposes_the_new_paths() -> None:
    registered = {
        (route.path, method)
        for route in make_app().routes
        for method in getattr(route, "methods", set()) or set()
    }
    assert ("/api/skills/{name}", "GET") in registered
    assert ("/api/skills/{name}", "PUT") in registered
    assert ("/api/skills/{name}/versions/{version}", "GET") in registered
    # 既有路径不能被动过。
    for path, method in (
        ("/api/skills", "GET"),
        ("/api/skills/{name}/disable", "POST"),
        ("/api/skills/{name}/enable", "POST"),
        ("/api/skills/{name}/versions", "GET"),
        ("/api/skills/{name}/versions/{version}/restore", "POST"),
    ):
        assert (path, method) in registered, (path, method)


# ---------------------------------------------------------------- 查看当前正文


@pytest.mark.anyio
async def test_detail_endpoint_returns_the_current_rules(skill_path: Path, isolated_data_dir: Path) -> None:
    async with api() as client:
        response = await client.get(url(NAME))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["name"] == NAME
    assert payload["version"] == "0.1.0"
    assert payload["enabled"] is True
    assert RULE_A in payload["body"] and RULE_B in payload["body"]
    assert payload["notes"] == ""
    assert Path(payload["path"]) == skill_path


@pytest.mark.anyio
async def test_detail_endpoint_404_and_400(skill_path: Path, isolated_data_dir: Path) -> None:
    async with api() as client:
        missing = await client.get(url("不存在的技能"))
        blank = await client.get(url(" "))

    assert missing.status_code == 404, missing.text
    assert missing.json()["detail"]
    assert blank.status_code == 400, blank.text


@pytest.mark.anyio
async def test_detail_endpoint_works_while_disabled(skill_path: Path, isolated_data_dir: Path) -> None:
    async with api() as client:
        assert (await client.post(url(NAME, "disable"))).status_code == 200
        response = await client.get(url(NAME))
        assert response.status_code == 200, response.text
        assert response.json()["enabled"] is False
        assert RULE_A in response.json()["body"]
        assert (await client.post(url(NAME, "enable"))).status_code == 200


# ------------------------------------------------------------------ 编辑保存


@pytest.mark.anyio
async def test_put_endpoint_saves_rules_and_creates_a_new_version(
    skill_path: Path, isolated_data_dir: Path
) -> None:
    edited = f"# 步骤\n\n1. {RULE_A}\n2. 标注负责人\n3. {RULE_B}"

    async with api() as client:
        response = await client.put(url(NAME), json={"instructions": edited, "note": "手工编辑"})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["ok"] is True
        assert payload["changed"] is True
        assert payload["previous_version"] == "0.1.0"
        assert payload["version"] == "0.1.1"

        detail = (await client.get(url(NAME))).json()
        assert "标注负责人" in detail["body"]
        assert detail["version"] == "0.1.1"

        # 编辑前的正文仍然可回看，而且回退仍然可用。
        old = await client.get(url(NAME, "versions", "0.1.0"))
        assert old.status_code == 200, old.text
        assert old.json()["current"] is False
        assert RULE_A in old.json()["body"] and "标注负责人" not in old.json()["body"]

        restored = await client.post(url(NAME, "versions", "0.1.0", "restore"))
        assert restored.status_code == 200, restored.text
        assert restored.json()["restored_from"] == "0.1.0"

        after = (await client.get(url(NAME))).json()
        assert "标注负责人" not in after["body"]

    # 运行时的加载路径也拿到了新正文（新会话生效）。
    loaded = get_skill_by_name(NAME)
    assert loaded is not None and "标注负责人" not in (loaded.prompt_template or "")


@pytest.mark.anyio
async def test_put_endpoint_without_changes_does_not_bump_the_version(
    skill_path: Path, isolated_data_dir: Path
) -> None:
    async with api() as client:
        response = await client.put(url(NAME), json={"instructions": BODY, "description": DESC})

    assert response.status_code == 200, response.text
    assert response.json()["changed"] is False
    assert response.json()["version"] == "0.1.0"


@pytest.mark.anyio
async def test_put_endpoint_rejects_an_empty_rule_body(skill_path: Path, isolated_data_dir: Path) -> None:
    before = skill_path.read_text(encoding="utf-8")

    async with api() as client:
        response = await client.put(url(NAME), json={"instructions": "   "})

    assert response.status_code == 400, response.text
    assert "empty" in response.json()["detail"]
    assert skill_path.read_text(encoding="utf-8") == before


@pytest.mark.anyio
async def test_put_endpoint_refuses_a_disabled_skill(skill_path: Path, isolated_data_dir: Path) -> None:
    async with api() as client:
        assert (await client.post(url(NAME, "disable"))).status_code == 200
        response = await client.put(url(NAME), json={"instructions": "# 新规则"})

    assert response.status_code == 400, response.text
    assert "disabled" in response.json()["detail"]


@pytest.mark.anyio
async def test_put_endpoint_404_for_unknown_skill(isolated_data_dir: Path) -> None:
    async with api() as client:
        response = await client.put(url("不存在的技能"), json={"instructions": "# 新规则"})
    assert response.status_code == 404, response.text


@pytest.mark.anyio
async def test_put_endpoint_ignores_unknown_payload_keys(skill_path: Path, isolated_data_dir: Path) -> None:
    """多余字段不能变成 500：接口只认自己声明的几个键。"""
    async with api() as client:
        response = await client.put(url(NAME), json={"instructions": BODY, "surprise": 1})

    assert response.status_code == 200, response.text
    assert response.json()["changed"] is False


# ------------------------------------------------------------------ 历史正文


@pytest.mark.anyio
async def test_version_content_endpoint_reads_current_and_history(
    skill_path: Path, isolated_data_dir: Path
) -> None:
    async with api() as client:
        assert (
            await client.put(url(NAME), json={"instructions": f"# 步骤\n\n1. {RULE_A}\n2. 标注负责人"})
        ).status_code == 200

        current = await client.get(url(NAME, "versions", "0.1.1"))
        history = await client.get(url(NAME, "versions", "0.1.0"))

    assert current.status_code == 200, current.text
    assert current.json()["current"] is True
    assert "标注负责人" in current.json()["body"]

    assert history.status_code == 200, history.text
    assert history.json()["current"] is False
    assert history.json()["body"].count(RULE_B) == 1
    assert "标注负责人" not in history.json()["body"]


@pytest.mark.anyio
async def test_version_content_endpoint_404_and_400(skill_path: Path, isolated_data_dir: Path) -> None:
    async with api() as client:
        unknown_version = await client.get(url(NAME, "versions", "9.9.9"))
        unknown_skill = await client.get(url("不存在的技能", "versions", "0.1.0"))
        blank_version = await client.get(url(NAME, "versions", " "))

    assert unknown_version.status_code == 404, unknown_version.text
    assert unknown_skill.status_code == 404, unknown_skill.text
    assert blank_version.status_code == 400, blank_version.text

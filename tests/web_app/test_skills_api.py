"""I24a 网页层测试：技能管理接口。

只挂载 mellowday.web_app.skills_api.router（不经过 create_app），用
httpx.ASGITransport 直接打接口：

    GET  /api/skills
    POST /api/skills/{name}/disable
    POST /api/skills/{name}/enable
    GET  /api/skills/{name}/versions
    POST /api/skills/{name}/versions/{version}/restore

重点：中文技能名可用；停用后运行时的发现/检索入口不再返回该技能；恢复后重新出现；
版本回退真的换了内容；未知技能与未知版本给 404、非法名字给 400，绝不 500。

全部离线：技能建在隔离的 MELLOWDAY_DATA_DIR 下，不发网络请求。
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from fastapi import FastAPI

from mellowday import paths
from mellowday.runtime.skills import (
    create_skill_file,
    discover_skills,
    evolve_skill_file,
    get_skill_by_name,
    parse_frontmatter,
    reset_skill_cache,
    retrieve_relevant_skills,
)
from mellowday.web_app import skills_api

NAME_A = "每周回顾"
NAME_B = "会议纪要整理"
DESC_A = "梳理本周完成与未完成的待办，生成本周总结与下周计划"
DESC_B = "把会议记录整理成决议摘要与待办清单"
BODY_A = "# 步骤\n\n1. 先列已完成\n2. 再列未完成"
QUERY_A = "帮我做每周回顾和周总结"
REQUIRED_KEYS = {"name", "description", "version", "enabled", "source", "path"}


@pytest.fixture(autouse=True)
def _isolated_skill_cache():
    reset_skill_cache()
    yield
    reset_skill_cache()


@pytest.fixture
def api_fixture_paths(isolated_data_dir: Path) -> dict[str, Path]:
    created: dict[str, Path] = {}
    for name, description, body in (
        (NAME_A, DESC_A, BODY_A),
        (NAME_B, DESC_B, "# 步骤\n\n1. 提取决议\n2. 输出待办"),
    ):
        result = create_skill_file(name=name, description=description, instructions=body)
        assert result["ok"] is True, result
        created[name] = Path(result["file"])
    reset_skill_cache()
    return created


def make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(skills_api.router)
    return app


def api() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=make_app()), base_url="http://mellowday.test")


def url(*parts: str) -> str:
    return "/api/skills" + "".join("/" + quote(str(part), safe="") for part in parts)


def _hit_names(query: str) -> list[str]:
    return [str(hit.get("name")) for hit in retrieve_relevant_skills(query, limit=5)]


# ------------------------------------------------------------- 路由契约


def test_router_exposes_the_contracted_paths() -> None:
    registered = {
        (route.path, method)
        for route in make_app().routes
        for method in getattr(route, "methods", set()) or set()
    }
    assert ("/api/skills", "GET") in registered
    assert ("/api/skills/{name}/disable", "POST") in registered
    assert ("/api/skills/{name}/enable", "POST") in registered
    assert ("/api/skills/{name}/versions", "GET") in registered
    assert ("/api/skills/{name}/versions/{version}/restore", "POST") in registered


# ------------------------------------------------------------------ 查看


@pytest.mark.anyio
async def test_list_skills_endpoint(api_fixture_paths, isolated_data_dir: Path) -> None:
    async with api() as client:
        response = await client.get("/api/skills")
    assert response.status_code == 200
    body = response.json()
    assert [entry["name"] for entry in body["skills"]] == sorted([NAME_A, NAME_B])
    for entry in body["skills"]:
        assert REQUIRED_KEYS <= set(entry), entry
        assert entry["version"] == "0.1.0"
        assert entry["enabled"] is True
        assert entry["source"] == "project"
        assert Path(entry["path"]).is_file()
    by_name = {entry["name"]: entry for entry in body["skills"]}
    assert by_name[NAME_A]["description"] == DESC_A


@pytest.mark.anyio
async def test_list_skills_is_empty_without_skills(isolated_data_dir: Path) -> None:
    async with api() as client:
        response = await client.get("/api/skills")
    assert response.status_code == 200
    assert response.json() == {"skills": []}


# ------------------------------------------------------- 停用 / 恢复


@pytest.mark.anyio
async def test_disable_and_enable_endpoints_change_runtime_retrieval(api_fixture_paths, isolated_data_dir: Path) -> None:
    assert NAME_A in _hit_names(QUERY_A)

    async with api() as client:
        disabled = await client.post(url(NAME_A, "disable"))
        assert disabled.status_code == 200, disabled.text
        payload = disabled.json()
        assert payload["ok"] is True
        assert payload["name"] == NAME_A
        assert payload["changed"] is True
        archived_to = Path(payload["archived_to"])
        assert archived_to.parent == paths.skills_archive_dir()
        assert (archived_to / "SKILL.md").is_file()

        # 停用真的影响检索：发现、命中与加载都不再返回该技能。
        assert NAME_A not in {skill.name for skill in discover_skills()}
        assert get_skill_by_name(NAME_A) is None
        assert _hit_names(QUERY_A) == []

        listed = await client.get("/api/skills")
        by_name = {entry["name"]: entry for entry in listed.json()["skills"]}
        assert by_name[NAME_A]["enabled"] is False
        assert by_name[NAME_A]["archived_to"] == str(archived_to)
        assert by_name[NAME_B]["enabled"] is True

        # 重复停用是幂等的：第二次不再移动目录。
        again = await client.post(url(NAME_A, "disable"))
        assert again.status_code == 200
        assert again.json()["changed"] is False
        assert again.json()["archived_to"] == str(archived_to)

        enabled = await client.post(url(NAME_A, "enable"))
        assert enabled.status_code == 200, enabled.text
        assert enabled.json()["changed"] is True
        assert not archived_to.exists()

    # 恢复后重新出现，并且检索又能命中。
    assert NAME_A in {skill.name for skill in discover_skills()}
    assert NAME_A in _hit_names(QUERY_A)
    assert get_skill_by_name(NAME_A) is not None
    async with api() as client:
        listed = await client.get("/api/skills")
    by_name = {entry["name"]: entry for entry in listed.json()["skills"]}
    assert by_name[NAME_A]["enabled"] is True
    assert by_name[NAME_A]["archived_to"] == ""


@pytest.mark.anyio
async def test_chinese_skill_name_round_trips_through_the_api(api_fixture_paths, isolated_data_dir: Path) -> None:
    original = api_fixture_paths[NAME_B].read_text(encoding="utf-8")

    async with api() as client:
        disabled = await client.post(url(NAME_B, "disable"))
        assert disabled.status_code == 200
        assert disabled.json()["name"] == NAME_B
        archived_file = Path(disabled.json()["path"])
        assert archived_file.read_text(encoding="utf-8") == original

        enabled = await client.post(url(NAME_B, "enable"))
        assert enabled.status_code == 200
        assert Path(enabled.json()["path"]).read_text(encoding="utf-8") == original
        assert NAME_B in {entry["name"] for entry in (await client.get("/api/skills")).json()["skills"]}


# ------------------------------------------------------- 版本与版本回退


@pytest.mark.anyio
async def test_versions_and_restore_endpoints(api_fixture_paths, isolated_data_dir: Path) -> None:
    skill_file = api_fixture_paths[NAME_A]
    evolve_skill_file(skill_name=NAME_A, lesson="先给出结论再列细节")
    evolve_skill_file(skill_name=NAME_A, lesson="每周一早上发出提醒")

    async with api() as client:
        listed = await client.get(url(NAME_A, "versions"))
        assert listed.status_code == 200, listed.text
        assert listed.json()["name"] == NAME_A
        versions = listed.json()["versions"]
        assert [item["version"] for item in versions] == ["0.1.2", "0.1.1", "0.1.0"]
        assert versions[0]["current"] is True
        assert all(item["updated_at"] and item["path"] for item in versions)

        restored = await client.post(url(NAME_A, "versions", "0.1.0", "restore"))
        assert restored.status_code == 200, restored.text
        payload = restored.json()
        assert payload["ok"] is True
        assert payload["restored_from"] == "0.1.0"
        assert payload["version"] == "0.1.3"

        after = await client.get(url(NAME_A, "versions"))
        assert after.status_code == 200
        assert [item["version"] for item in after.json()["versions"]] == ["0.1.3", "0.1.2", "0.1.1", "0.1.0"]

    # 内容真的换回了 0.1.0，并且加载路径拿到的是回退后的正文。
    raw = skill_file.read_text(encoding="utf-8")
    parsed = parse_frontmatter(raw)
    assert parsed.meta["version"] == "0.1.3"
    assert parsed.meta["restored-from"] == "0.1.0"
    assert parsed.body == BODY_A
    assert "先给出结论再列细节" not in raw
    skill = get_skill_by_name(NAME_A)
    assert skill is not None and skill.prompt_template == BODY_A


@pytest.mark.anyio
async def test_versions_endpoint_works_while_the_skill_is_disabled(api_fixture_paths, isolated_data_dir: Path) -> None:
    async with api() as client:
        assert (await client.post(url(NAME_A, "disable"))).status_code == 200
        response = await client.get(url(NAME_A, "versions"))
        assert response.status_code == 200
        assert response.json()["versions"][0]["version"] == "0.1.0"

        # 停用状态下拒绝回退，但给出明确状态码而不是 500。
        refused = await client.post(url(NAME_A, "versions", "0.1.0", "restore"))
        assert refused.status_code == 400, refused.text
        assert "disabled" in refused.json()["detail"]

        assert (await client.post(url(NAME_A, "enable"))).status_code == 200


# ------------------------------------------------------------- 非法输入


@pytest.mark.anyio
async def test_unknown_skill_and_version_are_404_not_500(api_fixture_paths, isolated_data_dir: Path) -> None:
    async with api() as client:
        for method, target in (
            ("get", url("不存在的技能", "versions")),
            ("post", url("不存在的技能", "disable")),
            ("post", url("不存在的技能", "enable")),
            ("post", url(NAME_A, "versions", "9.9.9", "restore")),
        ):
            response = await getattr(client, method)(target)
            assert response.status_code == 404, (method, target, response.status_code, response.text)
            assert response.json()["detail"]

        # 未知版本不能改动技能内容。
        raw_before = api_fixture_paths[NAME_A].read_text(encoding="utf-8")
    assert api_fixture_paths[NAME_A].read_text(encoding="utf-8") == raw_before


@pytest.mark.anyio
async def test_invalid_names_and_versions_are_400_not_500(api_fixture_paths, isolated_data_dir: Path) -> None:
    blank = quote(" ")
    async with api() as client:
        for target in (
            f"/api/skills/{blank}/disable",
            f"/api/skills/{blank}/enable",
            url(NAME_A, "versions", " ", "restore"),
        ):
            response = await client.post(target)
            assert response.status_code == 400, (target, response.status_code, response.text)
            assert response.json()["detail"]

        # 非法请求不得改变技能状态。
        listed = await client.get("/api/skills")
        by_name = {entry["name"]: entry for entry in listed.json()["skills"]}
        assert by_name[NAME_A]["enabled"] is True

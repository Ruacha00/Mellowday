"""Skill management endpoints: list, enable/disable and version restore.

Only a router is exported; the application factory includes it, so this module
never builds a FastAPI app of its own.

    GET  /api/skills
    GET  /api/skills/{name}
    PUT  /api/skills/{name}
    POST /api/skills/{name}/disable
    POST /api/skills/{name}/enable
    GET  /api/skills/{name}/versions
    GET  /api/skills/{name}/versions/{version}
    POST /api/skills/{name}/versions/{version}/restore

Status codes follow the runtime contract in
:mod:`mellowday.runtime.skills.skill_management`: an unknown skill or an
unknown version is a 404, every other rejected operation (empty name, disabled
skill, refused write) is a 400. User input never produces a 500.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from mellowday.runtime import skills as skills_runtime

router = APIRouter(prefix="/api/skills", tags=["skills"])

# Failure codes that mean "this skill / version does not exist".
_NOT_FOUND_CODES = {"skill_not_found", "version_not_found"}


def _http_error(result: dict[str, Any]) -> HTTPException:
    code = str(result.get("error_code") or "")
    status = 404 if code in _NOT_FOUND_CODES else 400
    detail = str(result.get("error") or "skill operation failed")
    return HTTPException(status_code=status, detail=detail)


@router.get("")
async def list_skills() -> dict[str, Any]:
    return {"skills": skills_runtime.list_skills()}


@router.post("/{name}/disable")
async def disable_skill(name: str) -> dict[str, Any]:
    result = skills_runtime.disable_skill(name)
    if not result.get("ok"):
        raise _http_error(result)
    return result


@router.post("/{name}/enable")
async def enable_skill(name: str) -> dict[str, Any]:
    result = skills_runtime.enable_skill(name)
    if not result.get("ok"):
        raise _http_error(result)
    return result




@router.get("/{name}")
async def skill_detail(name: str) -> dict[str, Any]:
    """当前规则正文与元信息，供管理页「查看规则」使用。"""
    result = skills_runtime.get_skill_detail(name)
    if not result.get("ok"):
        raise _http_error(result)
    return result


@router.put("/{name}")
async def update_skill(name: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    """保存人工编辑：规则正文完整替换，复用既有版本机制（快照 + 版本 +1）。

    没有实质变化时 changed 为 False，不写文件也不升版本。
    """
    result = skills_runtime.update_skill(
        name,
        description=payload.get("description"),
        when_to_use=payload.get("when_to_use"),
        instructions=payload.get("instructions"),
        note=str(payload.get("note") or ""),
    )
    if not result.get("ok"):
        raise _http_error(result)
    return result


@router.get("/{name}/versions/{version}")
async def skill_version_content(name: str, version: str) -> dict[str, Any]:
    """某个历史版本的规则正文，供管理页「查看历史正文」使用。"""
    result = skills_runtime.get_skill_version_content(name, version)
    if not result.get("ok"):
        raise _http_error(result)
    return result



@router.get("/{name}/versions")
async def list_skill_versions(name: str) -> dict[str, Any]:
    try:
        versions = skills_runtime.list_skill_versions(name)
    except skills_runtime.UnknownSkillError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except skills_runtime.SkillManagementError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"name": name, "versions": versions}


@router.post("/{name}/versions/{version}/restore")
async def restore_skill_version(name: str, version: str) -> dict[str, Any]:
    result = skills_runtime.restore_skill_version(name, version)
    if not result.get("ok"):
        raise _http_error(result)
    return result

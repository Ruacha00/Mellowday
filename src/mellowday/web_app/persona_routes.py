"""Settings endpoints for bounded persona adaptation."""
import sqlite3
from fastapi import APIRouter, Body, HTTPException
from mellowday.personal_assistant import persona_adaptation as adaptation

router = APIRouter(prefix='/api/persona/adaptation', tags=['persona'])


def _call(function, *args):
    try:
        return function(*args)
    except KeyError as exc:
        raise HTTPException(404, '未找到人格习惯') from exc
    except adaptation.AdaptationError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (ValueError, OSError, sqlite3.Error) as exc:
        raise HTTPException(409, '人格适应数据不可读或无法保存；未报告保存成功') from exc


@router.get('')
def read_adaptation():
    return _call(adaptation.snapshot)


@router.put('')
def update_adaptation(payload: dict = Body(...)):
    if set(payload) != {'paused'}:
        raise HTTPException(422, '仅支持 paused 字段')
    return _call(adaptation.set_paused, payload['paused'])


@router.post('/reset')
def reset_adaptation():
    return _call(adaptation.reset)


@router.post('/{rule_id}/lock')
def lock_rule(rule_id: str, payload: dict = Body(...)):
    if set(payload) != {'locked'}:
        raise HTTPException(422, '仅支持 locked 字段')
    return _call(adaptation.set_locked, rule_id, payload['locked'])


@router.post('/{rule_id}/undo')
def undo_rule(rule_id: str):
    return _call(adaptation.undo, rule_id)

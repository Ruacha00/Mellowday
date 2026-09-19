"""Calendar HTTP API, isolated from application construction."""
from fastapi import APIRouter, Body, HTTPException
from mellowday.personal_assistant.schedule import ScheduleService


def create_router(service: ScheduleService) -> APIRouter:
    router = APIRouter(prefix="/api/calendar", tags=["calendar"])

    def call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except KeyError as exc:
            raise HTTPException(404, "记录不存在") from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/events")
    def events(start: str, end: str):
        return {"events": call(service.calendar.events, start, end)}

    @router.get("/events/{event_id}")
    def event(event_id: str):
        return {"event": call(service.calendar.get, event_id)}

    @router.post("/events")
    def create_event(payload: dict = Body(...)):
        return {"event": call(service.calendar.create, payload)}

    @router.put("/events/{event_id}")
    def update_event(event_id: str, payload: dict = Body(...), scope: str = "series", occurrence_start: str | None = None):
        return {"event": call(service.calendar.update, event_id, payload, scope=scope, occurrence_start=occurrence_start)}

    @router.delete("/events/{event_id}")
    def delete_event(event_id: str, scope: str = "series", occurrence_start: str | None = None):
        return {"event": call(service.calendar.delete, event_id, scope=scope, occurrence_start=occurrence_start)}

    @router.get("/subscriptions")
    def subscriptions():
        return {"subscriptions": service.subscriptions()}

    @router.post("/subscriptions")
    def create_subscription(payload: dict = Body(...)):
        return {"subscription": call(service.save_subscription, payload)}

    @router.put("/subscriptions/{subscription_id}")
    def update_subscription(subscription_id: str, payload: dict = Body(...)):
        return {"subscription": call(service.save_subscription, payload, subscription_id)}

    @router.delete("/subscriptions/{subscription_id}")
    def delete_subscription(subscription_id: str):
        call(service.delete_subscription, subscription_id)
        return {"ok": True}

    @router.get("/notifications")
    def notifications(unread_only: bool = False):
        return {"notifications": service.notifications(unread_only=unread_only), "scheduler_error": service.last_error}

    @router.post("/notifications/{notification_id}/read")
    def mark_read(notification_id: str):
        call(service.mark_read, notification_id)
        return {"ok": True}

    return router

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config
from .admin import router as admin_router
from .auth import bootstrap_staff_user
from .db import SessionLocal, init_db
from .services import handle_inbound_sms, membersense_media_root, update_message_status


app = FastAPI(title=config.APP_NAME)
app.mount("/membersense-media", StaticFiles(directory=str(membersense_media_root())), name="membersense-media")
app.include_router(admin_router)


@app.on_event("startup")
def startup() -> None:
    init_db()
    with SessionLocal() as session:
        bootstrap_staff_user(session)


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse("/admin")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"ok": "true", "app": config.APP_NAME}


async def _handle_twilio_inbound(request: Request) -> Response:
    form = await request.form()
    payload = {str(key): str(value) for key, value in form.items()}
    from_phone = payload.get("From") or payload.get("WaId") or ""
    body = payload.get("Body") or ""
    with SessionLocal() as session:
        handle_inbound_sms(session, from_phone=from_phone, body=body, raw_payload=payload)
    return Response(content="", media_type="text/plain")


@app.post("/webhooks/twilio")
async def twilio_inbound(request: Request) -> Response:
    return await _handle_twilio_inbound(request)


@app.post("/webhooks/twilio-status")
async def twilio_status(request: Request) -> JSONResponse:
    form = await request.form()
    payload = {str(key): str(value) for key, value in form.items()}
    provider_sid = payload.get("MessageSid") or payload.get("SmsSid")
    status = payload.get("MessageStatus") or payload.get("SmsStatus")
    with SessionLocal() as session:
        updated = update_message_status(session, provider_sid=provider_sid, status=status, raw_payload=payload)
    return JSONResponse({"ok": True, "updated": updated})

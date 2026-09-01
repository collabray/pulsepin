import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import SessionLocal
from app.models.dispatch import DispatchRequest
from app.models.user import User, UserRole
from app.services.ws_hub import dispatcher_hub

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/dispatcher/{hospital_id}")
async def dispatcher_ws(websocket: WebSocket, hospital_id: str, token: str = Query(...)):
    db: Session = SessionLocal()
    try:
        try:
            payload = decode_token(token)
        except jwt.PyJWTError:
            await websocket.close(code=4401)
            return

        user = db.get(User, payload.get("sub"))
        if (
            user is None
            or user.role not in (UserRole.DISPATCHER, UserRole.HOSPITAL_ADMIN, UserRole.PLATFORM_ADMIN)
            or (user.role != UserRole.PLATFORM_ADMIN and str(user.hospital_id) != hospital_id)
        ):
            await websocket.close(code=4403)
            return
    finally:
        db.close()

    await dispatcher_hub.connect(hospital_id, websocket)
    try:
        while True:
            # Dashboard is push-only from the server's perspective; we still
            # need to await something to detect disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await dispatcher_hub.disconnect(hospital_id, websocket)


@router.websocket("/ws/patient/{dispatch_id}")
async def patient_tracking_ws(websocket: WebSocket, dispatch_id: str, token: str = Query(...)):
    """
    Live, Uber-style ambulance tracking channel for the patient app.
    Authenticated to the specific patient who owns this dispatch request
    only — nobody else can watch someone else's ambulance approach.
    """
    db: Session = SessionLocal()
    try:
        try:
            payload = decode_token(token)
        except jwt.PyJWTError:
            await websocket.close(code=4401)
            return

        user = db.get(User, payload.get("sub"))
        if user is None:
            await websocket.close(code=4401)
            return

        dispatch = db.get(DispatchRequest, dispatch_id)
        if dispatch is None or str(dispatch.patient_id) != str(user.id):
            await websocket.close(code=4403)
            return
    finally:
        db.close()

    channel = f"patient:{dispatch_id}"
    await dispatcher_hub.connect(channel, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await dispatcher_hub.disconnect(channel, websocket)

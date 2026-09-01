from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.ml.triage_engine import get_triage_engine
from app.models.triage import TriageSession, TriageSessionStatus
from app.models.user import User
from app.schemas.schemas import RankedCondition, TriageAnswerIn, TriageStartIn, TriageStepOut

router = APIRouter(prefix="/triage", tags=["triage"])

# Human-readable question phrasing for a subset of common symptom keys; any
# symptom without an explicit entry falls back to a readable auto-generated
# label so the API never returns raw snake_case to the UI.
SYMPTOM_LABELS: dict[str, str] = {
    "high_fever": "Do you have a high fever?",
    "chills": "Are you experiencing chills?",
    "headache": "Do you have a headache?",
    "vomiting": "Have you been vomiting?",
    "nausea": "Do you feel nauseous?",
    "fatigue": "Are you feeling unusually fatigued?",
    "joint_pain": "Do you have joint pain?",
    "skin_rash": "Do you have a skin rash?",
    "abdominal_pain": "Do you have abdominal pain?",
    "diarrhoea": "Do you have diarrhoea?",
    "chest_pain": "Do you have chest pain?",
    "breathlessness": "Are you having difficulty breathing?",
    "sweating": "Are you sweating more than usual?",
    "yellowish_skin": "Has your skin turned yellowish?",
    "dark_urine": "Is your urine darker than usual?",
}


def _label_for(symptom: str) -> str:
    if symptom in SYMPTOM_LABELS:
        return SYMPTOM_LABELS[symptom]
    return "Do you have " + symptom.replace("_", " ") + "?"


def _to_step_out(session: TriageSession, step, is_complete: bool) -> TriageStepOut:
    return TriageStepOut(
        session_id=session.id,
        ranked_conditions=[RankedCondition(**c) for c in step.ranked_conditions],
        top_condition=step.top_condition,
        top_probability=round(step.top_probability, 4),
        urgency_level=step.urgency.value,
        next_question_symptom=None if is_complete else step.next_question_symptom,
        next_question_label=None if is_complete else (
            _label_for(step.next_question_symptom) if step.next_question_symptom else None
        ),
        is_complete=is_complete,
    )


@router.post("/sessions", response_model=TriageStepOut, status_code=status.HTTP_201_CREATED)
def start_session(
    payload: TriageStartIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    engine = get_triage_engine()
    session = TriageSession(
        user_id=user.id,
        symptom_responses=payload.initial_symptoms,
        question_trace=list(payload.initial_symptoms.keys()),
    )
    db.add(session)
    db.flush()

    step = engine.step(session.symptom_responses, questions_asked=len(session.question_trace))
    _persist_step(session, step)
    db.commit()
    db.refresh(session)

    return _to_step_out(session, step, step.is_confident_enough_to_stop)


@router.post("/sessions/{session_id}/answer", response_model=TriageStepOut)
def answer_question(
    session_id: UUID,
    payload: TriageAnswerIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = db.get(TriageSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Triage session not found.")
    if session.status != TriageSessionStatus.IN_PROGRESS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Session is not in progress.")

    engine = get_triage_engine()
    responses = dict(session.symptom_responses)
    responses[payload.symptom] = payload.value
    session.symptom_responses = responses
    session.question_trace = list(session.question_trace) + [payload.symptom]

    step = engine.step(responses, questions_asked=len(session.question_trace))
    _persist_step(session, step)
    db.commit()
    db.refresh(session)

    return _to_step_out(session, step, step.is_confident_enough_to_stop)


@router.get("/sessions/{session_id}", response_model=TriageStepOut)
def get_session(
    session_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    session = db.get(TriageSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Triage session not found.")

    engine = get_triage_engine()
    step = engine.step(session.symptom_responses, questions_asked=len(session.question_trace))
    is_complete = session.status == TriageSessionStatus.COMPLETED
    return _to_step_out(session, step, is_complete)


def _persist_step(session: TriageSession, step) -> None:
    session.predicted_conditions = step.ranked_conditions
    session.top_condition = step.top_condition
    session.top_probability = step.top_probability
    session.urgency_level = step.urgency
    if step.is_confident_enough_to_stop:
        session.status = TriageSessionStatus.COMPLETED
        session.completed_at = datetime.now(timezone.utc)

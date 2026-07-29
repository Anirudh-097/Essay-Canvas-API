"""FastAPI application for the Essay Learner backend."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError

from . import db
from . import groq
from .auth import (
    SESSION_COOKIE,
    authenticate,
    cookie_secure,
    create_session,
    require_auth,
    session_max_age,
)


PARAGRAPH_TYPES = (
    "introduction",
    "primary argument",
    "counter-argument",
    "conclusion",
)


class Topic(BaseModel):
    id: int
    topic: str
    used: bool
    last_used: datetime | None = None


class TopicList(BaseModel):
    items: list[Topic]
    total: int


class EssayRequest(BaseModel):
    topic_id: int


class EssayResponse(BaseModel):
    topic: Topic
    essay: str


class PracticePrompt(BaseModel):
    topic: Topic
    paragraph_type: str


class EvaluationRequest(BaseModel):
    topic_id: int
    paragraph_type: str
    paragraph: str


class VocabularySuggestion(BaseModel):
    word: str
    synonyms: list[str]
    context: str


class Evaluation(BaseModel):
    score: int = Field(ge=1, le=6)
    grammar: int = Field(ge=1, le=6)
    vocabulary: int = Field(ge=1, le=6)
    structure: int = Field(ge=1, le=6)
    argument_quality: int = Field(ge=1, le=6)
    strengths: list[str]
    weaknesses: list[str]
    suggested_rewrite: str
    better_vocabulary: list[VocabularySuggestion]


class EvaluationResponse(BaseModel):
    topic: Topic
    paragraph_type: str
    evaluation: Evaluation


class ProgressMetric(BaseModel):
    average: float
    latest: int | None = None


class ProgressAttempt(BaseModel):
    id: int
    score: int
    grammar: int
    vocabulary: int
    structure: int
    argument_quality: int
    paragraph_type: str
    created_at: datetime


class ProgressResponse(BaseModel):
    total_attempts: int
    metrics: dict[str, ProgressMetric]
    attempts: list[ProgressAttempt]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256)


app = FastAPI(title="Essay Learner API", version="0.1.0")
# Allow requests from your Next.js frontend running on localhost:3000
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def serialize_topic(row: sqlite3.Row) -> Topic:
    return Topic(
        id=row["id"],
        topic=row["topic"],
        used=bool(row["used"]),
        last_used=row["last_used"],
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/login")
def login(request: LoginRequest, response: Response) -> dict[str, str]:
    if not authenticate(request.username, request.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    response.set_cookie(
        SESSION_COOKIE,
        create_session(request.username),
        max_age=session_max_age(),
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        path="/",
    )
    return {"username": request.username}


@app.post("/auth/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "ok"}


@app.get("/auth/me")
def current_user(username: str = Depends(require_auth)) -> dict[str, str]:
    return {"username": username}


@app.get("/topics", response_model=TopicList)
def list_topics(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    username: str = Depends(require_auth),
) -> TopicList:
    rows = db.get_topics()
    return TopicList(
        items=[serialize_topic(row) for row in rows[offset : offset + limit]],
        total=len(rows),
    )


@app.get("/topics/{topic_id}", response_model=Topic)
def topic_by_id(topic_id: int, username: str = Depends(require_auth)) -> Topic:
    row = db.get_topic(topic_id=topic_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return serialize_topic(row)


@app.get("/topic/today", response_model=Topic)
def topic_today(username: str = Depends(require_auth)) -> Topic:
    row = db.get_or_assign_today()
    if row is None:
        raise HTTPException(status_code=404, detail="No topics have been imported")
    return serialize_topic(row)


def require_topic(topic_id: int) -> Topic:
    row = db.get_topic(topic_id=topic_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return serialize_topic(row)


@app.post("/essay/generate", response_model=EssayResponse)
def generate_essay(request: EssayRequest, username: str = Depends(require_auth)) -> EssayResponse:
    topic = require_topic(request.topic_id)
    try:
        essay = groq.complete("essay.txt", {"topic": topic.topic})
    except groq.GroqError as error:
        status = 503 if "not configured" in str(error) else 502
        raise HTTPException(status_code=status, detail=str(error)) from error
    return EssayResponse(topic=topic, essay=essay)


@app.get("/practice/prompt", response_model=PracticePrompt)
def practice_prompt(
    exclude_topic_id: int | None = Query(None, ge=1),
    username: str = Depends(require_auth),
) -> PracticePrompt:
    row = db.get_random_practice_topic(exclude_topic_id=exclude_topic_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No practice topics have been imported")
    import random

    return PracticePrompt(
        topic=serialize_topic(row), paragraph_type=random.choice(PARAGRAPH_TYPES)
    )


@app.post("/evaluate", response_model=EvaluationResponse)
def evaluate_paragraph(
    request: EvaluationRequest, username: str = Depends(require_auth)
) -> EvaluationResponse:
    if request.paragraph_type not in PARAGRAPH_TYPES:
        raise HTTPException(status_code=422, detail="Unknown paragraph type")
    if not request.paragraph.strip():
        raise HTTPException(status_code=422, detail="Paragraph cannot be empty")
    topic = require_topic(request.topic_id)
    try:
        raw_evaluation = groq.complete_json(
            "evaluate.txt",
            {
                "topic": topic.topic,
                "paragraph_type": request.paragraph_type,
                "paragraph": request.paragraph.strip(),
            },
        )
        evaluation = Evaluation.model_validate_json(raw_evaluation)
    except groq.GroqError as error:
        status = 503 if "not configured" in str(error) else 502
        raise HTTPException(status_code=status, detail=str(error)) from error
    except (ValidationError, ValueError) as error:
        raise HTTPException(status_code=502, detail="Model returned invalid evaluation JSON") from error
    db.save_attempt(
        topic_id=topic.id,
        paragraph_type=request.paragraph_type,
        score=evaluation.score,
        grammar=evaluation.grammar,
        vocabulary=evaluation.vocabulary,
        structure=evaluation.structure,
        argument_quality=evaluation.argument_quality,
    )
    return EvaluationResponse(
        topic=topic, paragraph_type=request.paragraph_type, evaluation=evaluation
    )


@app.get("/progress", response_model=ProgressResponse)
def progress(username: str = Depends(require_auth)) -> ProgressResponse:
    rows = db.get_progress()
    fields = ("grammar", "vocabulary", "structure", "argument_quality")
    metrics = {}
    for field in fields:
        values = [row[field] for row in rows]
        metrics[field] = ProgressMetric(
            average=round(sum(values) / len(values), 2) if values else 0,
            latest=values[-1] if values else None,
        )
    return ProgressResponse(
        total_attempts=len(rows),
        metrics=metrics,
        attempts=[
            ProgressAttempt(
                id=row["id"], score=row["score"], grammar=row["grammar"],
                vocabulary=row["vocabulary"], structure=row["structure"],
                argument_quality=row["argument_quality"],
                paragraph_type=row["paragraph_type"], created_at=row["created_at"],
            )
            for row in rows
        ],
    )

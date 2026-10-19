"""RASD Intelligence API.

The scoring engine is an explainable, deterministic prototype. It is not a
validated predictive model and must not be used as the sole basis for decisions.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator


APP_VERSION = "1.1.0"
MODEL_VERSION = "1.0.0"
PROJECT_DIR = Path(__file__).resolve().parent.parent
DEMO_MODE = os.getenv("RASD_DEMO_MODE", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DB_PATH = Path(
    os.getenv("RASD_DATABASE_PATH", str(PROJECT_DIR / "data" / "rasd.sqlite3"))
).expanduser()


class RiskRequest(BaseModel):
    """Validated input for one supplier disruption assessment."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_default=True,
    )

    supplier_name: str = Field(min_length=2, max_length=120)
    critical_process: str = Field(min_length=2, max_length=200)
    impact_level: Literal["low", "medium", "high"]
    recovery_hours: int = Field(strict=True, ge=0, le=8760)
    required_recovery_hours: int = Field(default=24, strict=True, ge=1, le=8760)
    disruption_likelihood: Literal["low", "medium", "high"] = "medium"
    dependency_level: Literal["low", "medium", "high"] = "medium"
    alternative_supplier_available: bool = Field(default=False, strict=True)
    controls_effectiveness: Literal["weak", "adequate", "strong"] = "adequate"

    @field_validator("supplier_name", "critical_process")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Text cannot be empty.")
        if any(ord(char) < 32 for char in value):
            raise ValueError("Text must not contain control characters.")
        return value


class RiskDimension(BaseModel):
    category: str
    level: str
    score: int | None = None
    score_adjustment: int | None = None


class RiskResult(BaseModel):
    supplier: str
    critical_process: str
    risk_score: int = Field(ge=0, le=100)
    risk_level: Literal["Low", "Medium", "High"]
    impact_score: int
    recovery_score: int
    recovery_hours: int
    required_recovery_hours: int
    risk_factors: list[str]
    risk_dimensions: list[RiskDimension]
    recommendations: list[str]
    recommendation: str
    inherent_risk_score: int
    inherent_risk_level: Literal["Low", "Medium", "High"]
    likelihood_score: int
    dependency_score: int
    adjusted_dependency_score: int
    controls_score: int
    assessment_type: str
    model_version: str
    assessment_id: str
    created_at: datetime


class AssessmentRecord(BaseModel):
    id: str
    created_at: datetime
    input: RiskRequest
    data: RiskResult


class AssessmentPage(BaseModel):
    items: list[AssessmentRecord]
    total: int
    limit: int
    offset: int


class ClearAssessmentsResult(BaseModel):
    deleted: int


class AssessmentSummary(BaseModel):
    total: int
    high_risk: int
    average_score: float | None
    highest_score: int | None


class HealthResult(BaseModel):
    status: Literal["healthy"]
    version: str
    storage: Literal["available", "disabled"]
    demo_mode: bool


@contextmanager
def database_connection():
    """Open a short-lived SQLite connection with safe concurrency defaults."""

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    with database_connection() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS assessments (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                supplier_name TEXT NOT NULL,
                critical_process TEXT NOT NULL,
                risk_score INTEGER NOT NULL DEFAULT 0,
                risk_level TEXT NOT NULL DEFAULT 'Unknown',
                request_json TEXT NOT NULL,
                response_json TEXT NOT NULL
            )
            """
        )
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(assessments)")
        }
        if "risk_score" not in columns:
            connection.execute(
                "ALTER TABLE assessments ADD COLUMN risk_score INTEGER NOT NULL DEFAULT 0"
            )
        if "risk_level" not in columns:
            connection.execute(
                "ALTER TABLE assessments ADD COLUMN risk_level TEXT NOT NULL DEFAULT 'Unknown'"
            )
            legacy_rows = connection.execute(
                "SELECT id, response_json FROM assessments"
            ).fetchall()
            for row in legacy_rows:
                result = json.loads(row["response_json"])
                connection.execute(
                    "UPDATE assessments SET risk_score = ?, risk_level = ? WHERE id = ?",
                    (
                        int(result.get("risk_score", 0)),
                        str(result.get("risk_level", "Unknown")),
                        row["id"],
                    ),
                )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_assessments_created_at "
            "ON assessments(created_at DESC, id DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_assessments_risk_level "
            "ON assessments(risk_level)"
        )


def persist_assessment(
    assessment_id: str,
    created_at: str,
    request: RiskRequest,
    result: dict,
) -> None:
    with database_connection() as connection:
        connection.execute(
            """
            INSERT INTO assessments (
                id, created_at, supplier_name, critical_process,
                risk_score, risk_level, request_json, response_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                assessment_id,
                created_at,
                request.supplier_name,
                request.critical_process,
                result["risk_score"],
                result["risk_level"],
                json.dumps(request.model_dump(mode="json"), ensure_ascii=False),
                json.dumps(result, ensure_ascii=False),
            ),
        )


def list_assessments(limit: int, offset: int) -> tuple[list[dict], int]:
    with database_connection() as connection:
        total = connection.execute(
            "SELECT COUNT(*) AS total FROM assessments"
        ).fetchone()["total"]
        rows = connection.execute(
            """
            SELECT id, created_at, request_json, response_json
            FROM assessments
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()

    items = [
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "input": json.loads(row["request_json"]),
            "data": json.loads(row["response_json"]),
        }
        for row in rows
    ]
    return items, total


def clear_assessments() -> int:
    with database_connection() as connection:
        cursor = connection.execute("DELETE FROM assessments")
        return cursor.rowcount


def get_assessment_summary() -> dict:
    with database_connection() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN risk_level = 'High' THEN 1 ELSE 0 END), 0) AS high_risk,
                   AVG(risk_score) AS average_score,
                   MAX(risk_score) AS highest_score
            FROM assessments
            """
        ).fetchone()
    return {
        "total": row["total"],
        "high_risk": row["high_risk"],
        "average_score": round(row["average_score"], 1)
        if row["average_score"] is not None
        else None,
        "highest_score": row["highest_score"],
    }


IMPACT_SCORES = {"low": 25, "medium": 55, "high": 90}
LIKELIHOOD_SCORES = {"low": 20, "medium": 55, "high": 90}
DEPENDENCY_SCORES = {"low": 20, "medium": 55, "high": 90}
CONTROL_SCORES = {"strong": 20, "adequate": 50, "weak": 90}


def calculate_recovery_score(
    recovery_hours: int,
    required_recovery_hours: int,
) -> int:
    """Return the configured recovery exposure band (0–100)."""

    ratio = recovery_hours / required_recovery_hours
    if ratio <= 1:
        return 15
    if ratio <= 1.5:
        return 35
    if ratio <= 2:
        return 55
    if ratio <= 4:
        return 80
    return 100


def classify_risk(score: int) -> str:
    if score >= 70:
        return "High"
    if score >= 40:
        return "Medium"
    return "Low"


def build_assessment(request: RiskRequest) -> dict:
    """Build a transparent rule-based score and actionable explanation."""

    impact_score = IMPACT_SCORES[request.impact_level]
    likelihood_score = LIKELIHOOD_SCORES[request.disruption_likelihood]
    recovery_score = calculate_recovery_score(
        request.recovery_hours,
        request.required_recovery_hours,
    )
    dependency_score = DEPENDENCY_SCORES[request.dependency_level]
    controls_score = CONTROL_SCORES[request.controls_effectiveness]

    inherent_score = round(
        impact_score * 0.40
        + likelihood_score * 0.30
        + recovery_score * 0.20
        + dependency_score * 0.10
    )
    adjusted_dependency_score = dependency_score
    if request.alternative_supplier_available:
        adjusted_dependency_score = max(0, dependency_score - 25)

    risk_score = round(
        impact_score * 0.35
        + likelihood_score * 0.25
        + recovery_score * 0.20
        + adjusted_dependency_score * 0.10
        + controls_score * 0.10
    )
    risk_score = max(0, min(100, risk_score))
    risk_level = classify_risk(risk_score)

    risk_dimensions = [
        {
            "category": "business_impact",
            "level": request.impact_level,
            "score": impact_score,
        },
        {
            "category": "disruption_likelihood",
            "level": request.disruption_likelihood,
            "score": likelihood_score,
        },
        {
            "category": "recovery_exposure",
            "level": "above_target"
            if request.recovery_hours > request.required_recovery_hours
            else "within_target",
            "score": recovery_score,
        },
        {
            "category": "supplier_dependency",
            "level": request.dependency_level,
            "score": dependency_score,
        },
        {
            "category": "controls_effectiveness",
            "level": request.controls_effectiveness,
            "score": controls_score,
        },
        {
            "category": "alternative_supplier",
            "level": "available"
            if request.alternative_supplier_available
            else "unavailable",
            "score_adjustment": dependency_score - adjusted_dependency_score,
        },
    ]
    risk_factors = [
        f"Business impact: {request.impact_level}",
        f"Disruption likelihood: {request.disruption_likelihood}",
        "Recovery time exceeds the required target"
        if request.recovery_hours > request.required_recovery_hours
        else "Recovery time is within the required target",
        f"Supplier dependency: {request.dependency_level}",
        f"Controls effectiveness: {request.controls_effectiveness}",
        "Alternative supplier available"
        if request.alternative_supplier_available
        else "No alternative supplier available",
    ]

    recommendations = []
    if risk_level == "High":
        recommendations.append(
            "Prioritize risk treatment and review continuity arrangements "
            "with accountable owners."
        )
    elif risk_level == "Medium":
        recommendations.append(
            "Create a documented mitigation plan with owners, deadlines, "
            "and measurable actions."
        )
    else:
        recommendations.append(
            "Maintain existing controls and schedule periodic reassessments."
        )

    if request.recovery_hours > request.required_recovery_hours:
        recommendations.append(
            "Reduce the recovery gap and validate recovery capabilities "
            "through documented tests."
        )
    if not request.alternative_supplier_available:
        recommendations.append(
            "Evaluate alternative suppliers or a tested contingency "
            "arrangement for the critical process."
        )
    if request.controls_effectiveness == "weak":
        recommendations.append(
            "Strengthen preventive and detective controls and verify "
            "their effectiveness with evidence."
        )
    if request.disruption_likelihood == "high":
        recommendations.append(
            "Review disruption scenarios, monitoring indicators, and "
            "incident response procedures."
        )
    if request.dependency_level == "high":
        recommendations.append(
            "Review concentration risk and critical dependencies across "
            "the supplier relationship."
        )

    return {
        "supplier": request.supplier_name,
        "critical_process": request.critical_process,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "impact_score": impact_score,
        "recovery_score": recovery_score,
        "recovery_hours": request.recovery_hours,
        "required_recovery_hours": request.required_recovery_hours,
        "risk_factors": risk_factors,
        "risk_dimensions": risk_dimensions,
        "recommendations": recommendations,
        "recommendation": " ".join(recommendations),
        "inherent_risk_score": inherent_score,
        "inherent_risk_level": classify_risk(inherent_score),
        "likelihood_score": likelihood_score,
        "dependency_score": dependency_score,
        "adjusted_dependency_score": adjusted_dependency_score,
        "controls_score": controls_score,
        "assessment_type": "Preliminary weighted rule-based assessment",
        "model_version": MODEL_VERSION,
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not DEMO_MODE:
        initialize_database()
    yield


app = FastAPI(
    title="RASD Intelligence",
    description=(
        "Enterprise risk assessment and business continuity intelligence. "
        "Scores are preliminary rule-based estimates requiring human review."
    ),
    version=APP_VERSION,
    docs_url=None if DEMO_MODE else "/docs",
    redoc_url=None if DEMO_MODE else "/redoc",
    openapi_url=None if DEMO_MODE else "/openapi.json",
    lifespan=lifespan,
)

cors_origins = (
    []
    if DEMO_MODE
    else [
        origin.strip()
        for origin in os.getenv(
            "RASD_CORS_ORIGINS",
            "http://127.0.0.1:5500,http://localhost:5500",
        ).split(",")
        if origin.strip()
    ]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Content-Type"],
)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )
    return response


@app.get("/", tags=["system"], include_in_schema=False)
def home():
    return RedirectResponse(url="/ui", status_code=307)


@app.get("/ui", include_in_schema=False)
def frontend():
    page = PROJECT_DIR / "frontend" / "index.html"
    if not page.is_file():
        raise HTTPException(status_code=503, detail="Frontend bundle is unavailable.")
    return FileResponse(page, media_type="text/html")


@app.get("/favicon.svg", include_in_schema=False)
def favicon():
    icon = PROJECT_DIR / "frontend" / "favicon.svg"
    if not icon.is_file():
        raise HTTPException(status_code=404, detail="Favicon is unavailable.")
    return FileResponse(icon, media_type="image/svg+xml")


@app.get("/health", tags=["system"], response_model=HealthResult)
def health_check():
    if DEMO_MODE:
        return {
            "status": "healthy",
            "version": APP_VERSION,
            "storage": "disabled",
            "demo_mode": True,
        }
    try:
        with database_connection() as connection:
            connection.execute("SELECT 1").fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=503,
            detail="The assessment store is unavailable.",
        ) from exc
    return {
        "status": "healthy",
        "version": APP_VERSION,
        "storage": "available",
        "demo_mode": False,
    }


@app.post("/analyze-risk", tags=["assessments"], response_model=RiskResult)
def analyze_risk(request: RiskRequest):
    assessment_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = build_assessment(request)
    result["assessment_id"] = assessment_id
    result["created_at"] = created_at
    if not DEMO_MODE:
        try:
            persist_assessment(assessment_id, created_at, request, result)
        except sqlite3.Error as exc:
            raise HTTPException(
                status_code=503,
                detail="The assessment could not be saved. Please retry.",
            ) from exc
    return result


@app.get("/assessments", tags=["assessments"], response_model=AssessmentPage)
def get_assessments(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    if DEMO_MODE:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    try:
        items, total = list_assessments(limit, offset)
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=503,
            detail="Assessment history is temporarily unavailable.",
        ) from exc
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.get("/assessments/summary", tags=["assessments"], response_model=AssessmentSummary)
def assessment_summary():
    if DEMO_MODE:
        return {
            "total": 0,
            "high_risk": 0,
            "average_score": None,
            "highest_score": None,
        }
    try:
        return get_assessment_summary()
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=503,
            detail="Assessment summary is temporarily unavailable.",
        ) from exc


@app.delete(
    "/assessments",
    tags=["assessments"],
    response_model=ClearAssessmentsResult,
)
def delete_assessments():
    if DEMO_MODE:
        return {"deleted": 0}
    try:
        deleted = clear_assessments()
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=503,
            detail="Assessment history could not be cleared.",
        ) from exc
    return {"deleted": deleted}

from enum import StrEnum

from pydantic import BaseModel, Field


class ReviewMode(StrEnum):
    CONSERVATIVE = "conservative"
    AGGRESSIVE = "aggressive"


class FindingType(StrEnum):
    BUG = "bug"
    SECURITY = "security"
    PERFORMANCE = "performance"
    QUALITY = "quality"
    REFACTOR = "refactor"
    DOCUMENTATION = "documentation"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Decision(StrEnum):
    APPROVE = "approve"
    ESCALATE = "escalate"


class Finding(BaseModel):
    type: FindingType
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    description: str
    file_path: str | None = None
    line_number: int | None = None
    suggestion: str | None = None


class FileReview(BaseModel):
    file_path: str
    risk_level: RiskLevel
    summary: str
    findings: list[Finding] = Field(default_factory=list)


class ReviewerAssignment(BaseModel):
    username: str
    focus_areas: list[str]
    comment: str


class PRDecision(BaseModel):
    action: Decision
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str
    reasoning: str
    file_reviews: list[FileReview] = Field(default_factory=list)
    reviewer_assignments: list[ReviewerAssignment] = Field(default_factory=list)


class LLMCallRecord(BaseModel):
    call_id: str
    timestamp: str
    purpose: str
    model: str
    messages: list[dict]  # type: ignore[type-arg]
    response_text: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float

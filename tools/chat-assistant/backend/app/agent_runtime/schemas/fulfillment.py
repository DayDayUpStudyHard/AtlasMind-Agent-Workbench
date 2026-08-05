"""Pydantic models for fulfillment verification artifacts."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class FulfillmentConclusion(str, Enum):
    BASICALLY_SATISFIED = "BASICALLY_SATISFIED"
    HAS_ISSUES = "HAS_ISSUES"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNCLEAR_TERMS = "UNCLEAR_TERMS"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class RiskLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ManualResult(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PENDING = "PENDING"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"


class EvidenceSnapshotItem(BaseModel):
    """A snapshot of one evidence document at check time."""

    document_id: Optional[int] = Field(None, alias="documentId")
    file_name: str = Field(default="", alias="fileName")
    version: Optional[int] = None
    content_hash: Optional[str] = Field(None, alias="contentHash")
    snippet: str = ""
    matched_terms: Optional[list[str]] = Field(None, alias="matchedTerms")
    match_reason: str = Field(default="", alias="matchReason")


class FulfillmentRequirementJudgement(BaseModel):
    """Judgement for a single fulfillment sub-item."""

    requirement: str = Field(..., min_length=1)
    required: bool = True
    contract_citation_ids: Optional[list[str]] = Field(None, alias="contractCitationIds")
    evidence_citation_ids: Optional[list[str]] = Field(None, alias="evidenceCitationIds")
    evidence: str = ""
    judgement: str = ""
    reason: str = ""
    gap: str = ""
    risk_level: Optional[RiskLevel] = Field(None, alias="riskLevel")
    confidence_level: Optional[RiskLevel] = Field(None, alias="confidenceLevel")
    acceptance_criteria: Optional[str] = Field(None, alias="acceptanceCriteria")
    responsible_party: Optional[str] = Field(None, alias="responsibleParty")
    ambiguity: Optional[str] = None

    @model_validator(mode="after")
    def required_item_needs_contract_basis(self):
        if self.required and not (self.contract_citation_ids and len(self.contract_citation_ids) > 0):
            raise ValueError(
                f"required fulfillment item must have contract citation: '{self.requirement[:80]}'"
            )
        return self

    @model_validator(mode="after")
    def insufficient_evidence_cannot_claim_completion(self):
        if self.judgement == "EVIDENCE_INSUFFICIENT":
            if "已完成" in str(self.reason) or "已确认完成" in str(self.reason):
                raise ValueError(
                    "INSUFFICIENT_EVIDENCE judgement must not claim completion"
                )
        return self


class SuggestedFulfillmentAction(BaseModel):
    """Action suggested by the fulfillment agent, e.g. request missing materials."""

    type: str = Field(default="REQUEST_MATERIAL")
    title: str = ""
    description: str = ""


class FulfillmentArtifact(BaseModel):
    """Full fulfillment verification report artifact."""

    report_type: str = Field(default="FULFILLMENT_REPORT", alias="reportType")
    title: str = Field(..., min_length=1, max_length=512)
    summary: str = ""
    timeline_node_id: int = Field(default=0, alias="timelineNodeId")
    conclusion: Optional[FulfillmentConclusion] = None
    risk_level: Optional[RiskLevel] = Field(None, alias="riskLevel")
    confidence_level: Optional[RiskLevel] = Field(None, alias="confidenceLevel")
    requirements: list[FulfillmentRequirementJudgement] = []
    evidence_snapshot: list[EvidenceSnapshotItem] = Field(
        default_factory=list, alias="evidenceSnapshot"
    )
    missing_evidence: list[str] = Field(default_factory=list, alias="missingEvidence")
    explicit_consequence: str = Field(default="", alias="explicitConsequence")
    ai_risk: str = Field(default="", alias="aiRisk")
    suggested_actions: list[SuggestedFulfillmentAction] = Field(
        default_factory=list, alias="suggestedActions"
    )
    citations: Optional[list[dict]] = None
    content: Optional[dict] = None
    manual_confirmation_required: bool = Field(default=True, alias="manualConfirmationRequired")

    @field_validator("ai_risk")
    @classmethod
    def ai_risk_must_have_disclaimer(cls, v: str) -> str:
        if v and "AI 推断" not in v and "仅供参考" not in v:
            return f"AI 推断，仅供参考：{v}"
        return v

    @field_validator("explicit_consequence")
    @classmethod
    def explicit_consequence_must_not_contain_ai_disclaimer(cls, v: str) -> str:
        if v and "AI 推断" in v:
            raise ValueError("explicitConsequence must not contain AI-inferred content")
        return v

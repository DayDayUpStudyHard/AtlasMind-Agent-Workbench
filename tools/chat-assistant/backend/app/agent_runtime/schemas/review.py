"""Pydantic models for contract review reports, findings, and citations.

These models validate the structure and key business invariants of
contract review artifacts before they reach MySqlReportStore.save_report().
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class Severity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RiskStatus(str, Enum):
    LOW_RISK = "LOW_RISK"
    MEDIUM_RISK = "MEDIUM_RISK"
    HIGH_RISK = "HIGH_RISK"


class ClauseType(str, Enum):
    LIABILITY = "LIABILITY"
    PAYMENT = "PAYMENT"
    CONFIDENTIALITY = "CONFIDENTIALITY"
    ACCEPTANCE = "ACCEPTANCE"
    TERMINATION = "TERMINATION"
    IP = "IP"
    DATA_PROTECTION = "DATA_PROTECTION"
    OTHER = "OTHER"


class SuggestedAction(str, Enum):
    CREATE_NEGOTIATION_TASK = "CREATE_NEGOTIATION_TASK"
    REQUEST_MATERIAL = "REQUEST_MATERIAL"
    REQUEST_LEGAL_REVIEW = "REQUEST_LEGAL_REVIEW"
    SCHEDULE_REMINDER = "SCHEDULE_REMINDER"


class EvidenceStatus(str, Enum):
    DUAL_CITED = "DUAL_CITED"
    CONTRACT_ONLY = "CONTRACT_ONLY"
    POLICY_ONLY = "POLICY_ONLY"
    MISSING = "MISSING"


class SourceBasis(str, Enum):
    CONTRACT_AND_POLICY = "CONTRACT_AND_POLICY"
    CONTRACT_ONLY = "CONTRACT_ONLY"
    POLICY_ONLY = "POLICY_ONLY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class AnalysisMode(str, Enum):
    FULL = "FULL"
    LIMITED = "LIMITED"
    FALLBACK = "FALLBACK"


class DualCitation(BaseModel):
    """A citation referencing either a contract clause or a policy/knowledge source."""

    source_type: str = Field(
        ...,
        alias="sourceType",
        description="CONTRACT_CLAUSE | KB_CHUNK | STANDARD_CLAUSE | KB_DOCUMENT",
    )
    source_id: str = Field(
        ...,
        alias="sourceId",
        description="Prefixed ID, e.g. CONTRACT_CLAUSE:182 or KB_CHUNK:903",
    )
    document_id: Optional[int] = Field(None, alias="documentId")
    document_version: Optional[int] = Field(None, alias="documentVersion")
    content_hash: Optional[str] = Field(None, alias="contentHash")
    page: Optional[int] = None
    clause_number: Optional[str] = Field(None, alias="clauseNumber")
    snippet: str = ""
    retrieval_score: Optional[float] = Field(None, alias="retrievalScore")
    retrieval_type: Optional[str] = Field(None, alias="retrievalType")
    scope: str = "CURRENT_CASE"

    @field_validator("source_id")
    @classmethod
    def source_id_must_have_prefix(cls, v: str) -> str:
        if ":" not in v and not v.startswith(("CONTRACT_", "KB_", "STANDARD_")):
            raise ValueError(
                f"citation source_id must include source-type prefix, got: {v}"
            )
        return v


class ContractCitation(BaseModel):
    """Contract-specific citation (legacy format, used in findings)."""

    page: Optional[int] = None
    clause: str = ""
    clause_number: Optional[str] = Field(None, alias="clauseNumber")
    snippet: str = ""


class PolicyCitation(BaseModel):
    """Policy/knowledge citation (legacy format, used in findings)."""

    rule_key: Optional[str] = Field(None, alias="ruleKey")
    rule_title: Optional[str] = Field(None, alias="ruleTitle")
    snippet: str = ""


class ContractFinding(BaseModel):
    """A single contract review finding with dual citation."""

    finding_key: Optional[str] = Field(None, alias="findingKey")
    clause_type: ClauseType = Field(default=ClauseType.OTHER, alias="clauseType")
    severity: Severity = Severity.MEDIUM
    title: str = Field(..., min_length=1, max_length=512)
    domain_key: Optional[str] = Field(None, alias="domainKey")
    domain_name: Optional[str] = Field(None, alias="domainName")
    source_basis: Optional[SourceBasis] = Field(None, alias="sourceBasis")
    one_line_summary: Optional[str] = Field(None, alias="oneLineSummary")
    key_point: Optional[str] = Field(None, alias="keyPoint")
    description: str = ""
    risk_explanation: Optional[str] = Field(None, alias="riskExplanation")
    claim: Optional[str] = None
    impact: str = ""
    business_impact: Optional[str] = Field(None, alias="businessImpact")
    contract_basis: Optional[dict] = Field(None, alias="contractBasis")
    knowledge_basis: Optional[dict] = Field(None, alias="knowledgeBasis")
    explicit_consequence: Optional[str] = Field(None, alias="explicitConsequence")
    inferred_consequence: Optional[str] = Field(None, alias="inferredConsequence")
    inferred_consequence_disclaimer: Optional[str] = Field(
        None, alias="inferredConsequenceDisclaimer"
    )
    remediation_advice: Optional[str] = Field(None, alias="remediationAdvice")
    revision_advice: Optional[str] = Field(None, alias="revisionAdvice")
    negotiation_advice: Optional[str] = Field(None, alias="negotiationAdvice")
    review_questions: Optional[list[str]] = Field(None, alias="reviewQuestions")
    verification_points: Optional[list[str]] = Field(None, alias="verificationPoints")
    suggested_action: Optional[SuggestedAction] = Field(None, alias="suggestedAction")
    contract_citation: Optional[ContractCitation] = Field(None, alias="contractCitation")
    policy_citation: Optional[PolicyCitation] = Field(None, alias="policyCitation")
    contract_citation_ids: Optional[list[str]] = Field(None, alias="contractCitationIds")
    policy_citation_ids: Optional[list[str]] = Field(None, alias="policyCitationIds")
    evidence_status: Optional[EvidenceStatus] = Field(None, alias="evidenceStatus")
    confidence_level: Optional[str] = Field(None, alias="confidenceLevel")
    frontend_display: Optional[dict] = Field(None, alias="frontendDisplay")

    @model_validator(mode="after")
    def high_severity_needs_citation(self):
        if self.severity == Severity.HIGH:
            has_contract = bool(
                self.contract_citation
                or (self.contract_citation_ids and len(self.contract_citation_ids) > 0)
            )
            if not has_contract:
                raise ValueError(
                    f"HIGH severity finding '{self.title}' must have contract evidence"
                )
        return self


class ActionProposal(BaseModel):
    """An action proposed by the agent, pending human approval."""

    type: SuggestedAction
    title: str = Field(..., min_length=1, max_length=512)
    description: str = ""
    priority: Severity = Severity.MEDIUM


class ReviewDimension(BaseModel):
    """A single risk dimension score from the deterministic engine."""

    name: str
    score: float = Field(ge=0.0, le=100.0)
    weight: float = Field(ge=0.0, le=1.0)


class ContractReviewArtifact(BaseModel):
    """Full contract review report artifact.

    This is what the LLM generates and what MySqlReportStore persists.
    """

    report_type: str = Field(default="CONTRACT_REVIEW_REPORT", alias="reportType")
    title: str = Field(..., min_length=1, max_length=512)
    summary: str = ""
    risk_status: Optional[RiskStatus] = Field(None, alias="riskStatus")
    risk_score: Optional[float] = Field(None, alias="riskScore", ge=0.0, le=100.0)
    analysis_mode: AnalysisMode = Field(default=AnalysisMode.FULL, alias="analysisMode")
    coverage_limitation: Optional[str] = Field(None, alias="coverageLimitation")
    scoring_version: Optional[str] = Field(None, alias="scoringVersion")
    evidence_hash: Optional[str] = Field(None, alias="evidenceHash")
    findings: list[ContractFinding] = Field(default_factory=list)
    dimensions: Optional[list[ReviewDimension]] = None
    action_proposals: list[ActionProposal] = Field(
        default_factory=list, alias="actionProposals"
    )
    citations: Optional[list[DualCitation]] = None
    report_markdown: Optional[str] = Field(None, alias="reportMarkdown")
    content: Optional[dict] = None

    @field_validator("findings")
    @classmethod
    def deduplicate_findings(cls, v: list[ContractFinding]) -> list[ContractFinding]:
        seen: set[str] = set()
        unique: list[ContractFinding] = []
        for finding in v:
            key = finding.finding_key or finding.title
            if key not in seen:
                seen.add(key)
                unique.append(finding)
        return unique

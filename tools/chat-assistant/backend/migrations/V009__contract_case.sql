-- V009: Contract Case domain model + Subject abstraction for Agent tables.
-- Phase 0-1 migration per PRD-contract-lifecycle-agent-2026-08-03.

-- ============================================================
-- 1. Contract Case main table
-- ============================================================
CREATE TABLE IF NOT EXISTS contract_case (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    case_key            VARCHAR(64)     NOT NULL COMMENT 'Human-readable case identifier, e.g. SRV-2026-0042',
    title               VARCHAR(512)    NOT NULL COMMENT 'Case title',
    contract_type       VARCHAR(64)     NOT NULL DEFAULT 'SERVICE_PROCUREMENT' COMMENT 'Contract type',
    status              VARCHAR(32)     NOT NULL DEFAULT 'DRAFT' COMMENT 'DRAFT|MATERIAL_PENDING|READY_FOR_REVIEW|REVIEWING|NEEDS_REVISION|PENDING_APPROVAL|APPROVED|READY_TO_SIGN|SIGNED|IN_FULFILLMENT|EXPIRED|TERMINATED',
    description         TEXT            NULL COMMENT 'Business background',
    our_entity          VARCHAR(256)    NULL COMMENT 'Our legal entity name',
    counterparty        VARCHAR(256)    NULL COMMENT 'Counterparty name',
    amount              DECIMAL(18,2)   NULL COMMENT 'Contract amount',
    currency            VARCHAR(8)      NULL DEFAULT 'CNY',
    effective_date      DATE            NULL,
    expiry_date         DATE            NULL,
    department          VARCHAR(128)    NULL COMMENT 'Owning department',
    owner_id            BIGINT          NULL COMMENT 'Business owner user id',
    priority            VARCHAR(16)     NULL DEFAULT 'NORMAL' COMMENT 'LOW|NORMAL|HIGH|CRITICAL',
    tags                VARCHAR(512)    NULL COMMENT 'Comma-separated tags',
    approved_version_id BIGINT          NULL COMMENT 'FK to contract_document — the approved version hash',
    signed_version_id   BIGINT          NULL COMMENT 'FK to contract_document — the signed version hash',
    last_run_id         BIGINT          NULL,
    last_run_at         DATETIME        NULL,
    create_time         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted             TINYINT         NOT NULL DEFAULT 0,
    INDEX idx_status (status),
    INDEX idx_owner (owner_id),
    INDEX idx_department (department),
    INDEX idx_expiry (expiry_date),
    UNIQUE KEY uk_case_key (case_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Contract case — the core business object';

-- ============================================================
-- 2. Contract parties (may have multiple counterparties)
-- ============================================================
CREATE TABLE IF NOT EXISTS contract_party (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    case_id         BIGINT          NOT NULL COMMENT 'FK contract_case.id',
    party_name      VARCHAR(256)    NOT NULL,
    party_role      VARCHAR(32)     NOT NULL DEFAULT 'COUNTERPARTY' COMMENT 'OUR_ENTITY|COUNTERPARTY|GUARANTOR|AGENT',
    contact_person  VARCHAR(128)    NULL,
    contact_email   VARCHAR(256)    NULL,
    risk_score      DOUBLE          NULL COMMENT 'Auto-computed from historical performance',
    create_time     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_case (case_id),
    INDEX idx_name (party_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- 3. Contract documents (files, versions, attachments)
-- ============================================================
CREATE TABLE IF NOT EXISTS contract_document (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    case_id             BIGINT          NOT NULL COMMENT 'FK contract_case.id',
    document_type       VARCHAR(32)     NOT NULL DEFAULT 'MAIN' COMMENT 'MAIN|ATTACHMENT|PRICING|CERTIFICATE|FULFILLMENT_EVIDENCE|OTHER',
    file_name           VARCHAR(512)    NOT NULL,
    file_path           VARCHAR(1024)   NOT NULL COMMENT 'Storage path or URL',
    file_size           BIGINT          NULL,
    content_hash        VARCHAR(128)    NULL COMMENT 'SHA-256 for version dedup',
    version             INT             NOT NULL DEFAULT 1,
    parse_status        VARCHAR(32)     NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING|PARSING|READY|FAILED',
    parse_error         TEXT            NULL,
    page_count          INT             NULL,
    upload_by           BIGINT          NULL,
    create_time         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_case (case_id),
    INDEX idx_parse (parse_status),
    UNIQUE KEY uk_case_version (case_id, version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- 4. Contract clauses (extracted, structured, locatable)
-- ============================================================
CREATE TABLE IF NOT EXISTS contract_clause (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    document_id         BIGINT          NOT NULL COMMENT 'FK contract_document.id',
    case_id             BIGINT          NOT NULL COMMENT 'FK contract_case.id',
    clause_number       VARCHAR(64)     NULL COMMENT 'e.g. 8.3 or Article VIII Section 3',
    title               VARCHAR(256)    NULL COMMENT 'Clause heading',
    content             TEXT            NOT NULL,
    page_number         INT             NULL,
    clause_type         VARCHAR(64)     NULL COMMENT 'LIABILITY|PAYMENT|CONFIDENTIALITY|ACCEPTANCE|TERMINATION|IP|DATA_PROTECTION|OTHER',
    semantic_elements   JSON            NULL COMMENT 'LLM-extracted semantic elements (e.g. {liabilityCap: 100%, indirectDamages: excluded})',
    start_offset        INT             NULL COMMENT 'Character offset in document text',
    end_offset          INT             NULL,
    create_time         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_doc (document_id),
    INDEX idx_case (case_id),
    INDEX idx_type (clause_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Extracted contract clauses with semantic metadata';

-- ============================================================
-- 5. Contract review findings (was: agent_action for contracts)
-- ============================================================
CREATE TABLE IF NOT EXISTS contract_review_finding (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    case_id             BIGINT          NOT NULL COMMENT 'FK contract_case.id',
    run_id              BIGINT          NULL COMMENT 'FK agent_run.id — which Agent run created this finding',
    rule_id             BIGINT          NULL COMMENT 'FK contract_review_rule.id (future)',
    severity            VARCHAR(16)     NOT NULL DEFAULT 'MEDIUM' COMMENT 'HIGH|MEDIUM|LOW',
    status              VARCHAR(32)     NOT NULL DEFAULT 'OPEN' COMMENT 'OPEN|REMEDIATED|ACCEPTED_EXCEPTION|DISMISSED',
    title               VARCHAR(512)    NOT NULL,
    description         TEXT            NULL,
    contract_citation   JSON            NULL COMMENT '{documentId, version, page, clauseNumber, snippet}',
    policy_citation     JSON            NULL COMMENT '{documentId, version, ruleNumber, snippet}',
    suggested_action    VARCHAR(64)     NULL,
    resolved_by         BIGINT          NULL,
    resolved_at         DATETIME        NULL,
    create_time         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_case (case_id),
    INDEX idx_run (run_id),
    INDEX idx_status (status),
    INDEX idx_severity (severity)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Contract review findings with dual citation';

-- ============================================================
-- 6. Contract obligations (post-signing fulfillment tracking)
-- ============================================================
CREATE TABLE IF NOT EXISTS contract_obligation (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    case_id             BIGINT          NOT NULL COMMENT 'FK contract_case.id',
    title               VARCHAR(512)    NOT NULL,
    obligation_type     VARCHAR(64)     NOT NULL DEFAULT 'OTHER' COMMENT 'PAYMENT|DELIVERY|ACCEPTANCE|NOTICE|RENEWAL|OTHER',
    responsible_user_id BIGINT          NULL,
    due_date            DATE            NULL,
    trigger_condition   VARCHAR(512)    NULL COMMENT 'For condition-based obligations without a fixed date',
    status              VARCHAR(32)     NOT NULL DEFAULT 'PLANNED' COMMENT 'PLANNED|DUE_SOON|COMPLETED|OVERDUE|ESCALATED|WAIVED',
    evidence_required   TINYINT         NOT NULL DEFAULT 0,
    reminder_days_before INT            NULL COMMENT 'Days before due date to send reminder',
    completed_at        DATETIME        NULL,
    completed_by        BIGINT          NULL,
    create_time         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_case (case_id),
    INDEX idx_status (status),
    INDEX idx_due (due_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- 7. Standard clause library (for semantic matching)
-- ============================================================
CREATE TABLE IF NOT EXISTS contract_standard_clause (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    clause_type         VARCHAR(64)     NOT NULL COMMENT 'LIABILITY|PAYMENT|CONFIDENTIALITY|ACCEPTANCE|TERMINATION|IP|DATA_PROTECTION',
    title               VARCHAR(256)    NOT NULL,
    content             TEXT            NOT NULL,
    semantic_elements   JSON            NULL COMMENT 'Confirmed semantic elements — the matching baseline',
    is_mandatory        TINYINT         NOT NULL DEFAULT 0 COMMENT 'Non-negotiable clause',
    negotiation_bottom_line TEXT        NULL COMMENT 'Fallback position if counterparty pushes back',
    version             INT             NOT NULL DEFAULT 1,
    is_active           TINYINT         NOT NULL DEFAULT 1,
    effective_from      DATE            NULL,
    effective_to        DATE            NULL,
    create_time         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_type (clause_type),
    INDEX idx_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Enterprise standard clause library for semantic matching';

-- ============================================================
-- 8. Subject abstraction for Agent tables (compatible migration)
-- ============================================================
ALTER TABLE agent_run
    ADD COLUMN IF NOT EXISTS subject_type VARCHAR(32) NULL DEFAULT 'PROJECT' COMMENT 'PROJECT|CONTRACT_CASE',
    ADD COLUMN IF NOT EXISTS subject_id   BIGINT      NULL;

ALTER TABLE agent_report
    ADD COLUMN IF NOT EXISTS subject_type VARCHAR(32) NULL DEFAULT 'PROJECT',
    ADD COLUMN IF NOT EXISTS subject_id   BIGINT      NULL;

ALTER TABLE agent_action
    ADD COLUMN IF NOT EXISTS subject_type VARCHAR(32) NULL DEFAULT 'PROJECT',
    ADD COLUMN IF NOT EXISTS subject_id   BIGINT      NULL;

-- Backfill existing data: subject_type = PROJECT, subject_id = project_id
UPDATE agent_run    SET subject_type = 'PROJECT', subject_id = project_id WHERE subject_id IS NULL AND project_id IS NOT NULL;
UPDATE agent_report SET subject_type = 'PROJECT', subject_id = project_id WHERE subject_id IS NULL AND project_id IS NOT NULL;
UPDATE agent_action SET subject_type = 'PROJECT', subject_id = project_id WHERE subject_id IS NULL AND project_id IS NOT NULL;

-- ============================================================
-- 9. PRODUCT_MODE config seed
-- ============================================================
INSERT IGNORE INTO system_config (config_key, config_value, description) VALUES
('PRODUCT_MODE', 'contract', 'Product mode: contract (ContractOps) or project (legacy R&D). Switch to project to roll back.');

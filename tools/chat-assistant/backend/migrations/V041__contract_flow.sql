-- V041: Phase 2 contract approval flow schema.
-- Source of truth: docs/contract-workflow/phase-2-design.md §1 (tables 1.1–1.6)
-- and §5 (approver tables). Business logic lands in later steps; this migration
-- only creates storage plus the two approver whitelist tables needed for seed data.
--
-- Node chain is linear: at most one node is active (PENDING/CLAIMED/BLOCKED) per
-- flow. Events are append-only and are the single source of derived progress.

CREATE TABLE IF NOT EXISTS contract_flow (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    case_id         BIGINT      NOT NULL COMMENT 'FK contract_case.id',
    round_no        INT         NOT NULL COMMENT '1-based round within the case',
    state           VARCHAR(16) NOT NULL DEFAULT 'RUNNING' COMMENT 'RUNNING|COMPLETED|CANCELLED',
    version_id      BIGINT      NOT NULL COMMENT 'Reviewed contract version - approval binds to (flow, version)',
    start_node      VARCHAR(32) NOT NULL DEFAULT 'UPLOADER' COMMENT 'First node of this round - non-UPLOADER after withdraw restart',
    parent_flow_id  BIGINT      NULL COMMENT 'Previous round when restarted after withdraw',
    baseline_json   JSON        NOT NULL COMMENT 'Snapshot of substantive fields used as change baseline',
    baseline_hash   CHAR(64)    NOT NULL COMMENT 'SHA-256 of baseline_json',
    agent_run_id    BIGINT      NULL COMMENT 'Current agent run for this round',
    started_by      BIGINT      NULL COMMENT 'user_id that started the round',
    started_at      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at        DATETIME    NULL,
    end_reason      VARCHAR(64) NULL COMMENT 'COMPLETED|WITHDRAWN|CANCELLED|ABANDONED',
    UNIQUE KEY uk_case_round (case_id, round_no),
    KEY idx_case (case_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Phase 2 approval flow round';

CREATE TABLE IF NOT EXISTS contract_flow_node (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    flow_id           BIGINT      NOT NULL COMMENT 'FK contract_flow.id',
    node_key          VARCHAR(32) NOT NULL COMMENT 'UPLOADER|AGENT|DEPT_APPROVAL|LEGAL_APPROVAL|SIGNING',
    seq               INT         NOT NULL COMMENT 'Order within the linear chain',
    state             VARCHAR(16) NOT NULL COMMENT 'PENDING|CLAIMED|DONE|BLOCKED|VOID',
    assignee_id       BIGINT      NULL COMMENT 'Current holder user_id',
    claimed_at        DATETIME    NULL,
    claim_expires_at  DATETIME    NULL,
    candidate_group   VARCHAR(64) NULL COMMENT 'OWNER|DEPT:<deptId>|LEGAL',
    entered_at        DATETIME    NOT NULL,
    done_at           DATETIME    NULL,
    pending_rerun     TINYINT     NOT NULL DEFAULT 0 COMMENT '1 = rerun requested while agent is running',
    UNIQUE KEY uk_flow_node (flow_id, node_key, seq),
    KEY idx_flow_state (flow_id, state)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='One node instance within a flow round';

CREATE TABLE IF NOT EXISTS contract_flow_event (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    flow_id      BIGINT      NOT NULL COMMENT 'FK contract_flow.id',
    node_id      BIGINT      NULL COMMENT 'FK contract_flow_node.id when the event belongs to a node',
    event_type   VARCHAR(32) NOT NULL COMMENT 'Enum defined in phase-2-design §1.3',
    actor_id     BIGINT      NULL,
    actor_type   VARCHAR(8)  NOT NULL COMMENT 'USER|AGENT|SYSTEM',
    from_node    VARCHAR(32) NULL,
    to_node      VARCHAR(32) NULL,
    payload_json JSON        NULL,
    ref_id       BIGINT      NULL COMMENT 'agent_run_id / withdraw_id / sign_check_id used for idempotency',
    created_at   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_flow_time (flow_id, created_at),
    KEY idx_flow_type (flow_id, event_type, id),
    -- MySQL unique indexes treat NULL as distinct, so this only dedupes events
    -- that carry both a node_id and a ref_id. Events without a ref_id (EDIT,
    -- CONFIRM_* and other repeatable actions) intentionally stay repeatable.
    UNIQUE KEY uk_event (flow_id, node_id, event_type, ref_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Append-only flow event stream';

CREATE TABLE IF NOT EXISTS contract_flow_claim (
    id             BIGINT AUTO_INCREMENT PRIMARY KEY,
    node_id        BIGINT      NOT NULL COMMENT 'FK contract_flow_node.id',
    user_id        BIGINT      NOT NULL,
    claimed_at     DATETIME    NOT NULL,
    released_at    DATETIME    NULL,
    release_reason VARCHAR(32) NULL COMMENT 'MANUAL|TIMEOUT|FORCED|RETURNED|DONE',
    KEY idx_node (node_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Claim history for a flow node';

CREATE TABLE IF NOT EXISTS contract_flow_withdraw (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    flow_id       BIGINT       NOT NULL COMMENT 'FK contract_flow.id',
    requester_id  BIGINT       NOT NULL,
    target_node   VARCHAR(32)  NOT NULL COMMENT 'Node to restart from after withdraw approval',
    reason        VARCHAR(512) NOT NULL,
    state         VARCHAR(16)  NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING|APPROVED|REJECTED|EXPIRED',
    -- Maps PENDING to 1 and everything else to NULL so the unique index below
    -- enforces at most one open withdraw per flow (MySQL ignores NULLs).
    pending_flag  TINYINT GENERATED ALWAYS AS (IF(state='PENDING', 1, NULL)) STORED,
    decided_by    BIGINT       NULL,
    decided_at    DATETIME     NULL,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_flow_pending (flow_id, pending_flag),
    KEY idx_flow (flow_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Withdraw requests - approval restarts a new round';

CREATE TABLE IF NOT EXISTS contract_sign_check (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    flow_id           BIGINT      NOT NULL COMMENT 'FK contract_flow.id',
    version_id        BIGINT      NOT NULL COMMENT 'Approved version compared against',
    signed_doc_id     BIGINT      NOT NULL COMMENT 'FK contract_document.id of the signed copy',
    rule_result_json  JSON        NULL,
    agent_result_json JSON        NULL,
    verdict           VARCHAR(16) NOT NULL COMMENT 'MATCH|MISMATCH|UNKNOWN',
    decided_by        BIGINT      NULL,
    decision          VARCHAR(16) NULL COMMENT 'APPROVE|RERUN|ABANDON',
    decided_at        DATETIME    NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Signed copy consistency check';

-- ── Approver whitelist tables (phase-2-design §5, decision #15) ──────────

CREATE TABLE IF NOT EXISTS dept_approver (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    dept_id     BIGINT   NOT NULL COMMENT 'FK department.id',
    user_id     BIGINT   NOT NULL COMMENT 'FK t_user.id',
    created_by  BIGINT   NULL,
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_dept_user (dept_id, user_id),
    KEY idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Department approver whitelist';

CREATE TABLE IF NOT EXISTS flow_role_member (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    role_code   VARCHAR(32) NOT NULL COMMENT 'LEGAL',
    user_id     BIGINT      NOT NULL COMMENT 'FK t_user.id',
    created_by  BIGINT      NULL,
    create_time DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_role_user (role_code, user_id),
    KEY idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Flow role membership (LEGAL group)';

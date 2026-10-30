-- Phase 2 contract flow bootstrap seed (step 1 deliverable).
-- Idempotent: safe to run repeatedly. No business logic — configuration rows only.
--
-- Prerequisites (created by the Java service at startup, not by migrations):
--   system_config, department, t_user.role / department_id / status
-- Run after the service stack has initialised once:
--   mysql -u root -p atlasmind_agent < agent-server/sql/contract_flow_seed.sql
--
-- Decision #15: dev environments need at least one approver and one legal
-- member, otherwise the flow cannot be exercised end-to-end.

SET NAMES utf8mb4;

-- 1. Frontend switch. Default OFF: phase-1 WorkflowStrip stays in use until an
--    administrator explicitly flips it. INSERT IGNORE preserves later changes.
INSERT IGNORE INTO system_config (config_key, config_value)
VALUES ('contract.flow_v2_enabled', 'false');

-- 2. Department approvers: every active user in the default department.
--    Uses SELECT instead of hardcoded ids so fresh databases work unchanged.
INSERT INTO dept_approver (dept_id, user_id, created_by)
SELECT d.id, u.id, NULL
FROM department d
JOIN t_user u ON u.department_id = d.id
WHERE d.is_default = 1
  AND d.deleted = 0
  AND u.status = 'ACTIVE'
  AND NOT EXISTS (
      SELECT 1 FROM dept_approver a
      WHERE a.dept_id = d.id AND a.user_id = u.id
  );

-- 3. Legal group: bootstrap admin as the first legal member. There is no
--    department binding for LEGAL — membership is per user (design §5).
INSERT INTO flow_role_member (role_code, user_id, created_by)
SELECT 'LEGAL', u.id, NULL
FROM t_user u
WHERE u.username = 'admin'
  AND NOT EXISTS (
      SELECT 1 FROM flow_role_member m
      WHERE m.role_code = 'LEGAL' AND m.user_id = u.id
  );

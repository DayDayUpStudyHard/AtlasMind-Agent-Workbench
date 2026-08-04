-- V014: Denormalize contract finding keys used by scoring, queues, and UI.

ALTER TABLE contract_review_finding
    ADD COLUMN IF NOT EXISTS rule_key VARCHAR(64) NULL AFTER rule_id,
    ADD COLUMN IF NOT EXISTS clause_type VARCHAR(64) NULL AFTER rule_key,
    ADD COLUMN IF NOT EXISTS impact TEXT NULL AFTER description;

UPDATE contract_review_finding f
LEFT JOIN contract_review_rule r ON r.id = f.rule_id
SET
    f.rule_key = COALESCE(f.rule_key, r.rule_key),
    f.clause_type = COALESCE(f.clause_type, r.clause_type)
WHERE f.rule_key IS NULL OR f.clause_type IS NULL;

UPDATE contract_review_finding
SET
    rule_key = COALESCE(rule_key, JSON_UNQUOTE(JSON_EXTRACT(policy_citation, '$.ruleKey'))),
    clause_type = COALESCE(clause_type, JSON_UNQUOTE(JSON_EXTRACT(policy_citation, '$.clauseType')))
WHERE policy_citation IS NOT NULL AND (rule_key IS NULL OR clause_type IS NULL);

UPDATE contract_review_finding f
JOIN contract_review_rule r ON r.rule_key = f.rule_key AND r.is_active = 1
SET
    f.rule_id = COALESCE(f.rule_id, r.id),
    f.clause_type = COALESCE(f.clause_type, r.clause_type)
WHERE f.rule_key IS NOT NULL AND (f.rule_id IS NULL OR f.clause_type IS NULL);

UPDATE contract_case c
SET c.status='NEEDS_REVISION'
WHERE c.deleted=0
  AND c.status IN ('DRAFT','READY_FOR_REVIEW','REVIEWING','PENDING_APPROVAL')
  AND EXISTS (
      SELECT 1 FROM contract_review_finding f
      WHERE f.case_id=c.id AND f.status='OPEN'
  );

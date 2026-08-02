-- V010: Contract review rules + standard clause seeds (Phase 3)
-- Service procurement contract rules — MVP set of 15-20 rules.

CREATE TABLE IF NOT EXISTS contract_review_rule (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    rule_key        VARCHAR(64)     NOT NULL COMMENT 'e.g. PROCUREMENT-PAYMENT-001',
    rule_set         VARCHAR(64)     NOT NULL DEFAULT 'SERVICE_PROCUREMENT_V1',
    clause_type     VARCHAR(64)     NOT NULL COMMENT 'LIABILITY|PAYMENT|CONFIDENTIALITY|ACCEPTANCE|TERMINATION|IP|DATA_PROTECTION',
    title           VARCHAR(256)    NOT NULL,
    description     TEXT            NOT NULL COMMENT 'What this rule checks for',
    check_type      VARCHAR(32)     NOT NULL DEFAULT 'MISSING' COMMENT 'MISSING|THRESHOLD|CONTAINS|PATTERN|SEMANTIC',
    check_config    JSON            NULL COMMENT 'Rule-specific config: {field, operator, value, keywords}',
    severity        VARCHAR(16)     NOT NULL DEFAULT 'MEDIUM' COMMENT 'HIGH|MEDIUM|LOW',
    weight          INT             NOT NULL DEFAULT 10 COMMENT 'Scoring impact (0-100)',
    is_veto         TINYINT         NOT NULL DEFAULT 0 COMMENT '1 = one-vote veto regardless of total score',
    is_active       TINYINT         NOT NULL DEFAULT 1,
    version         INT             NOT NULL DEFAULT 1,
    effective_from  DATE            NULL,
    effective_to    DATE            NULL,
    create_time     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_rule_set (rule_set),
    INDEX idx_clause_type (clause_type),
    INDEX idx_active (is_active),
    UNIQUE KEY uk_rule_key_version (rule_key, version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Seed service procurement rules
INSERT IGNORE INTO contract_review_rule (rule_key, rule_set, clause_type, title, description, check_type, check_config, severity, weight) VALUES
-- Party & Authority
('PROC-PARTY-001', 'SERVICE_PROCUREMENT_V1', 'LIABILITY', '主体信息完整性', '合同主体名称、地址、法定代表人是否完整填写', 'MISSING', '{"fields": ["ourEntity", "counterparty"]}', 'HIGH', 15),
('PROC-PARTY-002', 'SERVICE_PROCUREMENT_V1', 'LIABILITY', '签署授权有效性', '签署人是否具有有效授权（需核对授权书或营业执照）', 'MISSING', '{"fields": ["signatoryAuthority"]}', 'HIGH', 15),

-- Payment
('PROC-PAY-001', 'SERVICE_PROCUREMENT_V1', 'PAYMENT', '预付款比例合规', '预付款比例不得超过公司制度规定的30%上限', 'THRESHOLD', '{"field": "advancePaymentPct", "operator": "lte", "value": 30}', 'HIGH', 20),
('PROC-PAY-002', 'SERVICE_PROCUREMENT_V1', 'PAYMENT', '付款节点与交付挂钩', '付款节点必须与可验证的交付里程碑关联', 'CONTAINS', '{"keywords": ["验收","交付","里程碑","完成"]}', 'MEDIUM', 10),
('PROC-PAY-003', 'SERVICE_PROCUREMENT_V1', 'PAYMENT', '发票要求明确', '合同应明确发票类型、税率和开具时间', 'MISSING', '{"fields": ["invoiceType", "taxRate"]}', 'LOW', 5),
('PROC-PAY-004', 'SERVICE_PROCUREMENT_V1', 'PAYMENT', '逾期违约金约定', '应约定逾期付款违约金比例或计算方式', 'MISSING', '{"fields": ["latePaymentPenalty"]}', 'MEDIUM', 10),

-- Acceptance & Delivery
('PROC-ACC-001', 'SERVICE_PROCUREMENT_V1', 'ACCEPTANCE', '验收标准明确', '验收标准不得为"甲方单方决定"，必须具有客观可衡量标准', 'SEMANTIC', '{"forbidden": ["甲方单方决定","甲方自行判断","甲方认为合格"]}', 'HIGH', 20),
('PROC-ACC-002', 'SERVICE_PROCUREMENT_V1', 'ACCEPTANCE', '验收期限明确', '验收应在交付后明确天数内完成', 'MISSING', '{"fields": ["acceptancePeriod"]}', 'MEDIUM', 10),
('PROC-ACC-003', 'SERVICE_PROCUREMENT_V1', 'ACCEPTANCE', 'SLA与服务水平协议', '服务类合同应包含可量化的服务水平指标和未达标处罚', 'MISSING', '{"fields": ["slaMetrics", "slaPenalty"]}', 'HIGH', 15),

-- Liability
('PROC-LIAB-001', 'SERVICE_PROCUREMENT_V1', 'LIABILITY', '责任上限合理性', '违约责任上限不应低于合同金额的100%', 'THRESHOLD', '{"field": "liabilityCapPct", "operator": "gte", "value": 100}', 'HIGH', 20),
('PROC-LIAB-002', 'SERVICE_PROCUREMENT_V1', 'LIABILITY', '间接损失排除', '应明确排除间接损失和利润损失的赔偿', 'CONTAINS', '{"keywords": ["间接损失","利润损失","排除","不承担"]}', 'HIGH', 15),
('PROC-LIAB-003', 'SERVICE_PROCUREMENT_V1', 'LIABILITY', '第三方索赔处理', '应明确因服务导致的第三方索赔责任归属', 'MISSING', '{"fields": ["thirdPartyClaims"]}', 'MEDIUM', 8),

-- Termination
('PROC-TERM-001', 'SERVICE_PROCUREMENT_V1', 'TERMINATION', '终止通知期限', '任意方终止合同的通知期限不应少于30天', 'THRESHOLD', '{"field": "terminationNoticeDays", "operator": "gte", "value": 30}', 'MEDIUM', 10),
('PROC-TERM-002', 'SERVICE_PROCUREMENT_V1', 'TERMINATION', '合同到期处理', '应明确合同到期后的过渡服务安排和数据迁移义务', 'MISSING', '{"fields": ["transitionService", "dataMigration"]}', 'MEDIUM', 8),

-- Confidentiality & Data
('PROC-CONF-001', 'SERVICE_PROCUREMENT_V1', 'CONFIDENTIALITY', '保密义务存续', '保密义务在合同终止后应继续有效至少2年', 'THRESHOLD', '{"field": "confidentialitySurvivalYears", "operator": "gte", "value": 2}', 'MEDIUM', 10),
('PROC-CONF-002', 'SERVICE_PROCUREMENT_V1', 'CONFIDENTIALITY', '数据保护合规', '涉及个人数据的服务应包含数据保护条款（处理目的、存储位置、删除义务）', 'MISSING', '{"fields": ["dataProcessingPurpose", "dataStorageLocation", "dataDeletionObligation"]}', 'HIGH', 15),

-- IP
('PROC-IP-001', 'SERVICE_PROCUREMENT_V1', 'IP', '知识产权归属明确', '应明确服务过程中产生的知识产权归属', 'MISSING', '{"fields": ["ipOwnership"]}', 'MEDIUM', 10),
('PROC-IP-002', 'SERVICE_PROCUREMENT_V1', 'IP', '背景知识产权保护', '我方提供的背景知识产权不应因合同而被转让或许可', 'CONTAINS', '{"keywords": ["背景知识产权","pre-existing IP","保留","retain"]}', 'HIGH', 12),

-- Renewal
('PROC-REN-001', 'SERVICE_PROCUREMENT_V1', 'TERMINATION', '自动续签约束', '自动续签条款应要求提前通知且不得默认生效', 'SEMANTIC', '{"forbidden": ["默认续签","自动续约","视为续签"]}', 'HIGH', 15);

-- Standard clause seeds
INSERT IGNORE INTO contract_standard_clause (clause_type, title, content, semantic_elements, is_mandatory, negotiation_bottom_line) VALUES
('LIABILITY', '标准违约责任条款（服务采购）',
 '任何一方违反本合同约定，应赔偿因此给对方造成的直接损失。赔偿责任上限为合同总金额的100%。以下损失不在赔偿范围内：(a)间接损失；(b)利润损失；(c)数据丢失导致的损失。因第三方就服务成果提起的索赔，由服务提供方负责处理并承担全部责任。违约方在收到守约方书面通知后有30天宽限期进行补救。',
 '{"liabilityCapPct": 100, "indirectDamages": "excluded", "profitLoss": "excluded", "dataLoss": "excluded", "thirdPartyClaims": "providerResponsible", "curePeriodDays": 30}',
 1, '最低接受责任上限为合同金额的50%。如果对方坚持排除间接损失，可以用增加保险覆盖作为替代。'),

('PAYMENT', '标准付款条款（服务采购）',
 '服务费用按季度支付。每季度初乙方向甲方开具增值税专用发票，甲方在收到发票后30个工作日内支付当季费用。预付款不超过合同总额的30%。如果甲方逾期支付，每逾期一天按未付金额的万分之五支付违约金。',
 '{"advancePaymentPct": 30, "paymentFrequency": "quarterly", "invoiceType": "增值税专用发票", "paymentDaysAfterInvoice": 30, "latePaymentPenalty": "日万分之五"}',
 1, '预付款可谈至50%，但需对方提供等额银行保函。付款周期可谈至月度或半年度。'),

('ACCEPTANCE', '标准验收条款（服务采购）',
 '服务交付后，甲方在15个工作日内按照附件《服务水平协议》中的量化指标进行验收。验收标准包括但不限于：服务响应时间、问题解决率、服务可用性。如未达标，乙方应在10个工作日内免费整改。整改后仍不达标的，甲方有权按比例扣减服务费或解除合同。',
 '{"acceptancePeriodDays": 15, "slaMetrics": ["响应时间","解决率","可用性"], "remediationDays": 10, "slaPenalty": "按比例扣减服务费或解除合同"}',
 1, '验收期可谈至30天。SLA指标可根据服务类型调整，但必须保留量化标准和未达标后果。'),

('CONFIDENTIALITY', '标准保密条款（服务采购）',
 '双方对在合同履行过程中获知的对方商业秘密和机密信息承担保密义务。保密期限为合同终止后3年。以下信息不受保密义务约束：(a)已进入公共领域的信息；(b)接收方在披露前已合法持有的信息；(c)法律法规要求披露的信息。',
 '{"confidentialitySurvivalYears": 3, "exceptions": ["publicDomain","priorPossession","legalRequirement"]}',
 1, '保密期限可谈至2年，但不得低于合同履行期。');

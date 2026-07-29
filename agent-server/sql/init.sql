/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

DROP DATABASE IF EXISTS `atlasmind_agent`;
CREATE DATABASE IF NOT EXISTS `atlasmind_agent`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `atlasmind_agent`;

DROP TABLE IF EXISTS `agent_action`;
DROP TABLE IF EXISTS `agent_report`;
DROP TABLE IF EXISTS `agent_run_step`;
DROP TABLE IF EXISTS `agent_run`;
DROP TABLE IF EXISTS `project_evidence`;
DROP TABLE IF EXISTS `project_sync_job`;
DROP TABLE IF EXISTS `project_source`;
DROP TABLE IF EXISTS `agent_project_memory`;
DROP TABLE IF EXISTS `agent_project`;
DROP TABLE IF EXISTS `kb_eval_case`;
DROP TABLE IF EXISTS `kb_tool_call`;
DROP TABLE IF EXISTS `kb_retrieval_hit`;
DROP TABLE IF EXISTS `kb_retrieval_trace`;
DROP TABLE IF EXISTS `kb_qa_message`;
DROP TABLE IF EXISTS `kb_qa_session`;
DROP TABLE IF EXISTS `kb_notification`;
DROP TABLE IF EXISTS `kb_ingest_job`;
DROP TABLE IF EXISTS `kb_document_chunk`;
DROP TABLE IF EXISTS `kb_document`;
DROP TABLE IF EXISTS `kb_space`;
DROP TABLE IF EXISTS `sys_setting`;
DROP TABLE IF EXISTS `t_operation_log`;
DROP TABLE IF EXISTS `t_user`;

CREATE TABLE `t_user` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `username` VARCHAR(50) NOT NULL,
  `password` VARCHAR(255) NOT NULL,
  `nickname` VARCHAR(50) DEFAULT NULL,
  `avatar` VARCHAR(255) DEFAULT NULL,
  `email` VARCHAR(100) DEFAULT NULL,
  `bio` VARCHAR(255) DEFAULT NULL,
  `social_links` TEXT COMMENT 'JSON social links',
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `t_operation_log` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `username` VARCHAR(50) DEFAULT NULL,
  `ip` VARCHAR(45) DEFAULT NULL,
  `operation` VARCHAR(100) DEFAULT NULL,
  `type` VARCHAR(20) DEFAULT NULL,
  `method_name` VARCHAR(200) DEFAULT NULL,
  `args` TEXT,
  `execution_time` BIGINT DEFAULT NULL,
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `sys_setting` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `setting_key` VARCHAR(100) NOT NULL,
  `setting_value` VARCHAR(500) NOT NULL,
  `value_type` VARCHAR(20) NOT NULL DEFAULT 'STRING',
  `description` VARCHAR(255) DEFAULT NULL,
  `editable` TINYINT DEFAULT 1,
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `update_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_setting_key` (`setting_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `kb_space` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(100) NOT NULL,
  `description` VARCHAR(500) DEFAULT NULL,
  `icon` VARCHAR(50) DEFAULT NULL,
  `color` VARCHAR(30) DEFAULT NULL,
  `sort` INT DEFAULT 0,
  `enabled` TINYINT DEFAULT 1,
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `update_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted` TINYINT DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `idx_enabled_deleted` (`enabled`,`deleted`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `kb_document` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `space_id` BIGINT NOT NULL,
  `title` VARCHAR(200) NOT NULL,
  `file_name` VARCHAR(255) NOT NULL,
  `file_type` VARCHAR(20) NOT NULL,
  `file_size` BIGINT DEFAULT 0,
  `file_path` VARCHAR(500) NOT NULL,
  `status` VARCHAR(30) DEFAULT 'UPLOADED',
  `parse_mode` VARCHAR(20) DEFAULT 'OCR',
  `chunk_count` INT DEFAULT 0,
  `embedding_model` VARCHAR(100) DEFAULT NULL,
  `embedding_dim` INT DEFAULT 2560,
  `index_name` VARCHAR(100) DEFAULT 'kb_chunks',
  `last_index_time` DATETIME DEFAULT NULL,
  `error_message` TEXT,
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `update_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted` TINYINT DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `idx_space_status` (`space_id`,`status`),
  KEY `idx_deleted` (`deleted`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `kb_document_chunk` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `document_id` BIGINT NOT NULL,
  `space_id` BIGINT NOT NULL,
  `chunk_index` INT NOT NULL,
  `section_title` VARCHAR(255) DEFAULT NULL,
  `source_page` INT DEFAULT NULL,
  `chunk_text` LONGTEXT NOT NULL,
  `char_count` INT DEFAULT 0,
  `token_count` INT DEFAULT 0,
  `embedding_status` VARCHAR(30) DEFAULT 'PENDING',
  `index_status` VARCHAR(30) DEFAULT 'PENDING',
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `update_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted` TINYINT DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `idx_document` (`document_id`),
  KEY `idx_space_document` (`space_id`,`document_id`),
  KEY `idx_deleted` (`deleted`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `kb_ingest_job` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `document_id` BIGINT NOT NULL,
  `job_type` VARCHAR(30) NOT NULL DEFAULT 'IMPORT',
  `status` VARCHAR(30) NOT NULL DEFAULT 'PENDING',
  `progress` INT DEFAULT 0,
  `message` VARCHAR(500) DEFAULT NULL,
  `error_message` TEXT,
  `started_at` DATETIME DEFAULT NULL,
  `finished_at` DATETIME DEFAULT NULL,
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `update_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_document` (`document_id`),
  KEY `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `kb_notification` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `type` VARCHAR(50) NOT NULL,
  `title` VARCHAR(200) NOT NULL,
  `content` VARCHAR(1000) DEFAULT NULL,
  `related_type` VARCHAR(30) DEFAULT NULL,
  `related_id` BIGINT DEFAULT NULL,
  `read_status` TINYINT DEFAULT 0,
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_read_create` (`read_status`,`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `kb_qa_session` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `source` VARCHAR(30) DEFAULT 'FRONT',
  `scope` VARCHAR(50) DEFAULT 'GLOBAL',
  `owner_token` VARCHAR(64) NOT NULL,
  `space_id` BIGINT DEFAULT NULL,
  `document_id` BIGINT DEFAULT NULL,
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `kb_qa_message` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `session_id` BIGINT NOT NULL,
  `role` VARCHAR(20) NOT NULL,
  `content` LONGTEXT NOT NULL,
  `model` VARCHAR(100) DEFAULT NULL,
  `latency_ms` BIGINT DEFAULT NULL,
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_session` (`session_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `kb_retrieval_trace` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `message_id` BIGINT NOT NULL,
  `query` TEXT NOT NULL,
  `retrieval_type` VARCHAR(50) DEFAULT NULL,
  `top_k` INT DEFAULT 5,
  `latency_ms` BIGINT DEFAULT NULL,
  `fallback_reason` VARCHAR(500) DEFAULT NULL,
  `hit_count` INT DEFAULT 0,
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_message` (`message_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `kb_retrieval_hit` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `trace_id` BIGINT NOT NULL,
  `source_type` VARCHAR(30) NOT NULL,
  `source_id` BIGINT NOT NULL,
  `chunk_id` BIGINT DEFAULT NULL,
  `title` VARCHAR(255) DEFAULT NULL,
  `score` DOUBLE DEFAULT 0,
  `snippet` TEXT,
  `rank_no` INT DEFAULT 0,
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_trace` (`trace_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `kb_tool_call` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `trace_id` BIGINT NOT NULL,
  `name` VARCHAR(100) NOT NULL,
  `status` VARCHAR(30) NOT NULL,
  `latency_ms` BIGINT DEFAULT 0,
  `input_summary` VARCHAR(1000) DEFAULT NULL,
  `output_summary` VARCHAR(1000) DEFAULT NULL,
  `error_message` TEXT,
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_trace` (`trace_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `kb_eval_case` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `question` VARCHAR(1000) NOT NULL,
  `expected_source_type` VARCHAR(30) DEFAULT NULL,
  `expected_source_id` BIGINT DEFAULT NULL,
  `expected_keywords` VARCHAR(1000) DEFAULT NULL,
  `expected_points` TEXT,
  `enabled` TINYINT DEFAULT 1,
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `update_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `agent_project` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(160) NOT NULL,
  `project_key` VARCHAR(60) NOT NULL,
  `description` VARCHAR(1000) DEFAULT NULL,
  `repository_type` VARCHAR(30) NOT NULL DEFAULT 'GITHUB',
  `repository_url` VARCHAR(500) DEFAULT NULL,
  `default_branch` VARCHAR(120) DEFAULT 'main',
  `business_scope` VARCHAR(1000) DEFAULT NULL,
  `release_target` VARCHAR(120) DEFAULT NULL,
  `current_milestone` VARCHAR(200) DEFAULT NULL,
  `team_size` INT DEFAULT NULL,
  `tech_stack` VARCHAR(500) DEFAULT NULL,
  `health_status` VARCHAR(30) DEFAULT 'UNKNOWN',
  `health_score` INT DEFAULT 0,
  `last_run_id` BIGINT DEFAULT NULL,
  `last_run_at` DATETIME DEFAULT NULL,
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `update_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted` TINYINT DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_project_key` (`project_key`),
  KEY `idx_project_status` (`health_status`,`deleted`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `agent_project_memory` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `project_id` BIGINT NOT NULL,
  `memory_type` VARCHAR(30) NOT NULL,
  `title` VARCHAR(200) NOT NULL,
  `content` TEXT NOT NULL,
  `source_type` VARCHAR(40) DEFAULT NULL,
  `source_id` VARCHAR(120) DEFAULT NULL,
  `confirmed` TINYINT DEFAULT 0,
  `confirmed_by` VARCHAR(100) DEFAULT NULL,
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `update_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_project_memory` (`project_id`,`memory_type`,`confirmed`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `project_source` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `project_id` BIGINT NOT NULL,
  `source_type` VARCHAR(30) NOT NULL DEFAULT 'GITHUB',
  `source_url` VARCHAR(500) NOT NULL,
  `default_branch` VARCHAR(120) DEFAULT 'main',
  `status` VARCHAR(30) NOT NULL DEFAULT 'PENDING',
  `last_sync_job_id` BIGINT DEFAULT NULL,
  `last_sync_at` DATETIME DEFAULT NULL,
  `last_error` TEXT,
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `update_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_project_source_url` (`project_id`,`source_url`),
  KEY `idx_project_source` (`project_id`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `project_sync_job` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `project_id` BIGINT NOT NULL,
  `source_id` BIGINT DEFAULT NULL,
  `sync_type` VARCHAR(30) NOT NULL DEFAULT 'MANUAL',
  `status` VARCHAR(30) NOT NULL DEFAULT 'RUNNING',
  `progress` INT DEFAULT 0,
  `message` VARCHAR(500) DEFAULT NULL,
  `counters_json` LONGTEXT,
  `error_message` TEXT,
  `started_at` DATETIME DEFAULT NULL,
  `finished_at` DATETIME DEFAULT NULL,
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `update_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_project_sync_job` (`project_id`,`create_time`),
  KEY `idx_sync_job_status` (`status`,`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `project_evidence` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `project_id` BIGINT NOT NULL,
  `source_id` BIGINT DEFAULT NULL,
  `source_type` VARCHAR(30) NOT NULL DEFAULT 'GITHUB',
  `object_type` VARCHAR(40) NOT NULL,
  `title` VARCHAR(260) NOT NULL,
  `source_ref` VARCHAR(260) DEFAULT NULL,
  `source_url` VARCHAR(700) DEFAULT NULL,
  `content_snippet` TEXT,
  `raw_json` LONGTEXT,
  `evidence_hash` VARCHAR(64) NOT NULL,
  `confidence_score` DECIMAL(5,4) DEFAULT 0.8000,
  `observed_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `update_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_project_evidence_hash` (`project_id`,`evidence_hash`),
  KEY `idx_project_evidence_type` (`project_id`,`object_type`,`update_time`),
  KEY `idx_project_evidence_source` (`source_id`,`object_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `agent_run` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `project_id` BIGINT NOT NULL,
  `run_type` VARCHAR(40) NOT NULL DEFAULT 'HEALTH_ANALYSIS',
  `trigger_type` VARCHAR(30) NOT NULL DEFAULT 'MANUAL',
  `question` VARCHAR(1000) DEFAULT NULL,
  `status` VARCHAR(40) NOT NULL DEFAULT 'CREATED',
  `progress` INT DEFAULT 0,
  `current_step` VARCHAR(120) DEFAULT NULL,
  `error_message` TEXT,
  `started_at` DATETIME DEFAULT NULL,
  `finished_at` DATETIME DEFAULT NULL,
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `update_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_project_run` (`project_id`,`create_time`),
  KEY `idx_run_status` (`status`,`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `agent_run_step` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `run_id` BIGINT NOT NULL,
  `step_order` INT NOT NULL,
  `role_name` VARCHAR(80) NOT NULL,
  `step_name` VARCHAR(120) NOT NULL,
  `status` VARCHAR(30) NOT NULL DEFAULT 'PENDING',
  `evidence_summary` VARCHAR(1000) DEFAULT NULL,
  `latency_ms` BIGINT DEFAULT 0,
  `started_at` DATETIME DEFAULT NULL,
  `finished_at` DATETIME DEFAULT NULL,
  `error_message` TEXT,
  PRIMARY KEY (`id`),
  KEY `idx_run_step` (`run_id`,`step_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `agent_report` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `project_id` BIGINT NOT NULL,
  `run_id` BIGINT NOT NULL,
  `title` VARCHAR(240) NOT NULL,
  `summary` TEXT,
  `health_status` VARCHAR(30) DEFAULT NULL,
  `health_score` INT DEFAULT 0,
  `dimensions_json` LONGTEXT,
  `risks_json` LONGTEXT,
  `plan_json` LONGTEXT,
  `citations_json` LONGTEXT,
  `report_markdown` LONGTEXT,
  `status` VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `update_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_report_run` (`run_id`),
  KEY `idx_project_report` (`project_id`,`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `agent_action` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `project_id` BIGINT NOT NULL,
  `run_id` BIGINT NOT NULL,
  `action_type` VARCHAR(50) NOT NULL,
  `status` VARCHAR(30) NOT NULL DEFAULT 'PENDING_APPROVAL',
  `title` VARCHAR(240) NOT NULL,
  `payload_json` LONGTEXT,
  `external_id` VARCHAR(120) DEFAULT NULL,
  `approved_by` VARCHAR(100) DEFAULT NULL,
  `approved_at` DATETIME DEFAULT NULL,
  `executed_at` DATETIME DEFAULT NULL,
  `result_json` LONGTEXT,
  `error_message` TEXT,
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP,
  `update_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_run_action` (`run_id`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO `t_user` (`id`, `username`, `password`, `nickname`, `avatar`, `email`, `bio`, `social_links`, `create_time`) VALUES
(1, 'admin', '$2a$10$nDKVFOBuRX8T5a6nKXRtXusB67trjNEZO0sJoWoEq1M8lGV0BD3r.', 'AtlasMind Admin', NULL, 'admin@atlasmind.local', 'Enterprise Agent workspace administrator', '[]', NOW());

INSERT INTO `sys_setting` (`id`, `setting_key`, `setting_value`, `value_type`, `description`, `editable`, `create_time`, `update_time`) VALUES
(1, 'ai.retrieval.top-k', '5', 'INTEGER', 'Default AI retrieval topK', 1, NOW(), NOW()),
(2, 'ai.retrieval.max-top-k', '10', 'INTEGER', 'Maximum AI retrieval topK', 1, NOW(), NOW()),
(3, 'ai.enabled', 'true', 'BOOLEAN', 'Enable front-end AI assistant', 1, NOW(), NOW());

INSERT INTO `kb_space` (`id`, `name`, `description`, `icon`, `color`, `sort`, `enabled`, `create_time`, `update_time`, `deleted`) VALUES
(1, 'Engineering Knowledge', 'API docs, deployment guides, technical designs, and incident reviews', 'code', '#2563eb', 1, 1, NOW(), NOW(), 0),
(2, 'Business Process', 'Process documents, SOPs, FAQs, and training materials', 'book-open', '#10b981', 2, 1, NOW(), NOW(), 0),
(3, 'Project Delivery', 'Requirements, weekly reports, meeting notes, and acceptance materials', 'briefcase', '#f59e0b', 3, 1, NOW(), NOW(), 0);

INSERT INTO `agent_project`
(`id`, `name`, `project_key`, `description`, `repository_type`, `repository_url`, `default_branch`, `business_scope`, `release_target`, `current_milestone`, `team_size`, `tech_stack`, `health_status`, `health_score`, `deleted`)
VALUES
(1, 'AtlasMind Agent Workbench', 'ATLASMIND', 'Enterprise R&D Agent system for project evidence, health reports, delivery planning, and approval-gated automation.', 'GITHUB', '', 'main', 'Internal software delivery and knowledge operations', 'Establish an auditable project Agent vertical slice', 'Agent evidence loop', 20, 'Spring Boot, Vue 3, MySQL, Redis, Elasticsearch', 'UNKNOWN', 0, 0);

INSERT INTO `agent_project_memory`
(`project_id`, `memory_type`, `title`, `content`, `source_type`, `source_id`, `confirmed`, `confirmed_by`)
VALUES
(1, 'PRODUCT_BOUNDARY', 'Single-team internal deployment', 'The first target deployment is one enterprise or R&D team, led by a tech lead or engineering manager.', 'MANUAL', 'seed', 1, 'init.sql'),
(1, 'CONNECTOR_ROADMAP', 'Reserved connector boundary', 'GitHub is implemented first. Local project scan, Jira, ZenTao, and CI/CD connectors are reserved for the next phases.', 'MANUAL', 'seed', 1, 'init.sql');

/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;
/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

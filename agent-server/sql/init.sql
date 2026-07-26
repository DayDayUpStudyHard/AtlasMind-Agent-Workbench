
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

/*!40000 DROP DATABASE IF EXISTS `atlasmind_agent`*/;

CREATE DATABASE /*!32312 IF NOT EXISTS*/ `atlasmind_agent` /*!40100 DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci */ /*!80016 DEFAULT ENCRYPTION='N' */;

USE `atlasmind_agent`;
DROP TABLE IF EXISTS `kb_document`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `kb_document` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `space_id` bigint NOT NULL,
  `title` varchar(200) NOT NULL,
  `file_name` varchar(255) NOT NULL,
  `file_type` varchar(20) NOT NULL,
  `file_size` bigint DEFAULT '0',
  `file_path` varchar(500) NOT NULL,
  `status` varchar(30) DEFAULT 'UPLOADED',
  `parse_mode` varchar(20) DEFAULT 'OCR',
  `chunk_count` int DEFAULT '0',
  `embedding_model` varchar(100) DEFAULT NULL,
  `embedding_dim` int DEFAULT '1536',
  `index_name` varchar(100) DEFAULT 'kb_chunks',
  `last_index_time` datetime DEFAULT NULL,
  `error_message` text,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted` tinyint DEFAULT '0',
  PRIMARY KEY (`id`),
  KEY `idx_space_status` (`space_id`,`status`),
  KEY `idx_deleted` (`deleted`)
) ENGINE=InnoDB AUTO_INCREMENT=9 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `kb_document_chunk`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `kb_document_chunk` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `document_id` bigint NOT NULL,
  `space_id` bigint NOT NULL,
  `chunk_index` int NOT NULL,
  `section_title` varchar(255) DEFAULT NULL,
  `source_page` int DEFAULT NULL,
  `chunk_text` longtext NOT NULL,
  `char_count` int DEFAULT '0',
  `token_count` int DEFAULT '0',
  `embedding_status` varchar(30) DEFAULT 'PENDING',
  `index_status` varchar(30) DEFAULT 'PENDING',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted` tinyint DEFAULT '0',
  PRIMARY KEY (`id`),
  KEY `idx_document` (`document_id`),
  KEY `idx_space_document` (`space_id`,`document_id`),
  KEY `idx_deleted` (`deleted`)
) ENGINE=InnoDB AUTO_INCREMENT=1661 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `kb_eval_case`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `kb_eval_case` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `question` varchar(1000) NOT NULL,
  `expected_source_type` varchar(30) DEFAULT NULL,
  `expected_source_id` bigint DEFAULT NULL,
  `expected_keywords` varchar(1000) DEFAULT NULL,
  `expected_points` text,
  `enabled` tinyint DEFAULT '1',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `kb_ingest_job`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `kb_ingest_job` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `document_id` bigint NOT NULL,
  `job_type` varchar(30) NOT NULL DEFAULT 'IMPORT',
  `status` varchar(30) NOT NULL DEFAULT 'PENDING',
  `progress` int DEFAULT '0',
  `message` varchar(500) DEFAULT NULL,
  `error_message` text,
  `started_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_document` (`document_id`),
  KEY `idx_status` (`status`)
) ENGINE=InnoDB AUTO_INCREMENT=29 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `kb_notification`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `kb_notification` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `type` varchar(50) NOT NULL,
  `title` varchar(200) NOT NULL,
  `content` varchar(1000) DEFAULT NULL,
  `related_type` varchar(30) DEFAULT NULL,
  `related_id` bigint DEFAULT NULL,
  `read_status` tinyint DEFAULT '0',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_read_create` (`read_status`,`create_time`)
) ENGINE=InnoDB AUTO_INCREMENT=29 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `kb_qa_message`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `kb_qa_message` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `session_id` bigint NOT NULL,
  `role` varchar(20) NOT NULL,
  `content` longtext NOT NULL,
  `model` varchar(100) DEFAULT NULL,
  `latency_ms` bigint DEFAULT NULL,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_session` (`session_id`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `kb_qa_session`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `kb_qa_session` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `source` varchar(30) DEFAULT 'FRONT',
  `scope` varchar(50) DEFAULT 'GLOBAL',
  `owner_token` varchar(64) NOT NULL,
  `space_id` bigint DEFAULT NULL,
  `document_id` bigint DEFAULT NULL,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `kb_retrieval_hit`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `kb_retrieval_hit` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `trace_id` bigint NOT NULL,
  `source_type` varchar(30) NOT NULL,
  `source_id` bigint NOT NULL,
  `chunk_id` bigint DEFAULT NULL,
  `title` varchar(255) DEFAULT NULL,
  `score` double DEFAULT '0',
  `snippet` text,
  `rank_no` int DEFAULT '0',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_trace` (`trace_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `kb_retrieval_trace`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `kb_retrieval_trace` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `message_id` bigint NOT NULL,
  `query` text NOT NULL,
  `retrieval_type` varchar(50) DEFAULT NULL,
  `top_k` int DEFAULT '5',
  `latency_ms` bigint DEFAULT NULL,
  `fallback_reason` varchar(500) DEFAULT NULL,
  `hit_count` int DEFAULT '0',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_message` (`message_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `kb_space`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `kb_space` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `name` varchar(100) NOT NULL,
  `description` varchar(500) DEFAULT NULL,
  `icon` varchar(50) DEFAULT NULL,
  `color` varchar(30) DEFAULT NULL,
  `sort` int DEFAULT '0',
  `enabled` tinyint DEFAULT '1',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted` tinyint DEFAULT '0',
  PRIMARY KEY (`id`),
  KEY `idx_enabled_deleted` (`enabled`,`deleted`)
) ENGINE=InnoDB AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `sys_setting`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `sys_setting` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `setting_key` varchar(100) NOT NULL,
  `setting_value` varchar(500) NOT NULL,
  `value_type` varchar(20) NOT NULL DEFAULT 'STRING',
  `description` varchar(255) DEFAULT NULL,
  `editable` tinyint DEFAULT '1',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_setting_key` (`setting_key`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `t_about`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `t_about` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `content` longtext COMMENT '关于页 Markdown 内容',
  `timeline` text COMMENT '个人时间线 JSON',
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `t_article`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `t_article` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `title` varchar(200) NOT NULL,
  `content` longtext,
  `summary` varchar(500) DEFAULT NULL,
  `category_id` bigint DEFAULT NULL,
  `cover` varchar(255) DEFAULT NULL,
  `is_top` int DEFAULT '0',
  `status` int DEFAULT '0',
  `visibility` varchar(20) NOT NULL DEFAULT 'PUBLIC',
  `view_count` int DEFAULT '0',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted` int DEFAULT '0',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=40 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `t_article_like`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `t_article_like` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `article_id` bigint NOT NULL,
  `user_ip` varchar(45) NOT NULL COMMENT '用户 IP（支持IPv6）',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_article_ip` (`article_id`,`user_ip`),
  KEY `idx_article_id` (`article_id`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `t_article_tag`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `t_article_tag` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `article_id` bigint NOT NULL,
  `tag_id` bigint NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `t_category`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `t_category` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `name` varchar(50) NOT NULL,
  `description` varchar(255) DEFAULT NULL,
  `sort` int DEFAULT '0',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=8 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `t_comment`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `t_comment` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `article_id` bigint DEFAULT NULL,
  `parent_id` bigint DEFAULT NULL COMMENT '父评论ID，NULL表示根评论',
  `reply_to` varchar(50) DEFAULT NULL COMMENT '回复目标用户昵称',
  `author` varchar(50) NOT NULL,
  `email` varchar(100) DEFAULT NULL,
  `content` text NOT NULL,
  `status` int DEFAULT '1',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=17 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `t_moment`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `t_moment` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `content` text NOT NULL COMMENT '动态公告内容',
  `image` varchar(255) DEFAULT NULL COMMENT '可选配图',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=25 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `t_operation_log`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `t_operation_log` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `username` varchar(50) DEFAULT NULL COMMENT '操作人',
  `ip` varchar(45) DEFAULT NULL COMMENT '操作IP',
  `operation` varchar(100) DEFAULT NULL COMMENT '操作描述',
  `type` varchar(20) DEFAULT NULL COMMENT '操作类型: CREATE/UPDATE/DELETE/OTHER',
  `method_name` varchar(200) DEFAULT NULL COMMENT '方法名',
  `args` text COMMENT '请求参数(截断)',
  `execution_time` bigint DEFAULT NULL COMMENT '执行耗时(ms)',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=40 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `t_tag`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `t_tag` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `name` varchar(50) NOT NULL,
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=14 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `t_user`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `t_user` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `username` varchar(50) NOT NULL,
  `password` varchar(255) NOT NULL,
  `nickname` varchar(50) DEFAULT NULL,
  `avatar` varchar(255) DEFAULT NULL,
  `email` varchar(100) DEFAULT NULL,
  `bio` varchar(255) DEFAULT NULL COMMENT '一句话简介',
  `social_links` text COMMENT '社交链接 JSON',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;


-- ============================================
-- AtlasMind Agent Workbench seed data
-- admin / admin123
-- ============================================

INSERT INTO `t_user` (`id`, `username`, `password`, `nickname`, `avatar`, `email`, `bio`, `social_links`, `create_time`) VALUES
(1, 'admin', '$2a$10$nDKVFOBuRX8T5a6nKXRtXusB67trjNEZO0sJoWoEq1M8lGV0BD3r.', 'AtlasMind Admin', NULL, 'admin@atlasmind.local', '企业知识工作台管理员', NULL, NOW());

INSERT INTO `sys_setting` (`id`, `setting_key`, `setting_value`, `value_type`, `description`, `editable`, `create_time`, `update_time`) VALUES
(1, 'ai.retrieval.top-k', '5', 'INTEGER', 'AI 默认检索数量', 1, NOW(), NOW()),
(2, 'ai.retrieval.max-top-k', '10', 'INTEGER', 'AI 最大检索数量', 1, NOW(), NOW()),
(3, 'ai.enabled', 'true', 'BOOLEAN', '是否启用用户端 AI', 1, NOW(), NOW());

INSERT INTO `kb_space` (`id`, `name`, `description`, `status`, `sort`, `create_time`, `update_time`) VALUES
(1, '研发知识库', '沉淀接口文档、部署手册、技术方案和故障复盘', 'ENABLED', 1, NOW(), NOW()),
(2, '业务制度库', '沉淀流程制度、SOP、FAQ 和培训材料', 'ENABLED', 2, NOW(), NOW()),
(3, '项目交付库', '沉淀需求说明、项目周报、会议纪要和验收材料', 'ENABLED', 3, NOW(), NOW());

INSERT INTO `t_category` (`id`, `name`, `description`, `sort`, `create_time`) VALUES
(1, '技术方案', '企业内部架构设计、接口设计和工程实践', 1, NOW()),
(2, '项目复盘', '项目交付过程中的问题、决策和经验沉淀', 2, NOW()),
(3, '流程制度', '团队协作、权限申请、发布上线等制度规范', 3, NOW());

INSERT INTO `t_tag` (`id`, `name`, `create_time`) VALUES
(1, 'RAG', NOW()),
(2, 'Agent', NOW()),
(3, 'Spring Boot', NOW()),
(4, 'KnowledgeOps', NOW()),
(5, 'Elasticsearch', NOW());

INSERT INTO `t_article` (`id`, `title`, `content`, `summary`, `category_id`, `cover`, `is_top`, `status`, `visibility`, `view_count`, `create_time`, `update_time`, `deleted`) VALUES
(1, '企业知识库本地启动流程', '# 企业知识库本地启动流程\n\n## 依赖服务\n\n本地开发需要启动 MySQL、Redis、Elasticsearch、Java 后端和 Python AI 服务。\n\n## 端口约定\n\n- Java 后端：18080\n- 管理端：15173\n- 知识门户：15174\n- Python AI 服务：18088\n\n## 启动顺序\n\n先启动基础设施，再启动后端服务，最后启动两个前端。', '企业知识库本地开发环境、端口和启动顺序说明。', 1, NULL, 1, 1, 'PUBLIC', 0, NOW(), NOW(), 0),
(2, 'RAG 问答权限规则', '# RAG 问答权限规则\n\nAtlasMind Agent Workbench 对知识源进行权限隔离。PUBLIC 内容可被普通用户检索；PRIVATE 和 DISABLED 内容不可进入 RAG 召回。\n\n管理员可以在后台查看召回记录、检索方式、TopK、耗时和引用来源。', '说明企业知识问答中的 PUBLIC/PRIVATE/DISABLED 权限边界。', 1, NULL, 0, 1, 'PUBLIC', 0, NOW(), NOW(), 0);

INSERT INTO `t_article_tag` (`article_id`, `tag_id`) VALUES
(1, 3), (1, 4), (2, 1), (2, 2);

INSERT INTO `t_about` (`id`, `content`, `timeline`, `update_time`) VALUES
(1, '# AtlasMind Agent Workbench\n\n面向企业内部知识资产管理、RAG 检索和 Agent 问答的智能工作台。\n\n## 核心能力\n\n- 文档上传与异步解析\n- 向量检索 + 关键词 fallback\n- Java AI Gateway\n- 权限隔离与问答日志\n- RAG 调试和导入任务可观测', '[]', NOW());
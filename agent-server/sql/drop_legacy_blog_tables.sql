-- Drop legacy blog/CMS tables after AtlasMind is migrated to enterprise Agent mode.
-- Execute with: mysql -u root -p atlasmind_agent < agent-server/sql/drop_legacy_blog_tables.sql

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS t_article_tag;
DROP TABLE IF EXISTS t_article_like;
DROP TABLE IF EXISTS t_article;
DROP TABLE IF EXISTS t_category;
DROP TABLE IF EXISTS t_tag;
DROP TABLE IF EXISTS t_comment;
DROP TABLE IF EXISTS t_moment;
DROP TABLE IF EXISTS t_about;

SET FOREIGN_KEY_CHECKS = 1;

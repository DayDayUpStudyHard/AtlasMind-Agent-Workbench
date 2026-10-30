package com.atlasmind.service;

import org.junit.jupiter.api.Assumptions;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.support.TransactionTemplate;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.containers.MySQLContainer;

import javax.sql.DataSource;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

/**
 * 为 flow 测试提供真实 MySQL。
 *
 * <p>优先级：
 * <ol>
 *   <li>环境变量 {@code FLOW_TEST_JDBC_URL}（{@code user}/{@code password} 可选）指向本地 MySQL；</li>
 *   <li>否则启动 Testcontainers MySQL 8.0；</li>
 *   <li>两者都不可用则跳过测试（不伪装通过）。</li>
 * </ol>
 * 之所以不用 H2：{@code pending_flag} 生成列与 JSON 列在 H2 下不保证兼容，
 * 而它们正是并发保障的核心（design §8 决策 12）。
 */
final class FlowTestDatabase implements AutoCloseable {

    private final MySQLContainer<?> container;
    private final DataSource dataSource;
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;

    private FlowTestDatabase(MySQLContainer<?> container, DataSource dataSource) {
        this.container = container;
        this.dataSource = dataSource;
        this.jdbc = new JdbcTemplate(dataSource);
        this.tx = new TransactionTemplate(new DataSourceTransactionManager(dataSource));
    }

    static FlowTestDatabase start() {
        MySQLContainer<?> container = null;
        DataSource ds;
        String override = System.getenv("FLOW_TEST_JDBC_URL");
        if (override != null && !override.isBlank()) {
            String user = envOr("FLOW_TEST_JDBC_USER", "root");
            String password = envOr("FLOW_TEST_JDBC_PASSWORD", "123456");
            ds = new DriverManagerDataSource(override, user, password);
        } else {
            Assumptions.assumeTrue(dockerAvailable(),
                    "跳过：本机无 Docker 且未设置 FLOW_TEST_JDBC_URL");
            container = new MySQLContainer<>("mysql:8.0")
                    .withDatabaseName("flow_test")
                    .withUsername("flow")
                    .withPassword("flow");
            container.start();
            ds = new DriverManagerDataSource(container.getJdbcUrl(), container.getUsername(),
                    container.getPassword());
        }
        FlowTestDatabase db = new FlowTestDatabase(container, ds);
        db.migrate();
        return db;
    }

    private static boolean dockerAvailable() {
        try {
            return DockerClientFactory.instance().isDockerAvailable();
        } catch (Throwable t) {
            return false;
        }
    }

    private static String envOr(String key, String fallback) {
        String v = System.getenv(key);
        return v == null || v.isBlank() ? fallback : v;
    }

    /** 执行仓库中的真实迁移 DDL（V041），确保测试的是实际上线脚本。 */
    private void migrate() {
        String sql = readMigration();
        String cleaned = String.join("\n", sql.lines()
                .filter(line -> !line.trim().startsWith("--"))
                .toList());
        for (String stmt : cleaned.split(";")) {
            String trimmed = stmt.trim();
            if (!trimmed.isEmpty()) {
                jdbc.execute(trimmed);
            }
        }
        for (String ddl : AUXILIARY_DDL) {
            jdbc.execute(ddl);
        }
    }

    private static String readMigration() {
        List<Path> candidates = List.of(
                Path.of("../tools/chat-assistant/backend/migrations/V041__contract_flow.sql"),
                Path.of("tools/chat-assistant/backend/migrations/V041__contract_flow.sql"),
                Path.of("../../tools/chat-assistant/backend/migrations/V041__contract_flow.sql"));
        for (Path candidate : candidates) {
            if (Files.exists(candidate)) {
                try {
                    return Files.readString(candidate, StandardCharsets.UTF_8);
                } catch (IOException e) {
                    throw new IllegalStateException("无法读取迁移脚本 " + candidate, e);
                }
            }
        }
        throw new IllegalStateException("找不到 V041__contract_flow.sql，测试工作目录="
                + Path.of(".").toAbsolutePath());
    }

    /** 流程服务直接依赖的业务表最小结构（一期已存在，这里只建测试所需列）。 */
    private static final List<String> AUXILIARY_DDL = List.of(
            """
            CREATE TABLE IF NOT EXISTS department (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(120) NOT NULL,
                code VARCHAR(60) NOT NULL,
                is_default TINYINT NOT NULL DEFAULT 0,
                deleted TINYINT NOT NULL DEFAULT 0,
                UNIQUE KEY uk_dept_code (code)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS t_user (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                role VARCHAR(16) NOT NULL DEFAULT 'USER',
                department_id BIGINT,
                status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
                UNIQUE KEY uk_user_name (username)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS contract_case (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                department_id BIGINT,
                creator_id BIGINT,
                maintainer_id BIGINT,
                status VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
                deleted TINYINT NOT NULL DEFAULT 0
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """,
            """
            CREATE TABLE IF NOT EXISTS contract_document (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                case_id BIGINT NOT NULL,
                version INT NOT NULL,
                content_hash VARCHAR(128),
                deleted TINYINT NOT NULL DEFAULT 0,
                UNIQUE KEY uk_doc_case_version (case_id, version)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """);

    JdbcTemplate jdbc() {
        return jdbc;
    }

    TransactionTemplate tx() {
        return tx;
    }

    DataSource dataSource() {
        return dataSource;
    }

    /** 每个测试前清空 flow 表，保留基础数据插入由测试自己完成。 */
    void reset() {
        for (String table : List.of("contract_flow_event", "contract_flow_claim",
                "contract_flow_withdraw", "contract_flow_node", "contract_sign_check",
                "contract_flow", "dept_approver", "flow_role_member",
                "contract_document", "contract_case", "t_user", "department")) {
            jdbc.execute("DELETE FROM " + table);
        }
    }

    @Override
    public void close() {
        if (container != null) {
            container.stop();
        }
    }
}

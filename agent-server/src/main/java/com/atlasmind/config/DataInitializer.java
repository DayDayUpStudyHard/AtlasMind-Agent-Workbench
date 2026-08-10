package com.atlasmind.config;

import cn.hutool.crypto.digest.BCrypt;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.atlasmind.entity.User;
import com.atlasmind.mapper.UserMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.CommandLineRunner;
import org.springframework.core.env.Environment;
import org.springframework.core.env.Profiles;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * Creates the default local administrator account when the database is empty.
 * Also ensures the default department (法务部) exists with idempotent upsert.
 */
@Component
@RequiredArgsConstructor
public class DataInitializer implements CommandLineRunner {

    private final UserMapper userMapper;
    private final JdbcTemplate jdbcTemplate;
    private final Environment environment;

    @Value("${atlasmind.bootstrap-admin.password:}")
    private String bootstrapAdminPassword;

    @Override
    public void run(String... args) {
        // Ensure default department exists (idempotent upsert)
        jdbcTemplate.update("""
                INSERT INTO department (name, code, is_default, description)
                VALUES ('法务部', 'LEGAL', 1, '默认部门（系统初始化）')
                ON DUPLICATE KEY UPDATE name=VALUES(name)
                """);

        // Get or infer the default department ID
        Long defaultDeptId = jdbcTemplate.queryForObject(
                "SELECT id FROM department WHERE is_default=1 LIMIT 1", Long.class);

        User existingAdmin = userMapper.selectOne(
                new LambdaQueryWrapper<User>().eq(User::getUsername, "admin"));
        boolean production = environment.acceptsProfiles(Profiles.of("prod"));
        if (production && (bootstrapAdminPassword == null
                || bootstrapAdminPassword.isBlank()
                || "admin123".equals(bootstrapAdminPassword))) {
            throw new IllegalStateException(
                    "BOOTSTRAP_ADMIN_PASSWORD must be set to a non-default value in production");
        }

        if (existingAdmin == null) {
            if (bootstrapAdminPassword == null || bootstrapAdminPassword.isBlank()) {
                throw new IllegalStateException("Bootstrap administrator password is not configured");
            }
            User admin = new User();
            admin.setUsername("admin");
            admin.setPassword(BCrypt.hashpw(bootstrapAdminPassword));
            admin.setNickname("AtlasMind Admin");
            admin.setEmail("admin@atlasmind.local");
            admin.setBio("Enterprise Agent workspace administrator");
            admin.setSocialLinks("[]");
            admin.setRole("ADMIN");
            admin.setDepartmentId(defaultDeptId);
            admin.setStatus("ACTIVE");
            userMapper.insert(admin);
        } else {
            if (production && BCrypt.checkpw("admin123", existingAdmin.getPassword())) {
                existingAdmin.setPassword(BCrypt.hashpw(bootstrapAdminPassword));
                userMapper.updateById(existingAdmin);
            }
            // Ensure existing admin is elevated and assigned to default department
            jdbcTemplate.update(
                "UPDATE t_user SET role='ADMIN', department_id=? WHERE username='admin' AND (role IS NULL OR role<>'ADMIN' OR department_id IS NULL)",
                defaultDeptId);
        }

        // Backfill missing quota rows for any existing users, especially legacy seed users.
        jdbcTemplate.update("""
                INSERT INTO user_quota (user_id, total_quota)
                SELECT u.id, 100
                FROM t_user u
                LEFT JOIN user_quota q ON q.user_id = u.id
                WHERE q.user_id IS NULL
                """);
    }
}

package com.atlasmind.config;

import cn.hutool.crypto.digest.BCrypt;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.atlasmind.entity.User;
import com.atlasmind.mapper.UserMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.CommandLineRunner;
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

        if (!userMapper.exists(new LambdaQueryWrapper<User>().eq(User::getUsername, "admin"))) {
            User admin = new User();
            admin.setUsername("admin");
            admin.setPassword(BCrypt.hashpw("admin123"));
            admin.setNickname("AtlasMind Admin");
            admin.setEmail("admin@atlasmind.local");
            admin.setBio("Enterprise Agent workspace administrator");
            admin.setSocialLinks("[]");
            admin.setRole("ADMIN");
            admin.setDepartmentId(defaultDeptId);
            admin.setStatus("ACTIVE");
            userMapper.insert(admin);
        } else {
            // Ensure existing admin is elevated and assigned to default department
            jdbcTemplate.update(
                "UPDATE t_user SET role='ADMIN', department_id=? WHERE username='admin' AND (role IS NULL OR role<>'ADMIN' OR department_id IS NULL)",
                defaultDeptId);
        }
    }
}

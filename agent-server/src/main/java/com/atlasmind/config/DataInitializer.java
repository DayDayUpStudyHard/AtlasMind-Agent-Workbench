package com.atlasmind.config;

import cn.hutool.crypto.digest.BCrypt;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.atlasmind.entity.User;
import com.atlasmind.mapper.UserMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;

/**
 * Creates the default local administrator account when the database is empty.
 */
@Component
@RequiredArgsConstructor
public class DataInitializer implements CommandLineRunner {

    private final UserMapper userMapper;

    @Override
    public void run(String... args) {
        if (!userMapper.exists(new LambdaQueryWrapper<User>().eq(User::getUsername, "admin"))) {
            User admin = new User();
            admin.setUsername("admin");
            admin.setPassword(BCrypt.hashpw("admin123"));
            admin.setNickname("AtlasMind Admin");
            admin.setEmail("admin@atlasmind.local");
            admin.setBio("Enterprise Agent workspace administrator");
            admin.setSocialLinks("[]");
            userMapper.insert(admin);
        }
    }
}

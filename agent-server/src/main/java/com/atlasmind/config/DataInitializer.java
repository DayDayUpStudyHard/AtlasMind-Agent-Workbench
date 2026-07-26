package com.atlasmind.config;

import cn.hutool.crypto.digest.BCrypt;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.atlasmind.entity.About;
import com.atlasmind.entity.User;
import com.atlasmind.mapper.AboutMapper;
import com.atlasmind.mapper.UserMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;

/**
 * 应用启动时初始化默认数据：管理员账号、关于页。
 * <p>
 * 实现 {@link CommandLineRunner}，在 Spring 容器就绪后执行。
 */
@Component
@RequiredArgsConstructor
public class DataInitializer implements CommandLineRunner {

    private final UserMapper userMapper;
    private final AboutMapper aboutMapper;

    @Override
    public void run(String... args) {
        if (!userMapper.exists(new LambdaQueryWrapper<User>().eq(User::getUsername, "admin"))) {
            User admin = new User();
            admin.setUsername("admin");
            admin.setPassword(BCrypt.hashpw("admin123"));
            admin.setNickname("AtlasMind");
            admin.setBio("记录思考与生活");
            admin.setSocialLinks("[{\"name\":\"GitHub\",\"url\":\"https://github.com\",\"icon\":\"github\"},{\"name\":\"邮箱\",\"url\":\"mailto:admin@atlasmind.local\",\"icon\":\"email\"}]");
            userMapper.insert(admin);
        }
        if (!aboutMapper.exists(new LambdaQueryWrapper<About>().eq(About::getId, 1L))) {
            About about = new About();
            about.setId(1L);
            about.setContent("# 关于我\n\n这里是企业知识资产管理与 Agent 问答工作台，用于沉淀研发文档、项目复盘、制度 SOP 和 FAQ。\n\n## 技术栈\n\n- **后端**: Spring Boot / MyBatis-Plus / Sa-Token\n- **前端**: Vue 3 / Naive UI / Element Plus\n- **数据库**: MySQL / Redis\n- **部署**: Docker / Nginx\n\n## 联系\n\n欢迎在知识门户中查看公开知识内容，或通过 AtlasMind AI 进行引用式问答。");
            about.setTimeline("[{\"year\":\"2024\",\"title\":\"创建 AtlasMind\",\"desc\":\"开始用 Spring Boot + Vue 3 搭建企业知识库与 Agent 系统\"},{\"year\":\"2023\",\"title\":\"学习全栈开发\",\"desc\":\"系统学习 Spring Boot 和 Vue 3 技术栈\"}]");
            about.setUpdateTime(LocalDateTime.now());
            aboutMapper.insert(about);
        }
    }
}

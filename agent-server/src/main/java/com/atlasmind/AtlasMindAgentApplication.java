package com.atlasmind;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * 企业知识工作台启动入口。
 * <p>
 * {@code @EnableAsync} 启用异步方法支持；{@code @EnableScheduling} 启用定时任务
 * （操作日志 Stream 消费者轮询）。
 */
@EnableAsync
@EnableScheduling
@SpringBootApplication
public class AtlasMindAgentApplication {
    public static void main(String[] args) {
        SpringApplication.run(AtlasMindAgentApplication.class, args);
    }
}

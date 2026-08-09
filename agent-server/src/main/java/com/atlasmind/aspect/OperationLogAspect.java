package com.atlasmind.aspect;

import cn.dev33.satoken.stp.StpUtil;
import com.atlasmind.annotation.OperationLog;
import jakarta.servlet.http.HttpServletRequest;
import lombok.extern.slf4j.Slf4j;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.aspectj.lang.reflect.MethodSignature;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.lang.reflect.Method;
import java.time.LocalDateTime;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 操作日志切面 — 记录后台管理操作到日志文件和 Redis Stream。
 *
 * <h3>架构演进</h3>
 * <pre>
 *  旧: 切面 → OperationLogService.save() → @Async → MySQL 直接写入
 *  新: 切面 → Redis Stream (oplog:stream) → OperationLogConsumer → 批量写入 MySQL
 * </pre>
 *
 * <h3>Stream 优势</h3>
 * <ul>
 *   <li><b>解耦</b>：请求线程只做 Stream 写入（轻量），不再依赖线程池</li>
 *   <li><b>削峰</b>：Stream 作为缓冲区，高并发时消息积压不丢失</li>
 *   <li><b>可重放</b>：消费者组 + ACK 机制，消息未确认可重新消费</li>
 *   <li><b>可扩展</b>：多实例部署时消费者组自动负载均衡</li>
 * </ul>
 *
 * <p>
 * 日志格式：{@code [操作类型] 操作描述 | 用户: xxx | IP: xxx | 参数: [...] | 耗时: xxxms}
 */
@Slf4j
@Aspect
@Component
public class OperationLogAspect {

    private static final String STREAM_KEY = "oplog:stream";

    private final StringRedisTemplate redisTemplate;

    public OperationLogAspect(StringRedisTemplate redisTemplate) {
        this.redisTemplate = redisTemplate;
    }

    @Around("@annotation(com.atlasmind.annotation.OperationLog)")
    public Object around(ProceedingJoinPoint joinPoint) throws Throwable {
        long start = System.currentTimeMillis();

        // 获取注解信息
        MethodSignature signature = (MethodSignature) joinPoint.getSignature();
        Method method = signature.getMethod();
        OperationLog annotation = method.getAnnotation(OperationLog.class);

        // 获取操作人
        String username = getLoginUsername();

        // 获取客户端 IP
        String ip = getClientIp();

        // Filter sensitive fields and truncate
        String args = Arrays.toString(joinPoint.getArgs());
        args = maskSensitive(args);
        if (args.length() > 2000) {
            args = args.substring(0, 2000) + "...";
        }

        // 获取方法名
        String methodName = method.getDeclaringClass().getSimpleName() + "." + method.getName();

        // 执行原方法
        Object result = joinPoint.proceed();
        long elapsed = System.currentTimeMillis() - start;

        // 记录到日志文件（同步，即时可见）
        log.info("[{}] {} | 用户: {} | IP: {} | 参数: {} | 耗时: {}ms",
                annotation.type(), annotation.value(), username, ip, args, elapsed);

        // 推送到 Redis Stream（异步解耦，由 OperationLogConsumer 批量写入 DB）
        try {
            Map<String, String> fields = new LinkedHashMap<>();
            fields.put("username", username);
            fields.put("operatorId", String.valueOf(getLoginUserId()));
            fields.put("ip", ip);
            fields.put("operation", annotation.value());
            fields.put("type", annotation.type());
            fields.put("methodName", methodName);
            fields.put("args", args);
            fields.put("executionTime", String.valueOf(elapsed));
            fields.put("createTime", LocalDateTime.now().toString());
            redisTemplate.opsForStream().add(STREAM_KEY, fields);
        } catch (Exception e) {
            log.warn("[OpLog] Redis Stream 写入失败: {}", e.getMessage());
        }

        return result;
    }

    private String getLoginUsername() {
        try {
            return (String) StpUtil.getLoginId();
        } catch (Exception e) {
            return "unknown";
        }
    }

    private long getLoginUserId() {
        try {
            return StpUtil.getLoginIdAsLong();
        } catch (Exception e) {
            return 0;
        }
    }

    /** Replace password/token values with *** to prevent sensitive data in logs. */
    private String maskSensitive(String args) {
        if (args == null) return "";
        return args
            .replaceAll("(?i)(password|token|refresh_token|secret|apiKey|accessKey)\\s*[=:]\\s*\"[^\"]*\"",
                         "$1=***")
            .replaceAll("(?i)(password|token|refresh_token|secret|apiKey|accessKey)\\s*[=:]\\s*[^,)}\\]\"]+",
                         "$1=***");
    }

    private String getClientIp() {
        ServletRequestAttributes attrs = (ServletRequestAttributes) RequestContextHolder.getRequestAttributes();
        if (attrs == null) return "unknown";
        HttpServletRequest request = attrs.getRequest();
        String ip = request.getHeader("X-Forwarded-For");
        if (ip == null || ip.isEmpty() || "unknown".equalsIgnoreCase(ip)) {
            ip = request.getHeader("X-Real-IP");
        }
        if (ip == null || ip.isEmpty() || "unknown".equalsIgnoreCase(ip)) {
            ip = request.getRemoteAddr();
        }
        return ip != null ? ip.split(",")[0].trim() : "unknown";
    }
}

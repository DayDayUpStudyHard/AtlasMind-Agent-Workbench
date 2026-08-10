package com.atlasmind.aspect;

import cn.dev33.satoken.stp.StpUtil;
import com.atlasmind.annotation.OperationLog;
import com.atlasmind.service.OperationLogService;
import jakarta.servlet.http.HttpServletRequest;
import lombok.extern.slf4j.Slf4j;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.aspectj.lang.reflect.MethodSignature;
import org.springframework.stereotype.Component;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.lang.reflect.Method;
import java.time.LocalDateTime;
import java.util.Arrays;

/**
 * 操作日志切面 — 记录后台管理操作到日志文件和 MySQL。
 *
 * <h3>写入路径</h3>
 * <pre>
 *  Controller @OperationLog → 本切面 → OperationLogService.save() → @Async → MySQL
 * </pre>
 *
 * <p>
 * 不再依赖 Redis Stream（Windows Redis 3.x 不支持 Stream 5.0+ 命令）。
 * 如需在生产环境（Linux Redis 7.x）启用 Stream 削峰，可通过配置开关切换
 * 为 Stream → Consumer 路径，同时关闭直写 DB 以避免重复。
 *
 * <p>
 * 日志格式：{@code [操作类型] 操作描述 | 用户: xxx | IP: xxx | 参数: [...] | 耗时: xxxms}
 */
@Slf4j
@Aspect
@Component
public class OperationLogAspect {

    private final OperationLogService operationLogService;

    public OperationLogAspect(OperationLogService operationLogService) {
        this.operationLogService = operationLogService;
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

        // 直写 DB（主路径，@Async 异步执行，不拖慢接口响应）
        saveToDatabase(username, ip, annotation, methodName, args, elapsed);

        return result;
    }

    /** 构造实体并通过 @Async 写入 MySQL，确保审计日志落库。 */
    private void saveToDatabase(String username, String ip, OperationLog annotation,
                                String methodName, String args, long elapsed) {
        try {
            com.atlasmind.entity.OperationLog entry = new com.atlasmind.entity.OperationLog();
            entry.setUsername(username);
            entry.setIp(ip);
            entry.setOperation(annotation.value());
            entry.setType(annotation.type());
            entry.setMethodName(methodName);
            entry.setArgs(args);
            entry.setExecutionTime(elapsed);
            entry.setOperatorId(getLoginUserId());
            entry.setCreateTime(LocalDateTime.now());
            operationLogService.save(entry);
        } catch (Exception ex) {
            log.error("[OpLog] 异步写入失败: {}", ex.getMessage());
        }
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

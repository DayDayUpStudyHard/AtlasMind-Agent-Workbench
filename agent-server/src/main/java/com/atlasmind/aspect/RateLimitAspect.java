package com.atlasmind.aspect;

import com.atlasmind.annotation.RateLimit;
import com.atlasmind.common.Result;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.stereotype.Component;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.util.concurrent.TimeUnit;

/**
 * 限流切面 — 基于 Redis INCR + EXPIRE 实现计数器限流。
 * <p>
 * 限流 key 格式：{@code rate_limit:接口路径:IP}。
 * 首次请求设置 key 并 +1，后续请求递增，超过限制返回 429。
 */
@Slf4j
@Aspect
@Component
@RequiredArgsConstructor
public class RateLimitAspect {

    private final RedisTemplate<String, Object> redisTemplate;

    @Around("@annotation(rateLimit)")
    public Object around(ProceedingJoinPoint joinPoint, RateLimit rateLimit) throws Throwable {
        // 构建限流 key
        String key = buildKey(joinPoint, rateLimit);

        // Redis INCR
        Long count = redisTemplate.opsForValue().increment(key, 1);
        if (count != null && count == 1) {
            // 首次请求设置过期时间
            redisTemplate.expire(key, rateLimit.window(), rateLimit.timeUnit());
        }

        // 检查是否超限
        if (count != null && count > rateLimit.limit()) {
            log.warn("接口限流触发: key={}, count={}, limit={}", key, count, rateLimit.limit());
            return Result.fail(429, rateLimit.message());
        }

        return joinPoint.proceed();
    }

    /**
     * 构建限流 key：方法名 + IP
     */
    private String buildKey(ProceedingJoinPoint joinPoint, RateLimit rateLimit) {
        String prefix = rateLimit.key().isEmpty()
                ? joinPoint.getSignature().toShortString()
                : rateLimit.key();
        String ip = getClientIp();
        return "rate_limit:" + prefix + ":" + ip;
    }

    /**
     * 获取客户端真实 IP（考虑反向代理）
     */
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

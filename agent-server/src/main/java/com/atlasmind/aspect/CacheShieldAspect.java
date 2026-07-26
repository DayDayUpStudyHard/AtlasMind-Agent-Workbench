package com.atlasmind.aspect;

import com.atlasmind.annotation.CacheShield;
import com.atlasmind.annotation.CacheShieldEvict;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.aspectj.lang.reflect.MethodSignature;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.DefaultParameterNameDiscoverer;
import org.springframework.core.ParameterNameDiscoverer;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.expression.EvaluationContext;
import org.springframework.expression.ExpressionParser;
import org.springframework.expression.spel.standard.SpelExpressionParser;
import org.springframework.expression.spel.support.StandardEvaluationContext;
import org.springframework.stereotype.Component;

import java.lang.reflect.Method;
import java.util.Set;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;

/**
 * 缓存防护切面 — 拦截 {@link CacheShield} 和 {@link CacheShieldEvict} 注解。
 *
 * <h3>三层防护机制</h3>
 * <table>
 *   <tr><th>问题</th><th>方案</th><th>实现</th></tr>
 *   <tr><td>缓存穿透</td><td>缓存空值</td><td>DB 返回 null → 缓存特殊标记 {@code __NULL__}，短 TTL 5min</td></tr>
 *   <tr><td>缓存雪崩</td><td>随机 TTL</td><td>实际 TTL = 基础值 + random(0, 浮动值)，防批量同时过期</td></tr>
 *   <tr><td>缓存击穿</td><td>分布式互斥锁</td><td>Redisson tryLock → 双检 → 单线程重建 → 释放锁</td></tr>
 * </table>
 *
 * <h3>与 Spring Cache 的关系</h3>
 * 本切面直接操作 RedisTemplate，完全替代 Spring {@code @Cacheable/@CacheEvict}。
 * 使用 {@code @CacheShield} 的方法不应再叠加 {@code @Cacheable}。
 */
@Aspect
@Component
public class CacheShieldAspect {

    private static final Logger log = LoggerFactory.getLogger(CacheShieldAspect.class);
    private static final String NULL_MARKER = "__CACHE_NULL__";
    private static final ParameterNameDiscoverer paramDiscoverer = new DefaultParameterNameDiscoverer();
    private static final ExpressionParser parser = new SpelExpressionParser();

    private final RedisTemplate<String, Object> redisTemplate;
    private final RedissonClient redissonClient;

    public CacheShieldAspect(RedisTemplate<String, Object> redisTemplate, RedissonClient redissonClient) {
        this.redisTemplate = redisTemplate;
        this.redissonClient = redissonClient;
    }

    // ═══════════════════════ @CacheShield — 读缓存 ═══════════════════════

    @Around("@annotation(cacheShield)")
    public Object shield(ProceedingJoinPoint pjp, CacheShield cacheShield) throws Throwable {
        String cacheKey = buildCacheKey(cacheShield.value(), cacheShield.key(), pjp);
        String lockKey = "lock:" + cacheKey;

        // 1. 查询缓存
        Object cached = redisTemplate.opsForValue().get(cacheKey);
        if (cached != null) {
            log.debug("[CacheShield] 命中: {}", cacheKey);
            return NULL_MARKER.equals(cached) ? null : cached;  // 穿透保护：命中空值标记返回 null
        }

        log.debug("[CacheShield] 未命中: {} → 加锁重建", cacheKey);

        // 2. 获取分布式锁（防击穿）
        RLock lock = redissonClient.getLock(lockKey);
        try {
            if (lock.tryLock(3, 30, TimeUnit.SECONDS)) {
                try {
                    // 3. 双检缓存（其他线程可能已重建）
                    cached = redisTemplate.opsForValue().get(cacheKey);
                    if (cached != null) {
                        log.debug("[CacheShield] 双检命中: {}", cacheKey);
                        return NULL_MARKER.equals(cached) ? null : cached;
                    }

                    // 4. 执行原方法查 DB
                    Object result = pjp.proceed();

                    // 5. 写入缓存
                    if (result == null) {
                        // 防穿透：缓存空值标记
                        redisTemplate.opsForValue().set(cacheKey, NULL_MARKER,
                                cacheShield.nullTtl(), cacheShield.unit());
                        log.debug("[CacheShield] 空值缓存: {} ({} {})",
                                cacheKey, cacheShield.nullTtl(), cacheShield.unit());
                    } else {
                        // 防雪崩：TTL 叠加随机浮动
                        long variance = cacheShield.ttlVariance() > 0
                                ? ThreadLocalRandom.current().nextLong(cacheShield.ttlVariance() + 1)
                                : 0;
                        long actualTtl = cacheShield.ttl() + variance;
                        redisTemplate.opsForValue().set(cacheKey, result, actualTtl, cacheShield.unit());
                        log.debug("[CacheShield] 缓存写入: {} (TTL={}+{} {})",
                                cacheKey, cacheShield.ttl(), variance, cacheShield.unit());
                    }
                    return result;
                } finally {
                    if (lock.isHeldByCurrentThread()) {
                        lock.unlock();
                    }
                }
            } else {
                // 6. 没抢到锁 → 短暂等待后重试缓存（避免惊群）
                log.debug("[CacheShield] 等待锁: {}", lockKey);
                TimeUnit.MILLISECONDS.sleep(100);
                cached = redisTemplate.opsForValue().get(cacheKey);
                if (cached != null) {
                    return NULL_MARKER.equals(cached) ? null : cached;
                }
                // 极端情况：锁持有者异常未写入缓存，降级查 DB
                return pjp.proceed();
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return pjp.proceed();  // 中断降级
        }
    }

    // ═══════════════════════ @CacheShieldEvict — 清除缓存 ═══════════════════════

    @Around("@annotation(evict)")
    public Object evict(ProceedingJoinPoint pjp, CacheShieldEvict evict) throws Throwable {
        try {
            return pjp.proceed();  // 先执行写操作
        } finally {
            if (evict.allEntries()) {
                // 全量清除：match 所有以 cacheName:: 开头的 key
                Set<String> keys = redisTemplate.keys(evict.value() + "::*");
                if (keys != null && !keys.isEmpty()) {
                    redisTemplate.delete(keys);
                    log.debug("[CacheShieldEvict] 批量清除: {} ({} keys)", evict.value(), keys.size());
                }
            } else {
                String cacheKey = buildCacheKey(evict.value(), evict.key(), pjp);
                redisTemplate.delete(cacheKey);
                log.debug("[CacheShieldEvict] 清除: {}", cacheKey);
            }
        }
    }

    // ═══════════════════════ 内部工具 ═══════════════════════

    /** 构造缓存 Key：{@code cacheName::resolvedKey} */
    String buildCacheKey(String cacheName, String keyExpr, ProceedingJoinPoint pjp) {
        return cacheName + "::" + resolveKey(keyExpr, pjp);
    }

    /** 解析 SpEL 表达式为字符串 */
    String resolveKey(String keyExpr, ProceedingJoinPoint pjp) {
        // 字面量（单引号包裹）直接去掉引号
        if (keyExpr.startsWith("'") && keyExpr.endsWith("'") && keyExpr.length() >= 2) {
            return keyExpr.substring(1, keyExpr.length() - 1);
        }

        // SpEL 表达式解析
        Method method = ((MethodSignature) pjp.getSignature()).getMethod();
        EvaluationContext context = new StandardEvaluationContext();
        String[] paramNames = paramDiscoverer.getParameterNames(method);
        Object[] args = pjp.getArgs();
        if (paramNames != null) {
            for (int i = 0; i < paramNames.length; i++) {
                context.setVariable(paramNames[i], args[i]);
            }
        }
        return parser.parseExpression(keyExpr).getValue(context, String.class);
    }
}

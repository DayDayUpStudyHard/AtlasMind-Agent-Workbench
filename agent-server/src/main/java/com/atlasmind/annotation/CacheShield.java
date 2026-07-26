package com.atlasmind.annotation;

import java.lang.annotation.*;
import java.util.concurrent.TimeUnit;

/**
 * 缓存防护注解 — 替代 Spring {@code @Cacheable}，增加三层防护：
 * <ul>
 *   <li><b>防穿透</b>：DB 返回 null 时缓存空值标记（{@link #nullTtl()} 短期），防恶意查询不存在的数据</li>
 *   <li><b>防雪崩</b>：TTL 基础上叠加 {@link #ttlVariance()} 随机分钟数，防批量缓存同时过期</li>
 *   <li><b>防击穿</b>：缓存未命中时用 Redisson 分布式锁互斥重建，只有一个线程查 DB</li>
 * </ul>
 * <p>
 * 用法：标注在 Service 的读方法上（替代 {@code @Cacheable}），配合 {@link CacheShieldEvict} 做缓存清除。
 *
 * <pre>{@code
 * @CacheShield(value = "about", key = "'about'", ttl = 30)
 * public About get() { ... }
 * }</pre>
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
@Documented
public @interface CacheShield {

    /** 缓存名称（对应 Redis key 前缀） */
    String value();

    /** 缓存 key 表达式（SpEL，字面量用单引号包裹如 {@code 'all'}） */
    String key();

    /** 基础过期时间 */
    long ttl() default 30;

    /** TTL 随机浮动范围（实际 TTL = ttl + random(0, ttlVariance)） */
    long ttlVariance() default 10;

    /** 空值缓存过期时间（防穿透，短期即可） */
    long nullTtl() default 5;

    /** 时间单位 */
    TimeUnit unit() default TimeUnit.MINUTES;
}

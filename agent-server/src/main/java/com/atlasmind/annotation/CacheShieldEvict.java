package com.atlasmind.annotation;

import java.lang.annotation.*;

/**
 * 缓存清除注解 — 替代 Spring {@code @CacheEvict}。
 * <p>
 * 配合 {@link CacheShield} 使用，标注在 Service 的写方法上。
 * {@code allEntries = true} 时清除整个缓存命名空间。
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
@Documented
public @interface CacheShieldEvict {

    /** 缓存名称 */
    String value();

    /** 缓存 key（SpEL），为空时需配合 {@code allEntries = true} */
    String key() default "";

    /** 清除全部缓存条目 */
    boolean allEntries() default false;
}

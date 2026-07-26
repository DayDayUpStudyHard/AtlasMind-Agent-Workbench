package com.atlasmind.annotation;

import java.lang.annotation.*;
import java.util.concurrent.TimeUnit;

/**
 * 接口限流注解 — 基于 Redis 计数器实现滑动窗口限流。
 * <p>
 * 默认：同一 key 在 60 秒内最多 10 次请求。
 * 应用于登录、评论、留言等公开接口，防止暴力破解和刷量。
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
@Documented
public @interface RateLimit {

    /** 限流 key 前缀，通常用接口路径 */
    String key() default "";

    /** 时间窗口内允许的最大请求数 */
    long limit() default 10;

    /** 时间窗口长度 */
    long window() default 60;

    /** 时间单位 */
    TimeUnit timeUnit() default TimeUnit.SECONDS;

    /** 限流提示消息 */
    String message() default "请求过于频繁，请稍后再试";
}

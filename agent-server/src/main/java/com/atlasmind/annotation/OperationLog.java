package com.atlasmind.annotation;

import java.lang.annotation.*;

/**
 * 操作日志注解 — 自动记录后台管理操作的调用信息。
 * <p>
 * 标注在 Controller 方法上，AOP 切入记录：操作人、IP、方法、参数、耗时、结果。
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
@Documented
public @interface OperationLog {

    /** 操作描述，如"删除文章" */
    String value() default "";

    /** 操作类型 */
    String type() default "OTHER";
}

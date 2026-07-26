package com.atlasmind.config;

import com.baomidou.mybatisplus.core.handlers.MetaObjectHandler;
import lombok.extern.slf4j.Slf4j;
import org.apache.ibatis.reflection.MetaObject;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;

/**
 * MyBatis-Plus 自动填充处理器。
 * <p>
 * 配合实体类上的 {@code @TableField(fill = FieldFill.INSERT)} /
 * {@code @TableField(fill = FieldFill.INSERT_UPDATE)} 注解，
 * 在插入和更新时自动设置 {@code createTime} 和 {@code updateTime} 字段。
 * <p>
 * 注意：{@code strictInsertFill} / {@code strictUpdateFill} 要求
 * 字段名和类型完全匹配（下划线转驼峰），否则填充不生效。
 */
@Slf4j
@Component
public class MyMetaObjectHandler implements MetaObjectHandler {

    @Override
    public void insertFill(MetaObject metaObject) {
        log.debug("MyMetaObjectHandler: insertFill triggered");
        this.strictInsertFill(metaObject, "createTime", LocalDateTime.class, LocalDateTime.now());
        this.strictInsertFill(metaObject, "updateTime", LocalDateTime.class, LocalDateTime.now());
    }

    @Override
    public void updateFill(MetaObject metaObject) {
        log.debug("MyMetaObjectHandler: updateFill triggered");
        this.strictUpdateFill(metaObject, "updateTime", LocalDateTime.class, LocalDateTime.now());
    }
}

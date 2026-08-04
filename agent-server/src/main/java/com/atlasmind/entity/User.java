package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.*;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.Email;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 用户实体，映射 {@code t_user} 表。
 * <p>
 * 注意：密码使用 BCrypt 哈希存储，查询时通过 {@code UserServiceImpl.getById} 自动置空密码字段避免泄露。
 * {@code createTime} 自动填充（插入时）。
 */
@Data
@TableName("t_user")
public class User {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String username;
    @JsonProperty(access = JsonProperty.Access.WRITE_ONLY)
    private String password;
    private String nickname;
    private String avatar;
    @Email(message = "邮箱格式不正确")
    private String email;
    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createTime;
    private String bio;
    private String socialLinks;
}

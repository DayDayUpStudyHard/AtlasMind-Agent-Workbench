package com.atlasmind.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

/**
 * 修改密码 DTO，前端传旧密码+新密码，后端校验旧密码正确后才更新。
 */
@Data
public class PasswordDto {
    @NotBlank(message = "旧密码不能为空")
    private String oldPassword;
    @NotBlank(message = "新密码不能为空")
    private String newPassword;
}

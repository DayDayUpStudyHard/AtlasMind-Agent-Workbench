package com.atlasmind.config;

import cn.dev33.satoken.stp.StpInterface;
import com.atlasmind.entity.User;
import com.atlasmind.mapper.UserMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * Sa-Token 权限提供器 — 让 {@code StpUtil.checkRole("ADMIN")} 生效。
 * <p>
 * 当前不需要细粒度权限码，{@code getPermissionList} 返回空列表。
 * 角色从 t_user.role 字段动态读取，支持实时生效（非缓存）。
 */
@Component
@RequiredArgsConstructor
public class SaTokenPermissionProvider implements StpInterface {

    private final UserMapper userMapper;

    @Override
    public List<String> getPermissionList(Object loginId, String loginType) {
        return List.of();
    }

    @Override
    public List<String> getRoleList(Object loginId, String loginType) {
        long userId = Long.parseLong(String.valueOf(loginId));
        User user = userMapper.selectById(userId);
        if (user == null || user.getRole() == null) return List.of();
        return List.of(user.getRole());
    }
}

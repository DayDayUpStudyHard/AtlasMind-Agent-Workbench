package com.atlasmind.service.impl;

import cn.hutool.crypto.digest.BCrypt;
import com.atlasmind.entity.User;
import com.atlasmind.mapper.UserMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * UserServiceImpl 单元测试 — 使用 Mockito 模拟 Mapper。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("用户服务单元测试")
class UserServiceImplTest {

    @Mock
    private UserMapper userMapper;

    @InjectMocks
    private UserServiceImpl userService;

    private User mockUser;

    @BeforeEach
    void setUp() {
        mockUser = new User();
        mockUser.setId(1L);
        mockUser.setUsername("admin");
        mockUser.setPassword(BCrypt.hashpw("admin123"));
        mockUser.setNickname("管理员");
        mockUser.setEmail("admin@atlasmind.local");
    }

    @Test
    @DisplayName("登录成功 — 正确的用户名和密码")
    void loginSuccess() {
        when(userMapper.selectOne(any())).thenReturn(mockUser);

        User result = userService.login("admin", "admin123");

        assertNotNull(result);
        assertEquals("admin", result.getUsername());
        verify(userMapper).selectOne(any());
    }

    @Test
    @DisplayName("登录失败 — 密码错误")
    void loginFailWrongPassword() {
        when(userMapper.selectOne(any())).thenReturn(mockUser);

        assertThrows(IllegalArgumentException.class, () ->
                userService.login("admin", "wrongpassword"));
    }

    @Test
    @DisplayName("登录失败 — 用户不存在")
    void loginFailUserNotFound() {
        when(userMapper.selectOne(any())).thenReturn(null);

        assertThrows(IllegalArgumentException.class, () ->
                userService.login("nobody", "password"));
    }

    @Test
    @DisplayName("获取用户信息 — 密码字段置空")
    void getByIdClearsPassword() {
        when(userMapper.selectById(1L)).thenReturn(mockUser);

        User result = userService.getById(1L);

        assertNotNull(result);
        assertNull(result.getPassword());
        assertEquals("admin", result.getUsername());
    }

    @Test
    @DisplayName("修改密码 — 旧密码错误时抛异常")
    void updatePasswordWrongOldPassword() {
        when(userMapper.selectById(1L)).thenReturn(mockUser);

        assertThrows(IllegalArgumentException.class, () ->
                userService.updatePassword(1L, "wrongold", "newpassword"));
    }

    @Test
    @DisplayName("修改密码 — 成功更新")
    void updatePasswordSuccess() {
        when(userMapper.selectById(1L)).thenReturn(mockUser);

        assertDoesNotThrow(() ->
                userService.updatePassword(1L, "admin123", "newpassword"));
        verify(userMapper).updateById(any(User.class));
    }

    @Test
    @DisplayName("获取站点信息 — 取 id=1 用户")
    void getSiteInfo() {
        when(userMapper.selectById(1L)).thenReturn(mockUser);

        User result = userService.getSiteInfo();

        assertNotNull(result);
        assertNull(result.getPassword());
        assertEquals("管理员", result.getNickname());
    }

    @Test
    @DisplayName("更新个人资料 — 用户不存在时抛异常")
    void updateProfileUserNotFound() {
        when(userMapper.selectById(999L)).thenReturn(null);

        assertThrows(IllegalArgumentException.class, () ->
                userService.updateProfile(999L, "name", "email@test.com", null, null, null));
    }

    @Test
    @DisplayName("更新个人资料 — 成功更新部分字段")
    void updateProfileSuccess() {
        when(userMapper.selectById(1L)).thenReturn(mockUser);

        userService.updateProfile(1L, "新昵称", null, null, null, null);

        assertEquals("新昵称", mockUser.getNickname());
        // 未传入的字段保持原值
        assertEquals("admin@atlasmind.local", mockUser.getEmail());
        verify(userMapper).updateById(mockUser);
    }
}

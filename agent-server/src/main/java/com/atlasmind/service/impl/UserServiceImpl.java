package com.atlasmind.service.impl;

import cn.hutool.crypto.digest.BCrypt;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.atlasmind.entity.User;
import com.atlasmind.mapper.UserMapper;
import com.atlasmind.service.UserService;
import lombok.RequiredArgsConstructor;
import com.atlasmind.annotation.CacheShieldEvict;
import org.springframework.stereotype.Service;

/**
 * 用户服务实现。
 * <p>
 * 密码使用 Hutool BCrypt 哈希，登录时校验哈希匹配。
 * {@code getById} 自动置空密码字段防止泄露。
 */
@Service
@RequiredArgsConstructor
public class UserServiceImpl implements UserService {

    private final UserMapper userMapper;

    @Override
    public User login(String username, String password) {
        User user = userMapper.selectOne(new LambdaQueryWrapper<User>().eq(User::getUsername, username));
        if (user == null || !BCrypt.checkpw(password, user.getPassword())) {
            throw new IllegalArgumentException("用户名或密码错误");
        }
        return user;
    }

    @Override
    public User getById(Long id) {
        User user = userMapper.selectById(id);
        if (user != null) user.setPassword(null);
        return user;
    }

    @Override
    public User getSiteInfo() {
        User user = userMapper.selectById(1L);
        if (user != null) user.setPassword(null);
        return user;
    }

    @Override
    public void updatePassword(Long userId, String oldPassword, String newPassword) {
        User user = userMapper.selectById(userId);
        if (user == null || !BCrypt.checkpw(oldPassword, user.getPassword())) {
            throw new IllegalArgumentException("旧密码错误");
        }
        user.setPassword(BCrypt.hashpw(newPassword));
        userMapper.updateById(user);
    }

    @CacheShieldEvict(value = "siteInfo", key = "'site'")
    @Override
    public void updateProfile(Long userId, String nickname, String email, String avatar, String bio, String socialLinks) {
        User user = userMapper.selectById(userId);
        if (user == null) throw new IllegalArgumentException("用户不存在");
        if (nickname != null) user.setNickname(nickname);
        if (email != null) user.setEmail(email);
        if (avatar != null) user.setAvatar(avatar);
        if (bio != null) user.setBio(bio);
        if (socialLinks != null) user.setSocialLinks(socialLinks);
        userMapper.updateById(user);
    }
}

package com.atlasmind.service;

import com.atlasmind.entity.User;

/**
 * 用户服务接口。
 */
public interface UserService {
    User login(String username, String password);
    User getById(Long id);
    User getSiteInfo();
    void updatePassword(Long userId, String oldPassword, String newPassword);
    void updateProfile(Long userId, String nickname, String email, String avatar, String bio, String socialLinks);
}

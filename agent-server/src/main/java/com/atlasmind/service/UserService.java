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

    /** Save a new refresh token record (hash + family). */
    void saveRefreshToken(Long userId, String tokenHash, String family);

    /**
     * Rotate a refresh token in a single transaction.
     * Returns the new raw token string and the auth user ID.
     */
    UserRefreshResult rotateRefreshToken(String tokenHash);

    /** Revoke a single refresh token by hash. */
    void revokeRefreshToken(String tokenHash, String reason);

    /** Revoke all refresh tokens for a user. */
    void revokeAllRefreshTokens(Long userId);

    /** Transactional result of rotating a refresh token. */
    record UserRefreshResult(Long userId, String newToken) {}
}

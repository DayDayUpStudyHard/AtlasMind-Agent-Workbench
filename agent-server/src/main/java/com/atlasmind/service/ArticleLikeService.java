package com.atlasmind.service;

import java.util.List;
import java.util.Map;

/**
 * 文章点赞服务接口。
 * <p>
 * Redis 数据结构：
 * <ul>
 *   <li>{@code article:likes:{id}} — Set，已点赞 IP（SISMEMBER 去重）</li>
 *   <li>{@code article:like:count:{id}} — String，点赞计数（INCR/DECR）</li>
 *   <li>{@code article:like:rank} — ZSet，点赞排行榜（按 count 排序，ZINCRBY）</li>
 * </ul>
 * 读写穿透：Redis 为主，MySQL 持久化兜底。
 */
public interface ArticleLikeService {
    /**
     * 切换点赞状态：未点赞→点赞，已点赞→取消。
     *
     * @param articleId 文章 ID
     * @param ip        用户 IP
     * @return {@code {liked: boolean, count: long}}
     */
    Map<String, Object> toggle(Long articleId, String ip);

    /**
     * 获取文章点赞信息。
     */
    Map<String, Object> getLikeInfo(Long articleId, String ip);

    /** 获取文章点赞数（不含用户状态）。 */
    long getCount(Long articleId);

    /**
     * 点赞排行榜 Top-N（按点赞数倒序）。
     *
     * @param limit 取前 N 名
     * @return {@code [{articleId: 1, count: 42}, ...]}
     */
    List<Map<String, Object>> getTopLiked(int limit);
}

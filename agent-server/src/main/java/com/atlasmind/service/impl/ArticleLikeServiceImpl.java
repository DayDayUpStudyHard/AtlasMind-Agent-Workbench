package com.atlasmind.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.atlasmind.entity.ArticleLike;
import com.atlasmind.mapper.ArticleLikeMapper;
import com.atlasmind.service.ArticleLikeService;
import lombok.RequiredArgsConstructor;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ZSetOperations;
import org.springframework.stereotype.Service;

import java.util.*;

/**
 * 文章点赞服务实现 — Redis ZSet 排行榜版。
 *
 * <h3>数据结构</h3>
 * <table>
 *   <tr><th>Key</th><th>类型</th><th>用途</th></tr>
 *   <tr><td>{@code article:likes:{id}}</td><td>Set</td><td>已点赞 IP（SISMEMBER 去重）</td></tr>
 *   <tr><td>{@code article:like:count:{id}}</td><td>String</td><td>点赞计数（INCR/DECR）</td></tr>
 *   <tr><td>{@code article:like:rank}</td><td>ZSet</td><td>全站排行榜（按 count 倒序，ZINCRBY 维护）</td></tr>
 * </table>
 *
 * <h3>设计要点</h3>
 * <ul>
 *   <li>读写穿透：Redis 主读写，MySQL 持久化兜底，启动时从 DB 回填</li>
 *   <li>排行榜实时更新：每次 toggle 同步 ZINCRBY，不依赖定时任务</li>
 *   <li>ZSet score 即 like count：{@code ZREVRANGE ... WITHSCORES} 直接取排行</li>
 * </ul>
 */
@Service
@RequiredArgsConstructor
public class ArticleLikeServiceImpl implements ArticleLikeService {

    private static final String LIKES_SET_PREFIX = "article:likes:";
    private static final String COUNT_KEY_PREFIX = "article:like:count:";
    private static final String RANK_KEY = "article:like:rank";

    private final ArticleLikeMapper articleLikeMapper;
    private final StringRedisTemplate redisTemplate;

    // ═══════════════════════ 点赞/取消 ═══════════════════════

    @Override
    public Map<String, Object> toggle(Long articleId, String ip) {
        String setKey = LIKES_SET_PREFIX + articleId;
        String countKey = COUNT_KEY_PREFIX + articleId;
        Boolean isMember = redisTemplate.opsForSet().isMember(setKey, ip);

        if (Boolean.TRUE.equals(isMember)) {
            // 取消点赞
            redisTemplate.opsForSet().remove(setKey, ip);
            redisTemplate.opsForValue().decrement(countKey);
            redisTemplate.opsForZSet().incrementScore(RANK_KEY, articleId.toString(), -1);
            articleLikeMapper.delete(new LambdaQueryWrapper<ArticleLike>()
                    .eq(ArticleLike::getArticleId, articleId)
                    .eq(ArticleLike::getUserIp, ip));
            long count = getCountFromRedis(articleId);
            return Map.of("liked", false, "count", count);
        } else {
            // 点赞
            redisTemplate.opsForSet().add(setKey, ip);
            Long newCount = redisTemplate.opsForValue().increment(countKey);
            redisTemplate.opsForZSet().incrementScore(RANK_KEY, articleId.toString(), 1);
            ArticleLike like = new ArticleLike();
            like.setArticleId(articleId);
            like.setUserIp(ip);
            articleLikeMapper.insert(like);
            long finalCount = newCount != null ? newCount : 0L;
            return Map.of("liked", true, "count", finalCount);
        }
    }

    // ═══════════════════════ 查询 ═══════════════════════

    @Override
    public Map<String, Object> getLikeInfo(Long articleId, String ip) {
        String setKey = LIKES_SET_PREFIX + articleId;
        Boolean liked = redisTemplate.opsForSet().isMember(setKey, ip);
        long count = getCountFromRedis(articleId);
        return Map.of("liked", Boolean.TRUE.equals(liked), "count", count);
    }

    @Override
    public long getCount(Long articleId) {
        return getCountFromRedis(articleId);
    }

    @Override
    public List<Map<String, Object>> getTopLiked(int limit) {
        Set<ZSetOperations.TypedTuple<String>> top = redisTemplate.opsForZSet()
                .reverseRangeWithScores(RANK_KEY, 0, limit - 1);

        if (top == null || top.isEmpty()) {
            return Collections.emptyList();
        }

        List<Map<String, Object>> result = new ArrayList<>();
        for (ZSetOperations.TypedTuple<String> tuple : top) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("articleId", Long.parseLong(tuple.getValue()));
            item.put("count", (long) tuple.getScore().doubleValue());
            result.add(item);
        }
        return result;
    }

    // ═══════════════════════ 内部 ═══════════════════════

    /** Redis 读计数，未命中从 DB 补偿并回填 Redis */
    private long getCountFromRedis(Long articleId) {
        String countKey = COUNT_KEY_PREFIX + articleId;
        String cached = redisTemplate.opsForValue().get(countKey);
        if (cached != null) {
            return Long.parseLong(cached);
        }
        long dbCount = articleLikeMapper.selectCount(
                new LambdaQueryWrapper<ArticleLike>().eq(ArticleLike::getArticleId, articleId));
        redisTemplate.opsForValue().set(countKey, String.valueOf(dbCount));
        // 同步回填排行榜
        if (dbCount > 0) {
            redisTemplate.opsForZSet().add(RANK_KEY, articleId.toString(), dbCount);
        }
        return dbCount;
    }
}

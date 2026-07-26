package com.atlasmind.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.atlasmind.entity.ArticleLike;
import org.apache.ibatis.annotations.Mapper;

/**
 * 文章点赞 Mapper。
 */
@Mapper
public interface ArticleLikeMapper extends BaseMapper<ArticleLike> {
}

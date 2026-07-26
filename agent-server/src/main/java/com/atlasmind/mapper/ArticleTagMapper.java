package com.atlasmind.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.atlasmind.entity.ArticleTag;
import org.apache.ibatis.annotations.Mapper;

/**
 * 文章-标签关联 Mapper。
 */
@Mapper
public interface ArticleTagMapper extends BaseMapper<ArticleTag> {
}

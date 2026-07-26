package com.atlasmind.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.atlasmind.entity.Comment;
import org.apache.ibatis.annotations.Mapper;

/**
 * 评论 Mapper。
 */
@Mapper
public interface CommentMapper extends BaseMapper<Comment> {
}

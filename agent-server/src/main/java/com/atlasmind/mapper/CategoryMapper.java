package com.atlasmind.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.atlasmind.entity.Category;
import org.apache.ibatis.annotations.Mapper;

/**
 * 分类 Mapper。
 */
@Mapper
public interface CategoryMapper extends BaseMapper<Category> {
}

package com.atlasmind.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.atlasmind.entity.Article;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;
import java.util.Map;

/**
 * 文章 Mapper，继承 MyBatis-Plus {@link BaseMapper}，自带 CRUD 方法。
 * 归档查询使用 {@code @Select} 注解直接写 SQL。
 */
@Mapper
public interface ArticleMapper extends BaseMapper<Article> {

    @Select("SELECT DATE_FORMAT(create_time, '%Y-%m') as yearMonth, " +
            "COUNT(*) as count " +
            "FROM t_article WHERE status = 1 AND deleted = 0 " +
            "GROUP BY DATE_FORMAT(create_time, '%Y-%m') " +
            "ORDER BY yearMonth DESC")
    List<Map<String, Object>> getArchiveGroups();

    @Select("SELECT id, title, summary, create_time FROM t_article " +
            "WHERE status = 1 AND deleted = 0 " +
            "AND DATE_FORMAT(create_time, '%Y-%m') = #{yearMonth} " +
            "ORDER BY create_time DESC")
    List<Article> getArticlesByYearMonth(@Param("yearMonth") String yearMonth);
}

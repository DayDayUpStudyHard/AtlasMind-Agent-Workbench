package com.atlasmind.service;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.atlasmind.dto.ArticleDto;
import com.atlasmind.entity.Article;

import java.util.List;
import java.util.Map;

/**
 * 文章服务接口。
 * <p>
 * 前台方法（{@code getPublishedList / getDetail / getNav}）仅操作已发布文章；
 * 后台方法（{@code getAdminList / create / update / delete}）需登录态调用。
 */
public interface ArticleService {
    Page<Article> getPublishedList(int page, int size, Long categoryId, String keyword);
    Article getDetail(Long id);
    Map<String, Object> getNav(Long id);
    Article getById(Long id);
    Page<Article> getAdminList(int page, int size, Integer status, String visibility);
    Article create(ArticleDto dto);
    Article update(Long id, ArticleDto dto);
    void delete(Long id);

    /**
     * 全文搜索（ES 优先，不可用时回退 MySQL LIKE）。
     */
    Page<Article> search(String keyword, int page, int size);

    /**
     * 文章归档 — 按年月分组，每组包含文章列表。
     */
    List<Map<String, Object>> getArchive();
}

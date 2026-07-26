package com.atlasmind.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.atlasmind.entity.Article;
import com.atlasmind.service.ArticleLikeService;
import com.atlasmind.service.ArticleService;
import com.atlasmind.service.TagService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * ArticleController MockMvc 集成测试 — 验证公开文章接口。
 */
@WebMvcTest(ArticleController.class)
@DisplayName("文章控制器集成测试")
class ArticleControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private ArticleService articleService;

    @MockBean
    private TagService tagService;

    @MockBean
    private ArticleLikeService articleLikeService;

    @Test
    @DisplayName("文章列表 — 返回分页数据")
    void list() throws Exception {
        Page<Article> page = new Page<>(1, 10);
        page.setRecords(List.of());
        page.setTotal(0);
        when(articleService.getPublishedList(anyInt(), anyInt(), isNull(), isNull())).thenReturn(page);

        mockMvc.perform(get("/api/articles"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.data.total").value(0));
    }

    @Test
    @DisplayName("文章详情 — 返回文章数据")
    void detail() throws Exception {
        Article article = new Article();
        article.setId(1L);
        article.setTitle("测试标题");
        article.setContent("# Hello");
        article.setStatus(1);
        when(articleService.getDetail(1L)).thenReturn(article);

        mockMvc.perform(get("/api/articles/1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.data.title").value("测试标题"));
    }

    @Test
    @DisplayName("点赞 — 返回点赞状态")
    void toggleLike() throws Exception {
        when(articleLikeService.toggle(eq(1L), anyString()))
                .thenReturn(Map.of("liked", true, "count", 1L));

        mockMvc.perform(post("/api/articles/1/like"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.data.liked").value(true))
                .andExpect(jsonPath("$.data.count").value(1));
    }
}

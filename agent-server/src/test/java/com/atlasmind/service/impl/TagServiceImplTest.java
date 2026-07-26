package com.atlasmind.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.atlasmind.entity.Tag;
import com.atlasmind.mapper.ArticleTagMapper;
import com.atlasmind.mapper.TagMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * TagServiceImpl 单元测试 — 验证标签 CRUD 与关联删除。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("标签服务单元测试")
class TagServiceImplTest {

    @Mock
    private TagMapper tagMapper;
    @Mock
    private ArticleTagMapper articleTagMapper;

    @InjectMocks
    private TagServiceImpl tagService;

    private Tag tag;

    @BeforeEach
    void setUp() {
        tag = new Tag();
        tag.setId(1L);
        tag.setName("Java");
    }

    @Test
    @DisplayName("标签列表 — 返回全部标签")
    void list() {
        when(tagMapper.selectList(isNull())).thenReturn(List.of(tag));

        List<Tag> result = tagService.list();

        assertEquals(1, result.size());
        assertEquals("Java", result.get(0).getName());
    }

    @Test
    @DisplayName("创建标签 — 插入并设置创建时间")
    void create() {
        tagService.create(tag);

        assertNotNull(tag.getCreateTime());
        verify(tagMapper).insert(tag);
    }

    @Test
    @DisplayName("更新标签 — 按 ID 更新")
    void update() {
        tagService.update(tag);
        verify(tagMapper).updateById(tag);
    }

    @Test
    @DisplayName("删除标签 — 先删关联再删标签")
    void delete() {
        tagService.delete(1L);

        // 先删关联
        verify(articleTagMapper).delete(any(LambdaQueryWrapper.class));
        // 再删标签
        verify(tagMapper).deleteById(1L);
    }
}

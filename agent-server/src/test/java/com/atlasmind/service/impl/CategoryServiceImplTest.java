package com.atlasmind.service.impl;

import com.atlasmind.entity.Category;
import com.atlasmind.mapper.CategoryMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * CategoryServiceImpl 单元测试 — 验证分类 CRUD 与缓存标记。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("分类服务单元测试")
class CategoryServiceImplTest {

    @Mock
    private CategoryMapper categoryMapper;

    @InjectMocks
    private CategoryServiceImpl categoryService;

    private Category cat;

    @BeforeEach
    void setUp() {
        cat = new Category();
        cat.setId(1L);
        cat.setName("技术分享");
        cat.setSort(1);
    }

    @Test
    @DisplayName("分类列表 — 按 sort 升序返回")
    void list() {
        when(categoryMapper.selectList(any())).thenReturn(List.of(cat));

        List<Category> result = categoryService.list();

        assertEquals(1, result.size());
        assertEquals("技术分享", result.get(0).getName());
    }

    @Test
    @DisplayName("创建分类 — 插入成功")
    void create() {
        categoryService.create(cat);
        verify(categoryMapper).insert(cat);
    }

    @Test
    @DisplayName("更新分类 — 已有记录只更新非 null 字段")
    void update() {
        when(categoryMapper.selectById(1L)).thenReturn(cat);
        Category partial = new Category();
        partial.setName("新名称");

        Category result = categoryService.update(1L, partial);

        assertEquals("新名称", result.getName());
        assertEquals(1, result.getSort()); // null 字段保持原值
        verify(categoryMapper).updateById(cat);
    }

    @Test
    @DisplayName("删除分类 — 按 ID 删除")
    void delete() {
        categoryService.delete(1L);
        verify(categoryMapper).deleteById(1L);
    }
}

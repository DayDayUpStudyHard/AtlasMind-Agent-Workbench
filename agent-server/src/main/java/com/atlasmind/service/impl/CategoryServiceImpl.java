package com.atlasmind.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.atlasmind.entity.Category;
import com.atlasmind.mapper.CategoryMapper;
import com.atlasmind.service.CategoryService;
import lombok.RequiredArgsConstructor;
import com.atlasmind.annotation.CacheShield;
import com.atlasmind.annotation.CacheShieldEvict;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 分类服务实现。
 * <p>
 * 列表按 sort 升序排列；更新时只更新非 null 字段，null 字段保持原值。
 */
@Service
@RequiredArgsConstructor
public class CategoryServiceImpl implements CategoryService {

    private final CategoryMapper categoryMapper;

    @CacheShield(value = "categories", key = "'all'", ttl = 30, ttlVariance = 10)
    @Override
    public List<Category> list() {
        return categoryMapper.selectList(new LambdaQueryWrapper<Category>().orderByAsc(Category::getSort));
    }

    @CacheShieldEvict(value = "categories", allEntries = true)
    @Override
    public Category create(Category category) {
        categoryMapper.insert(category);
        return category;
    }

    @CacheShieldEvict(value = "categories", allEntries = true)
    @Override
    public Category update(Long id, Category category) {
        Category existing = categoryMapper.selectById(id);
        if (existing == null) throw new IllegalArgumentException("分类不存在");
        if (category.getName() != null) existing.setName(category.getName());
        if (category.getDescription() != null) existing.setDescription(category.getDescription());
        if (category.getSort() != null) existing.setSort(category.getSort());
        categoryMapper.updateById(existing);
        return existing;
    }

    @CacheShieldEvict(value = "categories", allEntries = true)
    @Override
    public void delete(Long id) {
        categoryMapper.deleteById(id);
    }
}

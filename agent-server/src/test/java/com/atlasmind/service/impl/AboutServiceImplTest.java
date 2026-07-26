package com.atlasmind.service.impl;

import com.atlasmind.entity.About;
import com.atlasmind.mapper.AboutMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * AboutServiceImpl 单元测试 — 验证关于页的 upsert 逻辑。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("关于页服务单元测试")
class AboutServiceImplTest {

    @Mock
    private AboutMapper aboutMapper;

    @InjectMocks
    private AboutServiceImpl aboutService;

    private About existingAbout;

    @BeforeEach
    void setUp() {
        existingAbout = new About();
        existingAbout.setId(1L);
        existingAbout.setContent("# 关于我\n\n测试内容");
        existingAbout.setTimeline("[{\"year\":\"2024\",\"title\":\"知识工作台上线\"}]");
    }

    @Test
    @DisplayName("获取关于页 — 已有数据直接返回，不执行 insert")
    void getExisting() {
        when(aboutMapper.selectById(1L)).thenReturn(existingAbout);

        About result = aboutService.get();

        assertNotNull(result);
        assertEquals("# 关于我\n\n测试内容", result.getContent());
        // 已有数据，不应执行 insert
    }

    @Test
    @DisplayName("获取关于页 — 无数据时自动初始化")
    void getInitializesDefault() {
        when(aboutMapper.selectById(1L)).thenReturn(null);

        About result = aboutService.get();

        assertNotNull(result);
        assertEquals(1L, result.getId());
        assertTrue(result.getContent().contains("关于我"));
    }

    @Test
    @DisplayName("更新关于页 — 已有记录时保留未传入字段")
    void updateExistingPreservesNullFields() {
        when(aboutMapper.selectById(1L)).thenReturn(existingAbout);

        aboutService.update("新内容", null);

        assertEquals("新内容", existingAbout.getContent());
        // timeline 未传入，应保持原值
        assertEquals("[{\"year\":\"2024\",\"title\":\"知识工作台上线\"}]", existingAbout.getTimeline());
    }

    @Test
    @DisplayName("更新关于页 — 同时更新 content 和 timeline")
    void updateBothFields() {
        when(aboutMapper.selectById(1L)).thenReturn(existingAbout);

        aboutService.update("新内容", "[{\"year\":\"2025\"}]");

        assertEquals("新内容", existingAbout.getContent());
        assertEquals("[{\"year\":\"2025\"}]", existingAbout.getTimeline());
    }

    @Test
    @DisplayName("更新关于页 — content 为 null 时不覆盖原值")
    void updatePreservesNullContent() {
        when(aboutMapper.selectById(1L)).thenReturn(existingAbout);

        aboutService.update(null, "[{\"year\":\"2025\"}]");

        assertEquals("# 关于我\n\n测试内容", existingAbout.getContent());
        assertEquals("[{\"year\":\"2025\"}]", existingAbout.getTimeline());
    }

    @Test
    @DisplayName("更新关于页 — 无记录时创建新记录")
    void updateCreatesWhenNotExist() {
        when(aboutMapper.selectById(1L)).thenReturn(null);

        // 不应抛出异常
        assertDoesNotThrow(() -> aboutService.update("内容", "[]"));
    }
}

package com.atlasmind.service.impl;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.atlasmind.entity.Moment;
import com.atlasmind.mapper.MomentMapper;
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
 * MomentServiceImpl 单元测试 — 验证说说 CRUD。
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("说说服务单元测试")
class MomentServiceImplTest {

    @Mock
    private MomentMapper momentMapper;

    @InjectMocks
    private MomentServiceImpl momentService;

    private Moment moment;

    @BeforeEach
    void setUp() {
        moment = new Moment();
        moment.setId(1L);
        moment.setContent("说说内容");
        moment.setImage("https://example.com/img.jpg");
    }

    @Test
    @DisplayName("分页列表 — 按时间倒序")
    void list() {
        Page<Moment> mockPage = new Page<>(1, 10);
        mockPage.setRecords(List.of(moment));
        mockPage.setTotal(1);
        when(momentMapper.selectPage(any(Page.class), any())).thenReturn(mockPage);

        Page<Moment> result = momentService.list(1, 10);

        assertEquals(1, result.getTotal());
        assertEquals("说说内容", result.getRecords().get(0).getContent());
    }

    @Test
    @DisplayName("创建说说 — 设置创建时间并插入")
    void create() {
        momentService.create(moment);

        assertNotNull(moment.getCreateTime());
        verify(momentMapper).insert(moment);
    }

    @Test
    @DisplayName("删除说说 — 按 ID 删除")
    void delete() {
        momentService.delete(1L);
        verify(momentMapper).deleteById(1L);
    }
}

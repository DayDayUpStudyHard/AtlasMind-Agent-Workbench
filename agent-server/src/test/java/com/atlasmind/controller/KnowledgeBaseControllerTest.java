package com.atlasmind.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.atlasmind.entity.KbDocument;
import com.atlasmind.entity.KbDocumentChunk;
import com.atlasmind.entity.KbSpace;
import com.atlasmind.service.KnowledgeBaseService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

import java.time.LocalDateTime;
import java.util.List;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(KnowledgeBaseController.class)
@DisplayName("知识库前台控制器集成测试")
class KnowledgeBaseControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private KnowledgeBaseService knowledgeBaseService;

    @Test
    @DisplayName("文档列表 - 只返回 READY 文档")
    void documents() throws Exception {
        KbSpace space = new KbSpace();
        space.setId(6L);
        space.setName("项目复盘");
        space.setIcon("book");
        space.setColor("#2563eb");

        KbDocument document = new KbDocument();
        document.setId(10L);
        document.setTitle("agent");
        document.setFileName("agent.md");
        document.setFileType("MD");
        document.setFileSize(1024L);
        document.setSpaceId(6L);
        document.setStatus("READY");
        document.setParseMode("FAST");
        document.setChunkCount(11);
        document.setCreateTime(LocalDateTime.of(2026, 7, 27, 17, 8, 30));

        Page<KbDocument> page = new Page<>(1, 12);
        page.setRecords(List.of(document));
        page.setTotal(1);

        when(knowledgeBaseService.listDocuments(eq(1), eq(12), isNull(), eq("READY"), eq(false))).thenReturn(page);
        when(knowledgeBaseService.listSpaces()).thenReturn(List.of(space));

        mockMvc.perform(get("/api/kb/documents"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.data.total").value(1))
                .andExpect(jsonPath("$.data.records[0].title").value("agent"))
                .andExpect(jsonPath("$.data.records[0].spaceName").value("项目复盘"));
    }

    @Test
    @DisplayName("文档详情 - 返回 chunks")
    void documentDetail() throws Exception {
        KbSpace space = new KbSpace();
        space.setId(6L);
        space.setName("项目复盘");

        KbDocument document = new KbDocument();
        document.setId(10L);
        document.setSpaceId(6L);
        document.setTitle("agent");
        document.setFileName("agent.md");
        document.setFileType("MD");
        document.setStatus("READY");

        KbDocumentChunk chunk = new KbDocumentChunk();
        chunk.setId(1L);
        chunk.setDocumentId(10L);
        chunk.setChunkIndex(0);
        chunk.setChunkText("hello");

        when(knowledgeBaseService.getDocument(10L)).thenReturn(document);
        when(knowledgeBaseService.listSpaces()).thenReturn(List.of(space));
        when(knowledgeBaseService.listChunks(10L)).thenReturn(List.of(chunk));

        mockMvc.perform(get("/api/kb/documents/10"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(200))
                .andExpect(jsonPath("$.data.title").value("agent"))
                .andExpect(jsonPath("$.data.chunks[0].chunkText").value("hello"));
    }
}

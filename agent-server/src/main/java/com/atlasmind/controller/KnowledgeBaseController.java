package com.atlasmind.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.atlasmind.common.Result;
import com.atlasmind.entity.KbDocument;
import com.atlasmind.entity.KbDocumentChunk;
import com.atlasmind.entity.KbSpace;
import com.atlasmind.service.KnowledgeBaseService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 前台知识库只读接口。
 * <p>
 * 仅暴露已启用、未删除、已完成的知识库内容，供主页和知识库浏览页使用。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/kb")
public class KnowledgeBaseController {

    private static final String PUBLIC_STATUS = "READY";

    private final KnowledgeBaseService knowledgeBaseService;

    @GetMapping("/spaces")
    public Result<List<KbSpace>> spaces() {
        return Result.ok(knowledgeBaseService.listSpaces());
    }

    @GetMapping("/documents")
    public Result<Map<String, Object>> documents(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "12") int size,
            @RequestParam(required = false) Long spaceId) {
        Page<KbDocument> pageResult = knowledgeBaseService.listDocuments(page, size, spaceId, PUBLIC_STATUS, false);
        Map<Long, KbSpace> spaceMap = knowledgeBaseService.listSpaces().stream()
                .collect(Collectors.toMap(KbSpace::getId, space -> space));

        List<Map<String, Object>> records = pageResult.getRecords().stream()
                .map(document -> toPublicDocument(document, spaceMap.get(document.getSpaceId())))
                .toList();

        Map<String, Object> data = new HashMap<>();
        data.put("records", records);
        data.put("total", pageResult.getTotal());
        data.put("spaces", knowledgeBaseService.listSpaces());
        return Result.ok(data);
    }

    @GetMapping("/documents/{id}")
    public Result<Map<String, Object>> document(@PathVariable Long id) {
        KbDocument document = requirePublicDocument(id);
        KbSpace space = knowledgeBaseService.listSpaces().stream()
                .filter(item -> item.getId().equals(document.getSpaceId()))
                .findFirst()
                .orElse(null);

        Map<String, Object> data = new LinkedHashMap<>(toPublicDocument(document, space));
        data.put("chunks", knowledgeBaseService.listChunks(id));
        return Result.ok(data);
    }

    @GetMapping("/documents/{id}/chunks")
    public Result<List<KbDocumentChunk>> chunks(@PathVariable Long id) {
        requirePublicDocument(id);
        return Result.ok(knowledgeBaseService.listChunks(id));
    }

    private KbDocument requirePublicDocument(Long id) {
        KbDocument document = knowledgeBaseService.getDocument(id);
        if (document == null || document.getDeleted() != null && document.getDeleted() != 0) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Knowledge document not found");
        }
        if (!PUBLIC_STATUS.equalsIgnoreCase(String.valueOf(document.getStatus()))) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Knowledge document is not public");
        }
        boolean visibleSpace = knowledgeBaseService.listSpaces().stream()
                .anyMatch(space -> space.getId().equals(document.getSpaceId()));
        if (!visibleSpace) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Knowledge document is not public");
        }
        return document;
    }

    private Map<String, Object> toPublicDocument(KbDocument document, KbSpace space) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("id", document.getId());
        data.put("title", document.getTitle());
        data.put("fileName", document.getFileName());
        data.put("fileType", document.getFileType());
        data.put("fileSize", document.getFileSize());
        data.put("spaceId", document.getSpaceId());
        data.put("spaceName", space == null ? "" : space.getName());
        data.put("spaceIcon", space == null ? "" : space.getIcon());
        data.put("spaceColor", space == null ? "" : space.getColor());
        data.put("status", document.getStatus());
        data.put("parseMode", document.getParseMode());
        data.put("chunkCount", document.getChunkCount());
        data.put("createTime", document.getCreateTime());
        data.put("updateTime", document.getUpdateTime());
        return data;
    }
}

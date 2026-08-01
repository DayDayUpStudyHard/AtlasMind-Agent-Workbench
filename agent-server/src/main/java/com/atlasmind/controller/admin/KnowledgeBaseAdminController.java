package com.atlasmind.controller.admin;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.atlasmind.annotation.OperationLog;
import com.atlasmind.common.Result;
import com.atlasmind.entity.KbDocument;
import com.atlasmind.entity.KbDocumentChunk;
import com.atlasmind.entity.KbNotification;
import com.atlasmind.entity.KbSpace;
import com.atlasmind.service.KnowledgeBaseService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 后台知识库管理接口。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/admin/kb")
public class KnowledgeBaseAdminController {

    private final KnowledgeBaseService knowledgeBaseService;

    @GetMapping("/spaces")
    public Result<List<KbSpace>> spaces() {
        return Result.ok(knowledgeBaseService.listSpaces());
    }

    @OperationLog(value = "创建知识库空间", type = "CREATE")
    @PostMapping("/spaces")
    public Result<KbSpace> createSpace(@Valid @RequestBody KbSpace space) {
        return Result.ok(knowledgeBaseService.createSpace(space));
    }

    @OperationLog(value = "更新知识库空间", type = "UPDATE")
    @PutMapping("/spaces/{id}")
    public Result<KbSpace> updateSpace(@PathVariable Long id, @Valid @RequestBody KbSpace space) {
        return Result.ok(knowledgeBaseService.updateSpace(id, space));
    }

    @OperationLog(value = "删除知识库空间", type = "DELETE")
    @DeleteMapping("/spaces/{id}")
    public Result<?> deleteSpace(@PathVariable Long id) {
        knowledgeBaseService.deleteSpace(id);
        return Result.ok();
    }

    @GetMapping("/documents")
    public Result<Map<String, Object>> documents(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "10") int size,
            @RequestParam(required = false) Long spaceId,
            @RequestParam(required = false) String status,
            @RequestParam(defaultValue = "false") boolean includeDeleted) {
        Page<KbDocument> pageResult = knowledgeBaseService.listDocuments(page, size, spaceId, status, includeDeleted);
        Map<String, Object> data = new HashMap<>();
        data.put("records", pageResult.getRecords());
        data.put("total", pageResult.getTotal());
        return Result.ok(data);
    }

    @GetMapping("/documents/{id}")
    public Result<KbDocument> document(@PathVariable Long id) {
        return Result.ok(knowledgeBaseService.getDocument(id));
    }

    @GetMapping("/documents/{id}/chunks")
    public Result<List<KbDocumentChunk>> chunks(@PathVariable Long id) {
        return Result.ok(knowledgeBaseService.listChunks(id));
    }

    @OperationLog(value = "上传知识库文档", type = "CREATE")
    @PostMapping("/documents/upload")
    public Result<Map<String, Object>> upload(
            @RequestParam Long spaceId,
            @RequestParam MultipartFile file,
            @RequestParam(required = false) String title,
            @RequestParam(required = false) String parseMode,
            @RequestParam(required = false) List<Long> projectIds) throws IOException {
        return Result.ok(knowledgeBaseService.uploadDocument(spaceId, file, title, parseMode, projectIds));
    }

    @OperationLog(value = "上传知识库文档分片", type = "CREATE")
    @PostMapping("/documents/upload/chunk")
    public Result<Map<String, Object>> uploadChunk(
            @RequestParam String uploadId,
            @RequestParam String fileName,
            @RequestParam long fileSize,
            @RequestParam int chunkIndex,
            @RequestParam int totalChunks,
            @RequestParam MultipartFile chunk) throws IOException {
        return Result.ok(knowledgeBaseService.uploadDocumentChunk(
                uploadId, fileName, fileSize, chunkIndex, totalChunks, chunk));
    }

    @OperationLog(value = "合并知识库文档分片", type = "CREATE")
    @PostMapping("/documents/upload/complete")
    public Result<Map<String, Object>> completeChunkedUpload(
            @RequestParam Long spaceId,
            @RequestParam String uploadId,
            @RequestParam String fileName,
            @RequestParam long fileSize,
            @RequestParam int totalChunks,
            @RequestParam(required = false) String title,
            @RequestParam(required = false) String parseMode,
            @RequestParam(required = false) List<Long> projectIds) throws IOException {
        return Result.ok(knowledgeBaseService.completeChunkedUpload(
                spaceId, uploadId, fileName, fileSize, totalChunks, title, parseMode, projectIds));
    }

    @OperationLog(value = "绑定知识库文档项目", type = "UPDATE")
    @PutMapping("/documents/{id}/projects")
    public Result<?> bindProjects(@PathVariable Long id, @RequestBody Map<String, Object> request) {
        Object value = request.get("projectIds");
        List<Long> projectIds = value instanceof List<?> list
                ? list.stream()
                    .filter(item -> item instanceof Number || item instanceof String)
                    .map(item -> item instanceof Number number ? number.longValue() : Long.valueOf(String.valueOf(item)))
                    .toList()
                : List.of();
        knowledgeBaseService.bindDocumentProjects(id, projectIds);
        return Result.ok();
    }

    @OperationLog(value = "导入 Debug 修复记录", type = "CREATE")
    @PostMapping("/documents/import-debug-record")
    public Result<Map<String, Object>> importDebugRecord() throws IOException {
        return Result.ok(knowledgeBaseService.importDebugRecord());
    }

    @OperationLog(value = "删除知识库文档", type = "DELETE")
    @DeleteMapping("/documents/{id}")
    public Result<?> deleteDocument(@PathVariable Long id) {
        knowledgeBaseService.softDeleteDocument(id);
        return Result.ok();
    }

    @OperationLog(value = "恢复知识库文档", type = "UPDATE")
    @PostMapping("/documents/{id}/restore")
    public Result<?> restoreDocument(@PathVariable Long id) {
        knowledgeBaseService.restoreDocument(id);
        return Result.ok();
    }

    @OperationLog(value = "永久删除知识库文档", type = "DELETE")
    @DeleteMapping("/documents/{id}/permanent")
    public Result<?> permanentDeleteDocument(@PathVariable Long id) throws IOException {
        knowledgeBaseService.permanentDeleteDocument(id);
        return Result.ok();
    }

    @OperationLog(value = "重新解析知识库文档", type = "UPDATE")
    @PostMapping("/documents/{id}/reparse")
    public Result<?> reparseDocument(@PathVariable Long id) {
        knowledgeBaseService.reparseDocument(id);
        return Result.ok();
    }

    @OperationLog(value = "重新索引知识库文档", type = "UPDATE")
    @PostMapping("/documents/{id}/reindex")
    public Result<?> reindexDocument(@PathVariable Long id) {
        knowledgeBaseService.reindexDocument(id);
        return Result.ok();
    }

    @PostMapping("/qa/test")
    public Result<Map<String, Object>> qaTest(@RequestBody Map<String, Object> request) {
        return Result.ok(knowledgeBaseService.qaTest(request));
    }

    @GetMapping("/notifications")
    public Result<List<KbNotification>> notifications(@RequestParam(defaultValue = "false") boolean unreadOnly) {
        return Result.ok(knowledgeBaseService.listNotifications(unreadOnly));
    }

    @GetMapping("/notifications/unread-count")
    public Result<Map<String, Long>> unreadCount() {
        return Result.ok(Map.of("count", knowledgeBaseService.countUnreadNotifications()));
    }

    @PutMapping("/notifications/{id}/read")
    public Result<?> read(@PathVariable Long id) {
        knowledgeBaseService.markNotificationRead(id);
        return Result.ok();
    }

    @PutMapping("/notifications/read-all")
    public Result<?> readAll() {
        knowledgeBaseService.markAllNotificationsRead();
        return Result.ok();
    }
}

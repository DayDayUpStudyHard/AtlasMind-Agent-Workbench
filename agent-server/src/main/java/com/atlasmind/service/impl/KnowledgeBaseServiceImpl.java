package com.atlasmind.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.atlasmind.entity.KbDocument;
import com.atlasmind.entity.KbDocumentChunk;
import com.atlasmind.entity.KbIngestJob;
import com.atlasmind.entity.KbNotification;
import com.atlasmind.entity.KbSpace;
import com.atlasmind.gateway.AiGateway;
import com.atlasmind.mapper.KbDocumentChunkMapper;
import com.atlasmind.mapper.KbDocumentMapper;
import com.atlasmind.mapper.KbIngestJobMapper;
import com.atlasmind.mapper.KbNotificationMapper;
import com.atlasmind.mapper.KbSpaceMapper;
import com.atlasmind.service.KnowledgeBaseService;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.stream.Stream;

/**
 * 知识库管理实现。
 * <p>
 * Java 侧只负责事实源元数据和管理接口；文档解析、切片、embedding、ES 索引
 * 由 Python chat-assistant 负责。
 */
@Service
@RequiredArgsConstructor
public class KnowledgeBaseServiceImpl implements KnowledgeBaseService {

    private static final long MAX_KB_UPLOAD_BYTES = 300L * 1024 * 1024;
    private static final int MAX_CHUNK_COUNT = 10_000;

    private final KbSpaceMapper spaceMapper;
    private final KbDocumentMapper documentMapper;
    private final KbDocumentChunkMapper chunkMapper;
    private final KbIngestJobMapper jobMapper;
    private final KbNotificationMapper notificationMapper;
    private final AiGateway aiGateway;

    @Value("${atlasmind.upload-path:upload/}")
    private String uploadPath;

    @Value("${atlasmind.embedding.model:}")
    private String embeddingModel;

    @Value("${atlasmind.embedding.dim:2560}")
    private Integer embeddingDim;

    @Override
    public List<KbSpace> listSpaces() {
        return spaceMapper.selectList(new LambdaQueryWrapper<KbSpace>()
                .eq(KbSpace::getDeleted, 0)
                .orderByAsc(KbSpace::getSort)
                .orderByDesc(KbSpace::getCreateTime));
    }

    @Override
    public KbSpace createSpace(KbSpace space) {
        if (space.getEnabled() == null) space.setEnabled(1);
        if (space.getSort() == null) space.setSort(0);
        if (space.getDeleted() == null) space.setDeleted(0);
        spaceMapper.insert(space);
        return space;
    }

    @Override
    public KbSpace updateSpace(Long id, KbSpace input) {
        KbSpace space = spaceMapper.selectById(id);
        if (space == null) throw new IllegalArgumentException("知识库空间不存在");
        space.setName(input.getName());
        space.setDescription(input.getDescription());
        space.setIcon(input.getIcon());
        space.setColor(input.getColor());
        space.setSort(input.getSort());
        space.setEnabled(input.getEnabled());
        spaceMapper.updateById(space);
        return space;
    }

    @Override
    public void deleteSpace(Long id) {
        KbSpace space = spaceMapper.selectById(id);
        if (space == null) return;
        space.setDeleted(1);
        space.setEnabled(0);
        spaceMapper.updateById(space);
    }

    @Override
    public Page<KbDocument> listDocuments(int page, int size, Long spaceId, String status, boolean includeDeleted) {
        LambdaQueryWrapper<KbDocument> query = new LambdaQueryWrapper<KbDocument>()
                .orderByDesc(KbDocument::getCreateTime);
        if (!includeDeleted) query.eq(KbDocument::getDeleted, 0);
        if (spaceId != null) query.eq(KbDocument::getSpaceId, spaceId);
        if (status != null && !status.isBlank()) query.eq(KbDocument::getStatus, status);
        Page<KbDocument> result = documentMapper.selectPage(new Page<>(page, size), query);
        fillLatestJobs(result.getRecords());
        return result;
    }

    @Override
    public KbDocument getDocument(Long id) {
        return documentMapper.selectById(id);
    }

    @Override
    public List<KbDocumentChunk> listChunks(Long documentId) {
        return chunkMapper.selectList(new LambdaQueryWrapper<KbDocumentChunk>()
                .eq(KbDocumentChunk::getDocumentId, documentId)
                .eq(KbDocumentChunk::getDeleted, 0)
                .orderByAsc(KbDocumentChunk::getChunkIndex));
    }

    @Override
    @Transactional
    public Map<String, Object> uploadDocument(Long spaceId, MultipartFile file, String title, String parseMode) throws IOException {
        validateUploadFile(file);
        requireSpace(spaceId);

        String originalName = file.getOriginalFilename() == null ? "document" : file.getOriginalFilename();
        String fileType = resolveFileType(originalName);
        validateFileType(fileType);

        Path dir = Path.of(uploadPath, "knowledge", String.valueOf(spaceId));
        Files.createDirectories(dir);
        String storedName = System.currentTimeMillis() + "-" + originalName.replaceAll("[\\\\/:*?\"<>|]", "_");
        Path dest = dir.resolve(storedName).toAbsolutePath().normalize();
        file.transferTo(dest);

        return createUploadedDocument(spaceId, originalName, fileType, file.getSize(), dest, title, "IMPORT", parseMode);
    }

    @Override
    public Map<String, Object> uploadDocumentChunk(String uploadId, String fileName, long fileSize,
                                                   int chunkIndex, int totalChunks, MultipartFile chunk) throws IOException {
        validateChunkUpload(uploadId, fileName, fileSize, chunkIndex, totalChunks, chunk);

        Path chunkDir = chunkDir(uploadId);
        Files.createDirectories(chunkDir);
        Path chunkPath = chunkDir.resolve(chunkFileName(chunkIndex)).toAbsolutePath().normalize();
        if (!chunkPath.startsWith(chunkDir)) {
            throw new IllegalArgumentException("非法分片路径");
        }
        chunk.transferTo(chunkPath);
        return Map.of(
                "uploadId", uploadId,
                "chunkIndex", chunkIndex,
                "totalChunks", totalChunks,
                "received", true
        );
    }

    @Override
    @Transactional
    public Map<String, Object> completeChunkedUpload(Long spaceId, String uploadId, String fileName,
                                                     long fileSize, int totalChunks, String title, String parseMode) throws IOException {
        requireSpace(spaceId);
        validateChunkMeta(uploadId, fileName, fileSize, 0, totalChunks);

        String fileType = resolveFileType(fileName);
        validateFileType(fileType);

        Path chunkDir = chunkDir(uploadId);
        if (!Files.isDirectory(chunkDir)) {
            throw new IllegalArgumentException("未找到上传分片，请重新上传");
        }

        Path dir = Path.of(uploadPath, "knowledge", String.valueOf(spaceId));
        Files.createDirectories(dir);
        String storedName = System.currentTimeMillis() + "-" + fileName.replaceAll("[\\\\/:*?\"<>|]", "_");
        Path dest = dir.resolve(storedName).toAbsolutePath().normalize();
        mergeChunks(chunkDir, dest, totalChunks);

        long actualSize = Files.size(dest);
        if (actualSize != fileSize) {
            Files.deleteIfExists(dest);
            throw new IllegalArgumentException("分片合并后的文件大小不一致，请重新上传");
        }

        deleteDirectory(chunkDir);
        return createUploadedDocument(spaceId, fileName, fileType, actualSize, dest, title, "IMPORT", parseMode);
    }

    private Map<String, Object> createUploadedDocument(Long spaceId, String originalName, String fileType,
                                                       long fileSize, Path dest, String title, String jobType, String parseMode) {
        KbDocument document = new KbDocument();
        document.setSpaceId(spaceId);
        document.setTitle(title == null || title.isBlank() ? stripExt(originalName) : title);
        document.setFileName(originalName);
        document.setFileType(fileType);
        document.setFileSize(fileSize);
        document.setFilePath(dest.toString());
        document.setStatus("UPLOADED");
        document.setParseMode(normalizeParseMode(parseMode, fileType));
        document.setChunkCount(0);
        document.setEmbeddingModel(embeddingModel);
        document.setEmbeddingDim(embeddingDim);
        document.setIndexName("kb_chunks");
        document.setDeleted(0);
        documentMapper.insert(document);

        KbIngestJob job = createJob(document.getId(), jobType);
        triggerIngest(document, job);
        return Map.of("document", document, "job", job);
    }

    @Override
    @Transactional
    public Map<String, Object> importDebugRecord() throws IOException {
        KbSpace space = findOrCreateDebugSpace();
        Path debugPath = Path.of("..", "Debug修复记录.md").toAbsolutePath().normalize();
        if (!Files.exists(debugPath)) {
            debugPath = Path.of("Debug修复记录.md").toAbsolutePath().normalize();
        }
        if (!Files.exists(debugPath)) {
            throw new IllegalArgumentException("未找到 Debug修复记录.md");
        }

        KbDocument document = documentMapper.selectOne(new LambdaQueryWrapper<KbDocument>()
                .eq(KbDocument::getTitle, "AtlasMind Agent Workbench Debug 修复记录")
                .last("LIMIT 1"));
        if (document == null) {
            document = new KbDocument();
            document.setSpaceId(space.getId());
            document.setTitle("AtlasMind Agent Workbench Debug 修复记录");
            document.setFileName("Debug修复记录.md");
            document.setFileType("MD");
            document.setFileSize(Files.size(debugPath));
            document.setFilePath(debugPath.toString());
            document.setStatus("UPLOADED");
            document.setParseMode("FAST");
            document.setChunkCount(0);
            document.setEmbeddingModel(embeddingModel);
            document.setEmbeddingDim(embeddingDim);
            document.setIndexName("kb_chunks");
            document.setDeleted(0);
            documentMapper.insert(document);
        } else {
            document.setSpaceId(space.getId());
            document.setFileSize(Files.size(debugPath));
            document.setFilePath(debugPath.toString());
            document.setStatus("UPLOADED");
            document.setParseMode(document.getParseMode() == null ? "FAST" : document.getParseMode());
            document.setDeleted(0);
            documentMapper.updateById(document);
        }

        KbIngestJob job = createJob(document.getId(), "REPARSE");
        triggerIngest(document, job);
        return Map.of("document", document, "job", job);
    }

    @Override
    @Transactional
    public void softDeleteDocument(Long id) {
        KbDocument document = requireDocument(id);
        document.setDeleted(1);
        document.setStatus("DISABLED");
        documentMapper.updateById(document);
        try {
            aiGateway.deleteDocumentIndex(id);
        } catch (Exception e) {
            createFailureNotification(Map.of("documentId", id), e.getMessage());
        }
    }

    @Override
    @Transactional
    public void restoreDocument(Long id) {
        KbDocument document = requireDocument(id);
        document.setDeleted(0);
        document.setStatus("INDEXING");
        documentMapper.updateById(document);
        KbIngestJob job = createJob(id, "RESTORE");
        triggerReindex(document, job);
    }

    @Override
    @Transactional
    public void reparseDocument(Long id) {
        KbDocument document = requireDocument(id);
        document.setDeleted(0);
        document.setStatus("PARSING");
        documentMapper.updateById(document);
        KbIngestJob job = createJob(id, "REPARSE");
        triggerIngest(document, job);
    }

    @Override
    @Transactional
    public void reindexDocument(Long id) {
        KbDocument document = requireDocument(id);
        document.setDeleted(0);
        document.setStatus("INDEXING");
        documentMapper.updateById(document);
        KbIngestJob job = createJob(id, "REINDEX");
        triggerReindex(document, job);
    }

    @Override
    @Transactional
    public void permanentDeleteDocument(Long id) throws IOException {
        KbDocument document = requireDocument(id);
        try {
            aiGateway.deleteDocumentIndex(id);
        } catch (Exception e) {
            createFailureNotification(Map.of("documentId", id), e.getMessage());
        }
        chunkMapper.hardDeleteByDocumentId(id);
        documentMapper.hardDeleteById(id);
        if (document.getFilePath() != null) {
            Files.deleteIfExists(Path.of(document.getFilePath()));
        }
    }

    @Override
    public Map<String, Object> qaTest(Map<String, Object> request) {
        return aiGateway.testRetrieval(request);
    }

    @Override
    public List<KbNotification> listNotifications(boolean unreadOnly) {
        LambdaQueryWrapper<KbNotification> query = new LambdaQueryWrapper<KbNotification>()
                .orderByDesc(KbNotification::getCreateTime)
                .last("LIMIT 30");
        if (unreadOnly) query.eq(KbNotification::getReadStatus, 0);
        return notificationMapper.selectList(query);
    }

    @Override
    public long countUnreadNotifications() {
        return notificationMapper.selectCount(new LambdaQueryWrapper<KbNotification>()
                .eq(KbNotification::getReadStatus, 0));
    }

    @Override
    public void markNotificationRead(Long id) {
        KbNotification notification = notificationMapper.selectById(id);
        if (notification == null) return;
        notification.setReadStatus(1);
        notificationMapper.updateById(notification);
    }

    @Override
    public void markAllNotificationsRead() {
        List<KbNotification> notifications = notificationMapper.selectList(new LambdaQueryWrapper<KbNotification>()
                .eq(KbNotification::getReadStatus, 0));
        for (KbNotification notification : notifications) {
            notification.setReadStatus(1);
            notificationMapper.updateById(notification);
        }
    }

    private KbIngestJob createJob(Long documentId, String type) {
        KbIngestJob job = new KbIngestJob();
        job.setDocumentId(documentId);
        job.setJobType(type);
        job.setStatus("PENDING");
        job.setProgress(0);
        job.setMessage("等待处理");
        jobMapper.insert(job);
        return job;
    }

    private KbSpace findOrCreateDebugSpace() {
        KbSpace space = spaceMapper.selectOne(new LambdaQueryWrapper<KbSpace>()
                .eq(KbSpace::getName, "项目复盘")
                .last("LIMIT 1"));
        if (space != null) return space;
        KbSpace created = new KbSpace();
        created.setName("项目复盘");
        created.setDescription("项目 Debug 记录、架构决策和复盘资料");
        created.setIcon("bug");
        created.setColor("#2563eb");
        created.setSort(0);
        created.setEnabled(1);
        created.setDeleted(0);
        spaceMapper.insert(created);
        return created;
    }

    private void triggerIngest(KbDocument document, KbIngestJob job) {
        Map<String, Object> body = new HashMap<>();
        body.put("documentId", document.getId());
        body.put("jobId", job.getId());
        body.put("spaceId", document.getSpaceId());
        body.put("title", document.getTitle());
        body.put("filePath", document.getFilePath());
        body.put("fileType", document.getFileType());
        body.put("parseMode", normalizeParseMode(document.getParseMode(), document.getFileType()));
        try {
            aiGateway.triggerIngest(body);
            markJobDispatched(job);
        } catch (Exception e) {
            createFailureNotification(body, e.getMessage());
        }
    }

    private void triggerReindex(KbDocument document, KbIngestJob job) {
        Map<String, Object> body = new HashMap<>();
        body.put("documentId", document.getId());
        body.put("jobId", job.getId());
        try {
            aiGateway.triggerReindex(document.getId(), body);
            markJobDispatched(job);
        } catch (Exception e) {
            createFailureNotification(body, e.getMessage());
        }
    }

    private void markJobDispatched(KbIngestJob job) {
        job.setStatus("RUNNING");
        job.setProgress(Math.max(5, job.getProgress() == null ? 0 : job.getProgress()));
        job.setMessage("已提交 AI 服务处理");
        job.setStartedAt(LocalDateTime.now());
        jobMapper.updateById(job);
    }

    private void createFailureNotification(Map<String, Object> body, String message) {
        Object jobId = body == null ? null : body.get("jobId");
        if (jobId instanceof Number number) {
            KbIngestJob job = jobMapper.selectById(number.longValue());
            if (job != null) {
                job.setStatus("FAILED");
                job.setProgress(0);
                job.setMessage("任务触发失败");
                job.setErrorMessage(message);
                job.setFinishedAt(LocalDateTime.now());
                jobMapper.updateById(job);
            }
        }

        KbNotification notification = new KbNotification();
        notification.setType("INGEST_FAILED");
        notification.setTitle("知识库任务触发失败");
        notification.setContent(message);
        notification.setRelatedType("JOB");
        if (jobId instanceof Number number) {
            notification.setRelatedId(number.longValue());
        }
        notification.setReadStatus(0);
        notificationMapper.insert(notification);
    }

    private KbDocument requireDocument(Long id) {
        KbDocument document = documentMapper.selectById(id);
        if (document == null) throw new IllegalArgumentException("文档不存在");
        return document;
    }

    private void fillLatestJobs(List<KbDocument> documents) {
        if (documents == null || documents.isEmpty()) return;
        List<Long> documentIds = documents.stream().map(KbDocument::getId).toList();
        List<KbIngestJob> jobs = jobMapper.selectList(new LambdaQueryWrapper<KbIngestJob>()
                .in(KbIngestJob::getDocumentId, documentIds)
                .orderByDesc(KbIngestJob::getCreateTime));
        Map<Long, KbIngestJob> latestByDocument = new HashMap<>();
        for (KbIngestJob job : jobs) {
            latestByDocument.putIfAbsent(job.getDocumentId(), job);
        }
        for (KbDocument document : documents) {
            KbIngestJob job = latestByDocument.get(document.getId());
            if (job == null) continue;
            document.setLatestJobId(job.getId());
            document.setLatestJobStatus(job.getStatus());
            document.setLatestJobProgress(job.getProgress());
            document.setLatestJobMessage(job.getMessage());
            document.setLatestJobErrorMessage(job.getErrorMessage());
        }
    }

    private KbSpace requireSpace(Long spaceId) {
        KbSpace space = spaceMapper.selectById(spaceId);
        if (space == null || Integer.valueOf(1).equals(space.getDeleted())) {
            throw new IllegalArgumentException("知识库空间不存在");
        }
        return space;
    }

    private void validateUploadFile(MultipartFile file) {
        if (file == null || file.isEmpty()) {
            throw new IllegalArgumentException("上传文件不能为空");
        }
        if (file.getSize() > MAX_KB_UPLOAD_BYTES) {
            throw new IllegalArgumentException("单个知识库文件不能超过 300MB");
        }
    }

    private void validateChunkUpload(String uploadId, String fileName, long fileSize,
                                     int chunkIndex, int totalChunks, MultipartFile chunk) {
        validateChunkMeta(uploadId, fileName, fileSize, chunkIndex, totalChunks);
        if (chunk == null || chunk.isEmpty()) {
            throw new IllegalArgumentException("上传分片不能为空");
        }
    }

    private void validateChunkMeta(String uploadId, String fileName, long fileSize, int chunkIndex, int totalChunks) {
        if (uploadId == null || !uploadId.matches("[A-Za-z0-9_-]{8,80}")) {
            throw new IllegalArgumentException("非法上传会话");
        }
        if (fileName == null || fileName.isBlank()) {
            throw new IllegalArgumentException("文件名不能为空");
        }
        if (fileSize <= 0 || fileSize > MAX_KB_UPLOAD_BYTES) {
            throw new IllegalArgumentException("单个知识库文件不能超过 300MB");
        }
        if (totalChunks <= 0 || totalChunks > MAX_CHUNK_COUNT) {
            throw new IllegalArgumentException("分片数量不合法");
        }
        if (chunkIndex < 0 || chunkIndex >= totalChunks) {
            throw new IllegalArgumentException("分片序号不合法");
        }
    }

    private Path chunkDir(String uploadId) {
        Path root = Path.of(uploadPath, "knowledge", ".chunks").toAbsolutePath().normalize();
        Path dir = root.resolve(uploadId).toAbsolutePath().normalize();
        if (!dir.startsWith(root)) {
            throw new IllegalArgumentException("非法上传会话");
        }
        return dir;
    }

    private String chunkFileName(int chunkIndex) {
        return String.format(Locale.ROOT, "%06d.part", chunkIndex);
    }

    private void mergeChunks(Path chunkDir, Path dest, int totalChunks) throws IOException {
        try (OutputStream out = Files.newOutputStream(dest)) {
            for (int i = 0; i < totalChunks; i++) {
                Path chunkPath = chunkDir.resolve(chunkFileName(i)).toAbsolutePath().normalize();
                if (!chunkPath.startsWith(chunkDir) || !Files.exists(chunkPath)) {
                    throw new IllegalArgumentException("上传分片不完整，请重新上传");
                }
                try (InputStream in = Files.newInputStream(chunkPath)) {
                    in.transferTo(out);
                }
            }
        }
    }

    private void deleteDirectory(Path dir) throws IOException {
        if (!Files.exists(dir)) return;
        try (Stream<Path> paths = Files.walk(dir)) {
            paths.sorted(Comparator.reverseOrder()).forEach(path -> {
                try {
                    Files.deleteIfExists(path);
                } catch (IOException ignored) {
                }
            });
        }
    }

    private String resolveFileType(String name) {
        int dot = name.lastIndexOf('.');
        String ext = dot >= 0 ? name.substring(dot + 1).toUpperCase(Locale.ROOT) : "";
        if ("MARKDOWN".equals(ext)) return "MD";
        return ext;
    }

    private void validateFileType(String fileType) {
        if (!List.of("MD", "TXT", "PDF").contains(fileType)) {
            throw new IllegalArgumentException("第一版仅支持 Markdown、TXT、PDF");
        }
    }

    private String normalizeParseMode(String parseMode, String fileType) {
        if (!"PDF".equalsIgnoreCase(fileType)) {
            return "FAST";
        }
        if (parseMode == null || parseMode.isBlank()) {
            return "OCR";
        }
        String normalized = parseMode.trim().toUpperCase(Locale.ROOT);
        if (!List.of("FAST", "OCR", "MINERU").contains(normalized)) {
            throw new IllegalArgumentException("解析模式不合法");
        }
        return normalized;
    }

    private String stripExt(String name) {
        int dot = name.lastIndexOf('.');
        return dot > 0 ? name.substring(0, dot) : name;
    }
}

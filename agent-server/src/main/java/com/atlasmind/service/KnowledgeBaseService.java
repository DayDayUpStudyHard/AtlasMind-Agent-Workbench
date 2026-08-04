package com.atlasmind.service;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.atlasmind.entity.KbDocument;
import com.atlasmind.entity.KbDocumentChunk;
import com.atlasmind.entity.KbNotification;
import com.atlasmind.entity.KbSpace;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.List;
import java.util.Map;

/**
 * 知识库管理服务，负责元数据、导入任务和消息中心。
 */
public interface KnowledgeBaseService {
    List<KbSpace> listSpaces();

    KbSpace createSpace(KbSpace space);

    KbSpace updateSpace(Long id, KbSpace space);

    void deleteSpace(Long id);

    Page<KbDocument> listDocuments(int page, int size, Long spaceId, String status, boolean includeDeleted);

    KbDocument getDocument(Long id);

    List<KbDocumentChunk> listChunks(Long documentId);

    Map<String, Object> uploadDocument(Long spaceId, MultipartFile file, String title, String parseMode,
                                       List<Long> projectIds) throws IOException;

    Map<String, Object> uploadDocumentChunk(String uploadId, String fileName, long fileSize,
                                            int chunkIndex, int totalChunks, MultipartFile chunk) throws IOException;

    Map<String, Object> completeChunkedUpload(Long spaceId, String uploadId, String fileName,
                                              long fileSize, int totalChunks, String title, String parseMode,
                                              List<Long> projectIds) throws IOException;

    void bindDocumentProjects(Long documentId, List<Long> projectIds);

    void updateDocumentContractUsage(Long documentId, String scope, List<Long> caseIds);

    List<Map<String, Object>> listContractKnowledge(Long caseId);

    Map<String, Object> importDebugRecord() throws IOException;

    void softDeleteDocument(Long id);

    void restoreDocument(Long id);

    void reparseDocument(Long id);

    void reindexDocument(Long id);

    void permanentDeleteDocument(Long id) throws IOException;

    Map<String, Object> qaTest(Map<String, Object> request);

    List<KbNotification> listNotifications(boolean unreadOnly);

    long countUnreadNotifications();

    void markNotificationRead(Long id);

    void markAllNotificationsRead();
}

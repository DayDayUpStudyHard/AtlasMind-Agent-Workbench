package com.atlasmind.service;

import cn.dev33.satoken.stp.StpUtil;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.Resource;
import org.springframework.core.io.UrlResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.nio.file.Files;
import java.nio.file.Path;

/** Registers local uploads and resolves them only after an ownership/access check. */
@Service
@RequiredArgsConstructor
public class PrivateUploadService {

    private final JdbcTemplate jdbc;
    private final ContractAccessPolicy accessPolicy;

    @Value("${atlasmind.upload-path:upload/}")
    private String uploadPath;

    public void register(String path, Long ownerId, String originalName, String contentType) {
        if (path == null || !path.startsWith("/upload/") || ownerId == null) return;
        jdbc.update("""
                INSERT INTO private_upload (path, owner_id, original_name, content_type)
                VALUES (?,?,?,?)
                ON DUPLICATE KEY UPDATE owner_id=VALUES(owner_id),
                    original_name=VALUES(original_name), content_type=VALUES(content_type)
                """,
                path, ownerId, originalName == null ? "" : originalName,
                contentType == null || contentType.isBlank()
                        ? "application/octet-stream" : contentType);
    }

    public PrivateFile load(String requestedPath) {
        String relativePath = normalizeRelativePath(requestedPath);
        String publicPath = "/upload/" + relativePath.replace('\\', '/');
        authorize(publicPath);

        return resolveFileInternal(relativePath);
    }

    /**
     * 在调用方已完成权限校验后，直接解析并返回文件流。
     * filePath 为 DB 中存储的路径（如 /upload/abc.pdf 或 storage_key）。
     */
    public PrivateFile streamFile(String filePath, String fileName, String contentType) {
        String p = filePath == null ? "" : filePath.replace('\\', '/');
        // Strip /upload/ prefix — DB stores paths as /upload/...
        if (p.startsWith("/upload/")) p = p.substring("/upload/".length());
        String relativePath = normalizeRelativePath(p);
        return resolveFileInternal(relativePath);
    }

    private PrivateFile resolveFileInternal(String relativePath) {
        Path root = Path.of(uploadPath).toAbsolutePath().normalize();
        Path file = root.resolve(relativePath).toAbsolutePath().normalize();
        if (!file.startsWith(root) || !Files.isRegularFile(file)) {
            throw new org.springframework.web.server.ResponseStatusException(
                    org.springframework.http.HttpStatus.NOT_FOUND, "文件不存在");
        }
        try {
            Resource resource = new UrlResource(file.toUri());
            String contentType = Files.probeContentType(file);
            return new PrivateFile(resource, file.getFileName().toString(), contentType);
        } catch (Exception exception) {
            throw new IllegalArgumentException("文件路径无效", exception);
        }
    }

    private void authorize(String publicPath) {
        long userId = StpUtil.getLoginIdAsLong();
        var contractRows = jdbc.queryForList(
                "SELECT case_id FROM contract_document WHERE file_path=? LIMIT 1", publicPath);
        if (!contractRows.isEmpty()) {
            Object caseId = contractRows.get(0).get("case_id");
            if (caseId instanceof Number number) {
                accessPolicy.checkAccess(number.longValue());
                return;
            }
        }

        Integer owned = jdbc.queryForObject(
                "SELECT COUNT(*) FROM private_upload WHERE path=? AND owner_id=?",
                Integer.class, publicPath, userId);
        if ((owned != null && owned > 0) || accessPolicy.isAdmin(userId)) return;
        throw new org.springframework.web.server.ResponseStatusException(
                org.springframework.http.HttpStatus.NOT_FOUND, "文件不存在");
    }

    private String normalizeRelativePath(String requestedPath) {
        String value = requestedPath == null ? "" : requestedPath.replace('\\', '/');
        while (value.startsWith("/")) value = value.substring(1);
        if (value.isBlank() || value.contains("..")) {
            throw new IllegalArgumentException("文件路径无效");
        }
        return value;
    }

    public record PrivateFile(Resource resource, String fileName, String contentType) {}
}

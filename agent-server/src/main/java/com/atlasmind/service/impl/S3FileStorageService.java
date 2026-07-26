package com.atlasmind.service.impl;

import cn.hutool.core.util.IdUtil;
import com.atlasmind.config.FileStorageConfig;
import com.atlasmind.dto.StoreResult;
import com.atlasmind.service.FileStorageService;
import com.atlasmind.util.ImageUtil;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;

import java.io.IOException;
import java.net.URI;

/**
 * S3 兼容文件存储实现（Cloudflare R2 / AWS S3 / MinIO 等）。
 * <p>
 * 通过 {@code atlasmind.storage.type=s3} 激活，S3Client 在构造时创建，
 * 存储路径为 {@code agent-assets/<uuid>.<ext>}，返回公开访问 URL。
 * <p>
 * 图片上传自动压缩（>1920px 等比缩放至 1920px）+ 生成 400px 缩略图；
 * GIF 动图跳过压缩但生成静态缩略图；非图片文件直接存储。
 */
@Service
@ConditionalOnProperty(name = "atlasmind.storage.type", havingValue = "s3")
public class S3FileStorageService implements FileStorageService {

    private final S3Client client;
    private final FileStorageConfig config;

    public S3FileStorageService(FileStorageConfig config) {
        this.config = config;
        var s3Config = config.getS3();
        this.client = S3Client.builder()
                .region(Region.of(s3Config.getRegion()))
                .endpointOverride(URI.create(s3Config.getEndpoint()))
                .credentialsProvider(StaticCredentialsProvider.create(
                        AwsBasicCredentials.create(s3Config.getAccessKey(), s3Config.getSecretKey())))
                .forcePathStyle(true)
                .build();
    }

    @Override
    public StoreResult store(MultipartFile file) throws IOException {
        String originalName = file.getOriginalFilename();
        String ext = "";
        if (originalName != null && originalName.contains(".")) {
            ext = originalName.substring(originalName.lastIndexOf(".")).toLowerCase();
        }
        String baseName = IdUtil.fastSimpleUUID();

        // 读取原始字节
        byte[] rawBytes = file.getBytes();
        String contentType = file.getContentType();

        // 非图片 → 直接上传
        if (!ImageUtil.isImage(originalName)) {
            String key = "agent-assets/" + baseName + ext;
            putObject(key, rawBytes, contentType);
            return StoreResult.of(publicUrl(key));
        }

        // 图片 → 压缩 + 缩略图
        String format = ImageUtil.format(originalName);
        byte[] compressed = ImageUtil.compress(rawBytes, format);
        byte[] thumb = ImageUtil.thumbnail(rawBytes, format);

        // 上传压缩后主图
        String mainKey = "agent-assets/" + baseName + ext;
        putObject(mainKey, compressed, contentType);

        // 上传缩略图
        String thumbKey = "agent-assets/" + baseName + "_thumb" + ext;
        putObject(thumbKey, thumb, contentType);

        return StoreResult.of(publicUrl(mainKey), publicUrl(thumbKey));
    }

    void putObject(String key, byte[] bytes, String contentType) {
        PutObjectRequest request = PutObjectRequest.builder()
                .bucket(config.getS3().getBucket())
                .key(key)
                .contentType(contentType)
                .build();
        client.putObject(request, RequestBody.fromBytes(bytes));
    }

    private String publicUrl(String key) {
        var s3 = config.getS3();
        if (s3.getPublicUrl() != null && !s3.getPublicUrl().isBlank()) {
            return s3.getPublicUrl() + "/" + key;
        }
        return s3.getEndpoint() + "/" + s3.getBucket() + "/" + key;
    }
}

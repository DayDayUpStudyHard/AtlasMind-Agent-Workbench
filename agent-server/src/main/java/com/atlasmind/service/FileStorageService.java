package com.atlasmind.service;

import com.atlasmind.dto.StoreResult;
import org.springframework.web.multipart.MultipartFile;
import java.io.IOException;

/**
 * 文件存储服务接口，定义统一的文件上传行为。
 * <p>
 * 实现类通过 {@code @ConditionalOnProperty("atlasmind.storage.type")} 条件装配：
 * {@code local} → {@code LocalFileStorageService}，{@code s3} → {@code S3FileStorageService}。
 * 图片上传自动压缩（>1920px 等比缩放）+ 生成 400px 缩略图；非图片文件只存储不处理。
 */
public interface FileStorageService {
    StoreResult store(MultipartFile file) throws IOException;
}

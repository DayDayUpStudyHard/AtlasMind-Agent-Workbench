package com.atlasmind.service.impl;

import cn.hutool.core.util.IdUtil;
import com.atlasmind.dto.StoreResult;
import com.atlasmind.service.FileStorageService;
import com.atlasmind.util.ImageUtil;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * 本地文件存储实现，默认生效。
 * <p>
 * 文件保存至配置的 {@code atlasmind.upload-path} 目录（默认 {@code upload/}），
 * 返回相对路径 {@code /upload/xxx.ext}，由 {@code WebConfig} 映射为静态资源。
 * 文件名使用 UUID 避免冲突。
 * <p>
 * 图片上传自动压缩（>1920px 等比缩放至 1920px）+ 生成 400px 缩略图；
 * GIF 动图跳过压缩但生成静态缩略图；非图片文件直接存储。
 */
@Service
@ConditionalOnProperty(name = "atlasmind.storage.type", havingValue = "local", matchIfMissing = true)
public class LocalFileStorageService implements FileStorageService {

    @Value("${atlasmind.upload-path:upload/}")
    private String uploadPath;

    @Override
    public StoreResult store(MultipartFile file) throws IOException {
        // 1. 提取文件名信息
        String originalName = file.getOriginalFilename();
        String ext = "";
        if (originalName != null && originalName.contains(".")) {
            ext = originalName.substring(originalName.lastIndexOf(".")).toLowerCase();
        }
        String baseName = IdUtil.fastSimpleUUID();

        // 2. 确保上传目录存在
        File dir = new File(uploadPath);
        if (!dir.exists()) dir.mkdirs();

        // 3. 读取原始字节
        byte[] rawBytes = file.getBytes();

        // 4. 非图片 → 直接存储
        if (!ImageUtil.isImage(originalName)) {
            Path dest = Path.of(uploadPath, baseName + ext);
            Files.write(dest, rawBytes);
            return StoreResult.of("/upload/" + baseName + ext);
        }

        // 5. 图片 → 压缩 + 缩略图
        String format = ImageUtil.format(originalName);
        byte[] compressed = ImageUtil.compress(rawBytes, format);
        byte[] thumb = ImageUtil.thumbnail(rawBytes, format);

        // 写入压缩后的主图
        Path mainPath = Path.of(uploadPath, baseName + ext);
        Files.write(mainPath, compressed);

        // 写入缩略图
        String thumbName = baseName + "_thumb" + ext;
        Path thumbPath = Path.of(uploadPath, thumbName);
        Files.write(thumbPath, thumb);

        return StoreResult.of(
                "/upload/" + baseName + ext,
                "/upload/" + thumbName
        );
    }
}

package com.atlasmind.controller;

import com.atlasmind.common.Result;
import com.atlasmind.dto.StoreResult;
import com.atlasmind.service.FileStorageService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 文件上传接口（需登录态，由 SaToken 拦截器保护）。
 * 根据配置选择本地存储或 S3 兼容存储，返回文件访问 URL。
 * 图片上传自动压缩（>1920px 等比缩放）+ 生成 400px 缩略图。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/upload")
public class UploadController {

    private final FileStorageService storageService;

    @PostMapping
    public Result<Map<String, String>> upload(@RequestParam("file") MultipartFile file) throws IOException {
        StoreResult result = storageService.store(file);
        Map<String, String> data = new LinkedHashMap<>();
        data.put("url", result.getUrl());
        if (result.getThumbUrl() != null) {
            data.put("thumbUrl", result.getThumbUrl());
        }
        return Result.ok(data);
    }
}

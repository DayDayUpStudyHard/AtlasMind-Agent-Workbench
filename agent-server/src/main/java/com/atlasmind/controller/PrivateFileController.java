package com.atlasmind.controller;

import com.atlasmind.service.PrivateUploadService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.CacheControl;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.nio.charset.StandardCharsets;

/** Authenticated compatibility endpoint for existing /upload/... URLs. */
@RestController
@RequiredArgsConstructor
@RequestMapping("/upload")
public class PrivateFileController {

    private final PrivateUploadService privateUploadService;

    @GetMapping("/{*filePath}")
    public ResponseEntity<org.springframework.core.io.Resource> download(
            @PathVariable String filePath) {
        PrivateUploadService.PrivateFile file = privateUploadService.load(filePath);
        MediaType mediaType;
        try {
            mediaType = file.contentType() == null
                    ? MediaType.APPLICATION_OCTET_STREAM
                    : MediaType.parseMediaType(file.contentType());
        } catch (Exception ignored) {
            mediaType = MediaType.APPLICATION_OCTET_STREAM;
        }
        boolean inline = MediaType.APPLICATION_PDF.includes(mediaType)
                || "image".equalsIgnoreCase(mediaType.getType());
        ContentDisposition disposition = (inline
                ? ContentDisposition.inline()
                : ContentDisposition.attachment())
                .filename(file.fileName(), StandardCharsets.UTF_8)
                .build();
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .header(HttpHeaders.CONTENT_DISPOSITION, disposition.toString())
                .header("X-Content-Type-Options", "nosniff")
                .contentType(mediaType)
                .body(file.resource());
    }
}

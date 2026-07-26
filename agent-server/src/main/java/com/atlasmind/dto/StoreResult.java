package com.atlasmind.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 文件存储结果 — 包含原图/压缩图 URL 和缩略图 URL。
 * 非图片文件 thumbUrl 为 null。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class StoreResult {
    private String url;
    private String thumbUrl;

    /** 非图片只需 url */
    public static StoreResult of(String url) {
        return new StoreResult(url, null);
    }

    public static StoreResult of(String url, String thumbUrl) {
        return new StoreResult(url, thumbUrl);
    }
}

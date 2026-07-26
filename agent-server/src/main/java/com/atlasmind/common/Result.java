package com.atlasmind.common;

import lombok.Data;

/**
 * 统一响应体，所有 Controller 均通过此类返回 JSON。
 * <p>
 * 提供静态工厂方法 {@link #ok} / {@link #fail} 快速构建成功/失败响应。
 * 泛型 {@code T} 为实际返回数据类型。
 */
@Data
public class Result<T> {
    private int code;
    private String message;
    private T data;

    public static <T> Result<T> ok(T data) {
        Result<T> r = new Result<>();
        r.code = 200;
        r.message = "success";
        r.data = data;
        return r;
    }

    public static <T> Result<T> ok() {
        return ok(null);
    }

    public static <T> Result<T> fail(int code, String message) {
        Result<T> r = new Result<>();
        r.code = code;
        r.message = message;
        return r;
    }

    public static <T> Result<T> fail(String message) {
        return fail(400, message);
    }
}

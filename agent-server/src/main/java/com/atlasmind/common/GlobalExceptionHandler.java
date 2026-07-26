package com.atlasmind.common;

import cn.dev33.satoken.exception.NotLoginException;
import jakarta.validation.ConstraintViolation;
import jakarta.validation.ConstraintViolationException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.validation.FieldError;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.NoHandlerFoundException;

import java.util.stream.Collectors;

/**
 * 全局异常处理器 — 将所有异常转为统一的 {@link Result} 响应。
 * <p>
 * 覆盖：参数校验、认证鉴权、数据库约束、HTTP 方法/路径错误、兜底异常。
 * 兜底处理不暴露 {@code e.getMessage()}，避免生产环境泄露内部信息。
 */
@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    // ==================== 参数校验 ====================

    /**
     * {@code @Valid @RequestBody} 校验失败（Jakarta Bean Validation）
     */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public Result<?> handleMethodArgumentNotValid(MethodArgumentNotValidException e) {
        String msg = e.getBindingResult().getFieldErrors().stream()
                .map(fe -> fe.getField() + ": " + fe.getDefaultMessage())
                .collect(Collectors.joining("; "));
        return Result.fail(msg);
    }

    /**
     * 方法参数校验失败（{@code @Validated} on controller class + path/query param constraints）
     */
    @ExceptionHandler(ConstraintViolationException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public Result<?> handleConstraintViolation(ConstraintViolationException e) {
        String msg = e.getConstraintViolations().stream()
                .map(ConstraintViolation::getMessage)
                .collect(Collectors.joining("; "));
        return Result.fail(msg);
    }

    /**
     * JSON 请求体格式错误或类型不匹配
     */
    @ExceptionHandler(HttpMessageNotReadableException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public Result<?> handleHttpMessageNotReadable(HttpMessageNotReadableException e) {
        return Result.fail("请求格式错误，请检查 JSON 结构");
    }

    /**
     * 缺少必需的请求参数
     */
    @ExceptionHandler(MissingServletRequestParameterException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public Result<?> handleMissingParam(MissingServletRequestParameterException e) {
        return Result.fail("缺少请求参数: " + e.getParameterName());
    }

    /**
     * 请求参数类型转换失败（如分页参数传了字符串）
     */
    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public Result<?> handleTypeMismatch(MethodArgumentTypeMismatchException e) {
        return Result.fail("参数类型错误: " + e.getName() + " 应为 " +
                (e.getRequiredType() != null ? e.getRequiredType().getSimpleName() : "未知类型"));
    }

    /**
     * 表单绑定校验失败
     */
    @ExceptionHandler(org.springframework.validation.BindException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public Result<?> handleBindException(org.springframework.validation.BindException e) {
        String msg = e.getBindingResult().getFieldErrors().stream()
                .map(FieldError::getDefaultMessage)
                .collect(Collectors.joining("; "));
        return Result.fail(msg);
    }

    // ==================== 业务异常 ====================

    @ExceptionHandler(IllegalArgumentException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    public Result<?> handleIllegalArgument(IllegalArgumentException e) {
        return Result.fail(e.getMessage());
    }

    // ==================== 认证鉴权 ====================

    @ExceptionHandler(NotLoginException.class)
    @ResponseStatus(HttpStatus.UNAUTHORIZED)
    public Result<?> handleNotLogin(NotLoginException e) {
        return Result.fail(401, "请先登录");
    }

    // ==================== 数据库 ====================

    /**
     * 数据库约束冲突（唯一键重复、外键约束等）。
     * 不暴露原始 SQL 错误信息。
     */
    @ExceptionHandler(DataIntegrityViolationException.class)
    @ResponseStatus(HttpStatus.CONFLICT)
    public Result<?> handleDataIntegrityViolation(DataIntegrityViolationException e) {
        log.warn("数据完整性冲突: {}", e.getMessage());
        return Result.fail(409, "数据已存在或违反约束，请检查");
    }

    // ==================== HTTP 方法 / 路径错误 ====================

    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    @ResponseStatus(HttpStatus.METHOD_NOT_ALLOWED)
    public Result<?> handleMethodNotSupported(HttpRequestMethodNotSupportedException e) {
        return Result.fail(405, "不支持的请求方法: " + e.getMethod());
    }

    @ExceptionHandler(NoHandlerFoundException.class)
    @ResponseStatus(HttpStatus.NOT_FOUND)
    public Result<?> handleNoHandlerFound(NoHandlerFoundException e) {
        return Result.fail(404, "接口不存在: " + e.getRequestURL());
    }

    // ==================== 兜底处理 ====================

    /**
     * 兜底处理 — 未知异常。
     * 记录完整堆栈，返回通用错误消息，不泄露内部细节。
     */
    @ExceptionHandler(Exception.class)
    @ResponseStatus(HttpStatus.INTERNAL_SERVER_ERROR)
    public Result<?> handleException(Exception e) {
        log.error("未捕获异常: {}", e.getMessage(), e);
        return Result.fail(500, "服务器内部错误，请稍后重试");
    }
}

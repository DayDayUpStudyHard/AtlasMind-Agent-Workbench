package com.atlasmind.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.atlasmind.entity.OperationLog;
import com.atlasmind.mapper.OperationLogMapper;
import com.atlasmind.service.OperationLogService;
import lombok.RequiredArgsConstructor;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

/**
 * 操作日志服务实现。
 * <p>
 * {@code save()} 使用 {@code @Async} 异步写入，避免拖慢管理端请求响应。
 * {@code getList()} 同步查询，支持按操作类型筛选。
 */
@Service
@RequiredArgsConstructor
public class OperationLogServiceImpl implements OperationLogService {

    private final OperationLogMapper operationLogMapper;

    @Async("logExecutor")
    @Override
    public void save(OperationLog log) {
        operationLogMapper.insert(log);
    }

    @Override
    public Page<OperationLog> getList(int page, int size, String type) {
        LambdaQueryWrapper<OperationLog> wrapper = new LambdaQueryWrapper<OperationLog>()
                .orderByDesc(OperationLog::getCreateTime);
        if (type != null && !type.isBlank()) {
            wrapper.eq(OperationLog::getType, type);
        }
        return operationLogMapper.selectPage(new Page<>(page, size), wrapper);
    }
}

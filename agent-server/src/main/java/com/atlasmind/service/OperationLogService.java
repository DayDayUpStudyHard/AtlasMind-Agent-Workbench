package com.atlasmind.service;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.atlasmind.entity.OperationLog;

/**
 * 操作日志服务接口。
 */
public interface OperationLogService {
    void save(OperationLog log);
    Page<OperationLog> getList(int page, int size, String type);
}

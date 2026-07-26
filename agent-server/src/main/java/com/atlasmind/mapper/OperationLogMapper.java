package com.atlasmind.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.atlasmind.entity.OperationLog;
import org.apache.ibatis.annotations.Mapper;

/**
 * 操作日志 Mapper — 使用 MyBatis-Plus BaseMapper 的标准 CRUD。
 */
@Mapper
public interface OperationLogMapper extends BaseMapper<OperationLog> {
}

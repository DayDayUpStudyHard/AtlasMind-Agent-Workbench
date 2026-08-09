package com.atlasmind.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.atlasmind.entity.Department;
import org.apache.ibatis.annotations.Mapper;

/**
 * 部门 Mapper。
 */
@Mapper
public interface DepartmentMapper extends BaseMapper<Department> {
}

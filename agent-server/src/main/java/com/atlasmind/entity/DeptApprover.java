package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 部门审批人白名单，映射 {@code dept_approver} 表（phase-2-design §5）。
 * 成员角色（OWNER/EDITOR/REVIEWER/VIEWER）与流程角色是两套，不互相推导。
 */
@Data
@TableName("dept_approver")
public class DeptApprover {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long deptId;
    private Long userId;
    private Long createdBy;
    private LocalDateTime createTime;
}

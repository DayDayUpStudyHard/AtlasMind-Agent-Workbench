package com.atlasmind.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 流程角色成员，映射 {@code flow_role_member} 表（phase-2-design §5）。
 * 当前只使用 {@code roleCode='LEGAL'}。
 */
@Data
@TableName("flow_role_member")
public class FlowRoleMember {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String roleCode;
    private Long userId;
    private Long createdBy;
    private LocalDateTime createTime;
}

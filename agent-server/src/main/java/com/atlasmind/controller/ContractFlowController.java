package com.atlasmind.controller;

import cn.dev33.satoken.stp.StpUtil;
import com.atlasmind.common.Result;
import com.atlasmind.service.ContractAccessPolicy;
import com.atlasmind.service.ContractFlowService;
import com.atlasmind.service.FlowTimelineService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 二期审批流程接口（design §3 / §3.1）。
 *
 * <p>第 3 步只开放查询与内容类动作；认领、审批、撤回等写动作属第 5 步，
 * 单独在后续提交中接入，避免一次性铺开难以回溯。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/flows")
public class ContractFlowController {

    private final ContractFlowService flowService;
    private final FlowTimelineService timelineService;
    private final ContractAccessPolicy accessPolicy;

    /** 当前轮 + 当前节点 + 持有者。无流程返回 {@code flow=null}。 */
    @GetMapping("/cases/{caseId}/current")
    public Result<Map<String, Object>> current(@PathVariable Long caseId) {
        accessPolicy.checkAccess(caseId);
        Map<String, Object> current = flowService.current(caseId);
        return Result.ok(current == null ? Map.of("flow", null) : current);
    }

    /** 时间轴：里程碑 + 事件流，{@code (created_at,id)} 游标翻页。 */
    @GetMapping("/cases/{caseId}/timeline")
    public Result<Map<String, Object>> timeline(@PathVariable Long caseId,
                                                @RequestParam(required = false) String cursor,
                                                @RequestParam(required = false) Integer limit) {
        accessPolicy.checkAccess(caseId);
        return Result.ok(timelineService.timeline(caseId, cursor, limit));
    }

    @PostMapping("/cases/{caseId}/confirm-elements")
    public Result<Void> confirmElements(@PathVariable Long caseId) {
        accessPolicy.checkAccess(caseId);
        flowService.confirmElements(caseId, StpUtil.getLoginIdAsLong());
        return Result.ok();
    }

    @PostMapping("/cases/{caseId}/confirm-timeline")
    public Result<Void> confirmTimeline(@PathVariable Long caseId) {
        accessPolicy.checkAccess(caseId);
        flowService.confirmTimeline(caseId, StpUtil.getLoginIdAsLong());
        return Result.ok();
    }

    /** 修改实质字段，body: {@code {fields: {...}, reason: "..."}}。 */
    @PostMapping("/cases/{caseId}/edit")
    @SuppressWarnings("unchecked")
    public Result<Map<String, Object>> edit(@PathVariable Long caseId,
                                            @RequestBody Map<String, Object> body) {
        accessPolicy.checkAccess(caseId);
        Object fields = body.get("fields");
        if (!(fields instanceof Map<?, ?> map)) {
            throw new IllegalArgumentException("fields 必须是对象");
        }
        Object reason = body.get("reason");
        boolean substantive = flowService.editContent(caseId, StpUtil.getLoginIdAsLong(),
                (Map<String, Object>) map, reason == null ? null : String.valueOf(reason));
        return Result.ok(Map.of("substantive", substantive));
    }

    /** 上传新版本 / 切换版本，body: {@code {versionId: 2, mode: "UPLOAD"}}。 */
    @PostMapping("/cases/{caseId}/version")
    public Result<Void> switchVersion(@PathVariable Long caseId,
                                      @RequestBody Map<String, Object> body) {
        accessPolicy.checkAccess(caseId);
        Object versionId = body.get("versionId");
        if (versionId == null) {
            throw new IllegalArgumentException("缺少 versionId");
        }
        Long version = versionId instanceof Number n
                ? n.longValue() : Long.valueOf(String.valueOf(versionId));
        String mode = body.get("mode") == null ? "UPLOAD" : String.valueOf(body.get("mode"));
        flowService.switchVersion(caseId, StpUtil.getLoginIdAsLong(), version, mode);
        return Result.ok();
    }
}

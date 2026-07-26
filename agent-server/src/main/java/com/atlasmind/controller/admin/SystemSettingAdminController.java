package com.atlasmind.controller.admin;

import com.atlasmind.annotation.OperationLog;
import com.atlasmind.common.Result;
import com.atlasmind.entity.SystemSetting;
import com.atlasmind.service.SystemSettingService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 管理端运行配置接口。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/admin/settings")
public class SystemSettingAdminController {

    private final SystemSettingService systemSettingService;

    @GetMapping("/runtime")
    public Result<List<SystemSetting>> runtime() {
        return Result.ok(systemSettingService.listRuntimeSettings());
    }

    @OperationLog(value = "更新系统运行配置", type = "UPDATE")
    @PutMapping("/runtime")
    public Result<List<SystemSetting>> updateRuntime(@RequestBody Map<String, Object> values) {
        return Result.ok(systemSettingService.updateRuntimeSettings(values));
    }
}

package com.atlasmind.controller;

import com.atlasmind.common.Result;
import com.atlasmind.entity.User;
import com.atlasmind.service.SystemSettingService;
import com.atlasmind.service.UserService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * 公开站点信息接口：返回站点拥有者的公开资料（昵称/头像/社交链接等），无需登录。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/site")
public class SiteController {

    private final UserService userService;
    private final SystemSettingService systemSettingService;

    @GetMapping("/info")
    public Result<User> info() {
        return Result.ok(userService.getSiteInfo());
    }

    @GetMapping("/runtime-config")
    public Result<Map<String, Object>> runtimeConfig() {
        return Result.ok(systemSettingService.publicRuntimeConfig());
    }
}

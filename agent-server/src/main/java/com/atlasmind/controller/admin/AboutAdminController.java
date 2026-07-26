package com.atlasmind.controller.admin;

import com.atlasmind.annotation.OperationLog;
import com.atlasmind.common.Result;
import com.atlasmind.entity.About;
import com.atlasmind.service.AboutService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * 后台关于页管理（需登录）：查询和更新关于页内容。
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/admin/about")
public class AboutAdminController {

    private final AboutService aboutService;

    @GetMapping
    public Result<About> get() {
        return Result.ok(aboutService.get());
    }

    @OperationLog(value = "更新关于页面", type = "UPDATE")
    @PutMapping
    public Result<?> update(@RequestBody Map<String, String> body) {
        aboutService.update(body.get("content"), body.get("timeline"));
        return Result.ok();
    }
}

package com.atlasmind.service;

import com.atlasmind.entity.SystemSetting;

import java.util.List;
import java.util.Map;

/**
 * 系统运行配置服务。
 */
public interface SystemSettingService {

    List<SystemSetting> listRuntimeSettings();

    List<SystemSetting> updateRuntimeSettings(Map<String, Object> values);

    Map<String, Object> publicRuntimeConfig();
}

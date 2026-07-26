package com.atlasmind.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.atlasmind.entity.SystemSetting;
import com.atlasmind.mapper.SystemSettingMapper;
import com.atlasmind.service.SystemSettingService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 系统运行配置实现，负责默认值、范围校验和公开配置裁剪。
 */
@Service
@RequiredArgsConstructor
public class SystemSettingServiceImpl implements SystemSettingService {

    private static final String TOP_K = "ai.retrieval.top-k";
    private static final String MAX_TOP_K = "ai.retrieval.max-top-k";
    private static final String AI_ENABLED = "ai.enabled";

    private final SystemSettingMapper settingMapper;

    @Override
    public List<SystemSetting> listRuntimeSettings() {
        ensureDefaults();
        return settingMapper.selectList(new LambdaQueryWrapper<SystemSetting>()
                .in(SystemSetting::getSettingKey, TOP_K, MAX_TOP_K, AI_ENABLED)
                .orderByAsc(SystemSetting::getId));
    }

    @Override
    @Transactional
    public List<SystemSetting> updateRuntimeSettings(Map<String, Object> values) {
        ensureDefaults();
        updateInteger(TOP_K, values.get(TOP_K), 1, 20);
        updateInteger(MAX_TOP_K, values.get(MAX_TOP_K), 1, 20);
        int maxTopK = readInt(MAX_TOP_K, 10);
        if (readInt(TOP_K, 5) > maxTopK) {
            updateValue(TOP_K, String.valueOf(maxTopK));
        }
        if (values.containsKey(AI_ENABLED)) {
            updateValue(AI_ENABLED, String.valueOf(values.get(AI_ENABLED)));
        }
        return listRuntimeSettings();
    }

    @Override
    public Map<String, Object> publicRuntimeConfig() {
        ensureDefaults();
        int topK = readInt(TOP_K, 5);
        int maxTopK = readInt(MAX_TOP_K, 10);
        return Map.of(
                "aiEnabled", readBoolean(AI_ENABLED, true),
                "aiTopK", Math.min(topK, maxTopK),
                "aiMaxTopK", maxTopK
        );
    }

    private void ensureDefaults() {
        createIfMissing(TOP_K, "5", "INTEGER", "AI 默认检索数量", 1);
        createIfMissing(MAX_TOP_K, "10", "INTEGER", "AI 最大检索数量", 1);
        createIfMissing(AI_ENABLED, "true", "BOOLEAN", "是否启用用户端 AI", 1);
    }

    private void createIfMissing(String key, String value, String type, String description, int editable) {
        SystemSetting existing = settingMapper.selectOne(new LambdaQueryWrapper<SystemSetting>()
                .eq(SystemSetting::getSettingKey, key)
                .last("LIMIT 1"));
        if (existing != null) return;
        SystemSetting setting = new SystemSetting();
        setting.setSettingKey(key);
        setting.setSettingValue(value);
        setting.setValueType(type);
        setting.setDescription(description);
        setting.setEditable(editable);
        settingMapper.insert(setting);
    }

    private void updateInteger(String key, Object value, int min, int max) {
        if (value == null) return;
        int parsed;
        try {
            parsed = Integer.parseInt(String.valueOf(value));
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException(key + " 必须是整数");
        }
        if (parsed < min || parsed > max) {
            throw new IllegalArgumentException(key + " 必须在 " + min + " 到 " + max + " 之间");
        }
        updateValue(key, String.valueOf(parsed));
    }

    private void updateValue(String key, String value) {
        SystemSetting setting = settingMapper.selectOne(new LambdaQueryWrapper<SystemSetting>()
                .eq(SystemSetting::getSettingKey, key)
                .last("LIMIT 1"));
        if (setting == null) return;
        setting.setSettingValue(value);
        settingMapper.updateById(setting);
    }

    private int readInt(String key, int fallback) {
        try {
            return Integer.parseInt(readValue(key, String.valueOf(fallback)));
        } catch (NumberFormatException e) {
            return fallback;
        }
    }

    private boolean readBoolean(String key, boolean fallback) {
        String value = readValue(key, String.valueOf(fallback));
        return Boolean.parseBoolean(value);
    }

    private String readValue(String key, String fallback) {
        SystemSetting setting = settingMapper.selectOne(new LambdaQueryWrapper<SystemSetting>()
                .eq(SystemSetting::getSettingKey, key)
                .last("LIMIT 1"));
        return setting == null || setting.getSettingValue() == null
                ? fallback
                : setting.getSettingValue();
    }
}

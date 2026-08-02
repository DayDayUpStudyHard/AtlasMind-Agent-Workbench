package com.atlasmind.config;

import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Simple key-value configuration store backed by the {@code system_config} table.
 *
 * <p>Values are cached for 30 seconds so that a runtime mode switch
 * ({@code AGENT_RUNTIME}) takes effect without a restart.</p>
 */
@Component
@RequiredArgsConstructor
public class SystemConfigRepository {

    private final JdbcTemplate jdbcTemplate;

    private static final long CACHE_TTL_MILLIS = 30_000;

    private final AtomicReference<CachedEntry> cached = new AtomicReference<>();

    /**
     * Read a config value, returning {@code defaultValue} when the key is absent.
     */
    public String get(String key, String defaultValue) {
        CachedEntry entry = cached.get();
        if (entry != null && entry.key.equals(key) && isFresh(entry)) {
            return entry.value == null ? defaultValue : entry.value;
        }
        String value = load(key);
        cached.set(new CachedEntry(key, value, Instant.now().toEpochMilli()));
        return value == null ? defaultValue : value;
    }

    /**
     * Explicitly invalidate the cache (optional — useful after writes).
     */
    public void invalidate() {
        cached.set(null);
    }

    private String load(String key) {
        try {
            return jdbcTemplate.queryForObject(
                    "SELECT config_value FROM system_config WHERE config_key = ?",
                    String.class,
                    key
            );
        } catch (Exception e) {
            return null;
        }
    }

    private boolean isFresh(CachedEntry entry) {
        return (Instant.now().toEpochMilli() - entry.loadedAt) < CACHE_TTL_MILLIS;
    }

    private record CachedEntry(String key, String value, long loadedAt) {}
}

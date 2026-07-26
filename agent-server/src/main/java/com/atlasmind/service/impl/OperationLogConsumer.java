package com.atlasmind.service.impl;

import com.atlasmind.entity.OperationLog;
import com.atlasmind.mapper.OperationLogMapper;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.RedisSystemException;
import org.springframework.data.redis.connection.stream.Consumer;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.ReadOffset;
import org.springframework.data.redis.connection.stream.StreamOffset;
import org.springframework.data.redis.core.StreamOperations;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 操作日志 Redis Stream 消费者 — 替代 {@code @Async} 直接写 DB。
 *
 * <h3>架构</h3>
 * <pre>
 * 请求 → OperationLogAspect → Redis Stream (oplog:stream) → 本消费者 → 批量写入 MySQL
 * </pre>
 *
 * <h3>特性</h3>
 * <ul>
 *   <li><b>解耦</b>：日志写入与请求线程完全分离，接口响应不受 DB 写入影响</li>
 *   <li><b>削峰</b>：Stream 作为缓冲区，高并发时积压消息不丢</li>
 *   <li><b>消费者组</b>：支持多实例部署（消费者组自动负载均衡），支持消息 ACK + 重放</li>
 *   <li><b>批量写入</b>：每次拉取最多 20 条，减少 DB 连接开销</li>
 * </ul>
 */
@Component
public class OperationLogConsumer {

    private static final Logger log = LoggerFactory.getLogger(OperationLogConsumer.class);
    private static final String STREAM_KEY = "oplog:stream";
    private static final String GROUP = "oplog-consumers";
    private static final String CONSUMER_NAME = "consumer-1";

    private final StringRedisTemplate redisTemplate;
    private final OperationLogMapper operationLogMapper;

    public OperationLogConsumer(StringRedisTemplate redisTemplate, OperationLogMapper operationLogMapper) {
        this.redisTemplate = redisTemplate;
        this.operationLogMapper = operationLogMapper;
    }

    private volatile boolean disabled = false;

    /** 启动时创建消费者组（已存在则忽略，不支持则降级） */
    @PostConstruct
    public void init() {
        try {
            redisTemplate.opsForStream().createGroup(STREAM_KEY, GROUP);
            log.info("[OpLog] 消费者组创建成功: {} / {} / {}", STREAM_KEY, GROUP, CONSUMER_NAME);
        } catch (RedisSystemException e) {
            log.debug("[OpLog] 消费者组已存在: {}", GROUP);
        } catch (Exception e) {
            // Redis 版本不支持 Stream（如 Windows Redis 3.x）→ 降级为 @Async 直写
            disabled = true;
            log.warn("[OpLog] Redis 不支持 Stream ({}), 降级为 @Async 直写 DB", e.getMessage().split("\n")[0]);
        }
    }

    /** 每秒轮询 Redis Stream，批量写入 MySQL */
    @SuppressWarnings("unchecked")
    @Scheduled(fixedDelay = 1000)
    public void consume() {
        if (disabled) return;
        StreamOperations<String, Object, Object> ops = redisTemplate.opsForStream();
        try {
            List<MapRecord<String, Object, Object>> records = ops.read(
                    Consumer.from(GROUP, CONSUMER_NAME),
                    org.springframework.data.redis.connection.stream.StreamReadOptions.empty()
                            .count(20)
                            .block(Duration.ofSeconds(1)),
                    StreamOffset.create(STREAM_KEY, ReadOffset.lastConsumed())
            );

            if (records == null || records.isEmpty()) {
                return;
            }

            List<OperationLog> batch = new ArrayList<>();
            for (MapRecord<String, Object, Object> record : records) {
                try {
                    batch.add(toEntity(record.getValue()));
                } catch (Exception e) {
                    log.warn("[OpLog] 解析失败: {}", e.getMessage());
                }
            }

            // 批量写入
            if (!batch.isEmpty()) {
                for (OperationLog entry : batch) {
                    operationLogMapper.insert(entry);
                }
                log.debug("[OpLog] 批量写入 {} 条", batch.size());
            }

            // 确认消费
            for (MapRecord<String, Object, Object> record : records) {
                ops.acknowledge(STREAM_KEY, GROUP, record.getId());
            }
        } catch (Exception e) {
            log.warn("[OpLog] 消费异常: {}", e.getMessage());
        }
    }

    /** MapRecord fields → OperationLog */
    private OperationLog toEntity(Map<Object, Object> fields) {
        OperationLog entry = new OperationLog();
        entry.setUsername(str(fields, "username"));
        entry.setIp(str(fields, "ip"));
        entry.setOperation(str(fields, "operation"));
        entry.setType(str(fields, "type"));
        entry.setMethodName(str(fields, "methodName"));
        entry.setArgs(str(fields, "args"));
        String et = str(fields, "executionTime");
        if (et != null && !et.isEmpty()) {
            entry.setExecutionTime(Long.parseLong(et));
        }
        String ct = str(fields, "createTime");
        if (ct != null && !ct.isEmpty()) {
            entry.setCreateTime(LocalDateTime.parse(ct));
        }
        return entry;
    }

    private static String str(Map<Object, Object> map, String key) {
        Object v = map.get(key);
        return v != null ? v.toString() : null;
    }
}

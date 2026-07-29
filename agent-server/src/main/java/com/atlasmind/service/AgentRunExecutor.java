package com.atlasmind.service;

import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;

/**
 * 独立异步执行器，避免 Controller 请求线程持有长时间分析任务。
 */
@Component
@RequiredArgsConstructor
public class AgentRunExecutor {

    private final ObjectProvider<AgentProjectService> agentProjectService;

    @Async("agentTaskExecutor")
    public void execute(Long runId) {
        agentProjectService.getObject().executeRun(runId);
    }
}

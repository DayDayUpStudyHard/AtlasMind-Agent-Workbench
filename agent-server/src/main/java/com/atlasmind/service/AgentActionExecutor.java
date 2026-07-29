package com.atlasmind.service;

import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class AgentActionExecutor {

    private final ObjectProvider<AgentProjectService> agentProjectService;

    @Async("agentTaskExecutor")
    public void execute(Long runId, Long actionId) {
        agentProjectService.getObject().executeAction(runId, actionId);
    }
}

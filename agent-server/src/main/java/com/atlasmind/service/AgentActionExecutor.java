package com.atlasmind.service;

import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class AgentActionExecutor {

    private final ObjectProvider<ContractCaseService> contractCaseService;

    @Async("agentTaskExecutor")
    public void execute(Long runId, Long actionId) {
        contractCaseService.getObject().executeAction(runId, actionId);
    }
}

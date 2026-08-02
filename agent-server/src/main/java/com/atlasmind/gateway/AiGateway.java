package com.atlasmind.gateway;

import java.util.Map;

/**
 * Java 主后端访问 AI 微服务的统一接口。
 *
 * <p>调用方只关心知识库业务动作，不需要了解 Python 服务地址、HTTP
 * 方法、超时和响应解析细节。</p>
 */
public interface AiGateway {

    void triggerIngest(Map<String, Object> payload);

    void triggerReindex(Long documentId, Map<String, Object> payload);

    void deleteDocumentIndex(Long documentId);

    Map<String, Object> testRetrieval(Map<String, Object> payload);

    Map<String, Object> analyzeProject(Map<String, Object> payload);

    Map<String, Object> runProjectTask(Map<String, Object> payload);

    Map<String, Object> planAgent(Map<String, Object> payload);

    Map<String, Object> nextAgentTurn(Map<String, Object> payload);

    Map<String, Object> reflectAgent(Map<String, Object> payload);

    Map<String, Object> startAgentRun(Map<String, Object> payload);

    Map<String, Object> getAgentRun(Long runId);

    Map<String, Object> cancelAgentRun(Long runId, Map<String, Object> payload);

    Map<String, Object> health();
}

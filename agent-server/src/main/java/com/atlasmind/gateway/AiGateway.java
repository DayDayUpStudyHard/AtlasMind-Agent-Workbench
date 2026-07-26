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
}

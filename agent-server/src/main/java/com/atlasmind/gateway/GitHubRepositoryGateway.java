package com.atlasmind.gateway;

import java.util.List;
import java.util.Map;

/**
 * Read-only GitHub connector used by project evidence sync.
 */
public interface GitHubRepositoryGateway {

    List<Map<String, Object>> collectEvidence(String repositoryUrl, String branch);
}

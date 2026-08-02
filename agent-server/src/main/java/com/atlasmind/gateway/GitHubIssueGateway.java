package com.atlasmind.gateway;

import java.util.Map;

/**
 * GitHub write operations boundary — used by ContractOps approval actions.
 */
public interface GitHubIssueGateway {

    Map<String, Object> createIssue(String repositoryUrl, String title, String body);

    Map<String, Object> createMilestone(String repositoryUrl, String title,
                                        String description, String dueOn);
}

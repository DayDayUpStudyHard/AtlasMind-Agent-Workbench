package com.atlasmind.gateway;

import java.util.Map;

/**
 * GitHub 写操作边界。实现可以替换为企业内部 GitHub App 或 Mock connector。
 */
public interface GitHubIssueGateway {

    Map<String, Object> createIssue(String repositoryUrl, String title, String body);

    Map<String, Object> createMilestone(String repositoryUrl, String title,
                                        String description, String dueOn);
}

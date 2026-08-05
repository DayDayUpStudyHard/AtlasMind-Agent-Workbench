"""Coverage reflection — domain matrix, not boolean adequate."""

from __future__ import annotations

from typing import Any


def coverage_reflection(state: dict[str, Any]) -> dict[str, Any]:
    """Compute domain coverage matrix from validated findings.

    Returns status: CONFIRMED | NEED_MORE_EVIDENCE | CANNOT_RESOLVE
    """
    validated = state.get("validated_findings") or []
    domain_tasks = state.get("domain_tasks") or []
    domain_analysis = state.get("domain_analysis") or {}

    # Build coverage per domain
    domains: dict[str, dict] = {}
    for task in domain_tasks:
        domain = str(task.get("domainKey") or task.get("domain") or "")
        analysis = domain_analysis.get(domain) or {}
        domains[domain] = {
            "domainName": task.get("domainName") or task.get("domain") or domain,
            "covered": analysis.get("status") == "COMPLETED",
            "analysisStatus": analysis.get("status") or "MISSING",
            "issues": [],
            "findingCount": 0,
        }

    # Check each domain
    for finding in validated:
        finding_domain = str(finding.get("domainKey") or "")
        evidence_status = str(finding.get("evidenceStatus", "")).upper()

        if finding_domain in domains:
            domains[finding_domain]["findingCount"] += 1
            if evidence_status == "MISSING":
                domains[finding_domain]["issues"].append(
                    f"{finding.get('title', '')}: missing citation"
                )

    # Determine coverage
    all_covered = True
    any_covered = False
    missing_domains = []
    for domain, info in domains.items():
        if info["covered"]:
            any_covered = True
        else:
            all_covered = False
            missing_domains.append(domain)

    retry_count = state.get("retry_state", {}).get("reflection_rounds", 0)

    if all_covered:
        status = "CONFIRMED"
        next_queries = []
    elif retry_count >= 2:
        status = "CANNOT_RESOLVE"
        next_queries = []
    else:
        status = "NEED_MORE_EVIDENCE"
        next_queries = [
            f"{domains[domain].get('domainName', domain)} 合同条款 企业制度 审查"
            for domain in missing_domains[:3]
        ]

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "coverage_reflection",
        "coverage": {
            "status": status,
            "domains": domains,
            "missingDomains": missing_domains,
            "retryable": status == "NEED_MORE_EVIDENCE",
        },
        "reflection": {
            "adequate": status == "CONFIRMED",
            "status": status,
            "domains": domains,
            "nextQueries": next_queries,
            "retryable": status == "NEED_MORE_EVIDENCE",
        },
        "errors": state.get("errors", []) + (
            [{"node": "coverage_reflection", "error": f"domains not covered: {missing_domains}"}]
            if missing_domains else []
        ),
    }


def targeted_retrieval(state: dict[str, Any]) -> dict[str, Any]:
    """Expand queries for uncovered domains and execute a real second retrieval."""
    retry_state = state.get("retry_state") or {}
    retry_state["reflection_rounds"] = retry_state.get("reflection_rounds", 0) + 1

    missing = set((state.get("coverage") or {}).get("missingDomains") or [])
    tasks = []
    for raw in state.get("domain_tasks") or []:
        key = str(raw.get("domainKey") or raw.get("domain") or "")
        if key not in missing:
            continue
        task = dict(raw)
        task["queries"] = list(task.get("queries") or []) + [
            f"{task.get('domainName') or task.get('domain')} 风险 审查要求 缺失条款 例外"
        ]
        tasks.append(task)

    domain_results = dict(state.get("domain_results") or {})
    citations: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    if tasks:
        from .retrieval import retrieve_domain_evidence

        retrieved = retrieve_domain_evidence({**state, "domain_tasks": tasks})
        domain_results.update(retrieved.get("domain_results") or {})
        citations = retrieved.get("citations") or []
        observations = retrieved.get("observations") or []

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "targeted_retrieval",
        "retry_state": retry_state,
        "domain_results": domain_results,
        "citations": citations,
        "observations": observations,
    }

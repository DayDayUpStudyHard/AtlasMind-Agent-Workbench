"""Coverage reflection - domain matrix with review checklist."""

from __future__ import annotations

from typing import Any


def _domain_source_counts(evidence: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in evidence:
        source_type = str(item.get("sourceType") or "UNKNOWN")
        counts[source_type] = counts.get(source_type, 0) + 1
    return counts


def _domain_highlights(findings: list[dict[str, Any]], evidence: list[dict[str, Any]]) -> list[str]:
    highlights: list[str] = []
    for finding in findings[:3]:
        title = str(finding.get("title") or finding.get("oneLineSummary") or "").strip()
        if title:
            highlights.append(title[:120])
    if not highlights:
        for item in evidence[:2]:
            snippet = str(item.get("snippet") or item.get("title") or item.get("clauseText") or "").strip()
            if snippet:
                highlights.append(snippet[:120])
    return highlights[:3]


def _domain_state(
    task: dict[str, Any],
    analysis: dict[str, Any],
    findings: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> tuple[str, str, int, int]:
    analysis_status = str(analysis.get("status") or "MISSING").upper()
    finding_count = len(findings)
    evidence_count = len(evidence)
    low_confidence_count = sum(
        1 for finding in findings if str(finding.get("confidenceLevel") or "").upper() == "LOW"
    )

    label = task.get("domainName") or task.get("domainKey") or "UNKNOWN"
    if analysis_status != "COMPLETED":
        if evidence_count == 0:
            return "MISSING", f"{label} 未检索到可用证据，且分析未完成", finding_count, evidence_count
        return "AMBIGUOUS", f"{label} 已检索到证据，但分析状态为 {analysis_status}", finding_count, evidence_count

    if evidence_count == 0:
        return "MISSING", f"{label} 未检索到可用证据", finding_count, evidence_count
    if finding_count == 0:
        return "PARTIAL", f"{label} 有证据但未形成可落地发现", finding_count, evidence_count
    if low_confidence_count >= max(2, finding_count // 2 + 1):
        return "AMBIGUOUS", f"{label} 发现较多低置信度结果，需要补证复核", finding_count, evidence_count
    return "COVERED", f"{label} 已形成可核验发现", finding_count, evidence_count


def coverage_reflection(state: dict[str, Any]) -> dict[str, Any]:
    """Compute a domain coverage matrix from validated findings."""
    validated = state.get("validated_findings") or []
    domain_tasks = state.get("domain_tasks") or []
    domain_analysis = state.get("domain_analysis") or {}
    domain_results = state.get("domain_results") or {}

    findings_by_domain: dict[str, list[dict[str, Any]]] = {}
    for finding in validated:
        domain_key = str(finding.get("domainKey") or finding.get("domain_key") or "")
        if not domain_key:
            continue
        findings_by_domain.setdefault(domain_key, []).append(finding)

    domains: dict[str, dict[str, Any]] = {}
    checklist: list[dict[str, Any]] = []
    for task in domain_tasks:
        domain = str(task.get("domainKey") or task.get("domain") or "")
        analysis = domain_analysis.get(domain) or {}
        evidence = domain_results.get(domain) or []
        findings = findings_by_domain.get(domain) or []
        coverage_state, reason, finding_count, evidence_count = _domain_state(task, analysis, findings, evidence)
        source_counts = _domain_source_counts(evidence)

        domains[domain] = {
            "domainName": task.get("domainName") or task.get("domain") or domain,
            "covered": coverage_state == "COVERED",
            "coverageState": coverage_state,
            "analysisStatus": analysis.get("status") or "MISSING",
            "priority": task.get("priority") or "MEDIUM",
            "requiredClauseTypes": list(task.get("requiredClauseTypes") or []),
            "findingCount": finding_count,
            "evidenceCount": evidence_count,
            "sourceCounts": source_counts,
            "issues": [],
            "reason": reason,
            "highlights": _domain_highlights(findings, evidence),
            "nextQueries": list(task.get("queries") or [])[:3],
        }
        checklist.append({
            "domainKey": domain,
            "domainName": domains[domain]["domainName"],
            "priority": domains[domain]["priority"],
            "requiredClauseTypes": domains[domain]["requiredClauseTypes"],
            "coverageState": coverage_state,
            "analysisStatus": domains[domain]["analysisStatus"],
            "findingCount": finding_count,
            "evidenceCount": evidence_count,
            "sourceCounts": source_counts,
            "reason": reason,
            "highlights": domains[domain]["highlights"],
            "nextQueries": domains[domain]["nextQueries"],
            "source": task.get("source") or "LLM_DYNAMIC",
        })

    for finding in validated:
        finding_domain = str(finding.get("domainKey") or "")
        evidence_status = str(finding.get("evidenceStatus", "")).upper()
        if finding_domain in domains and evidence_status == "MISSING":
            domains[finding_domain]["issues"].append(
                f"{finding.get('title', '')}: missing citation"
            )

    missing_domains: list[str] = []
    partial_domains: list[str] = []
    ambiguous_domains: list[str] = []
    for domain, info in domains.items():
        if info["covered"]:
            continue
        missing_domains.append(domain)
        if info.get("coverageState") == "AMBIGUOUS":
            ambiguous_domains.append(domain)
        else:
            partial_domains.append(domain)

    summary = {
        "totalDomains": len(domains),
        "coveredDomains": sum(1 for item in domains.values() if item.get("coverageState") == "COVERED"),
        "partialDomains": sum(1 for item in domains.values() if item.get("coverageState") == "PARTIAL"),
        "missingDomains": sum(1 for item in domains.values() if item.get("coverageState") == "MISSING"),
        "ambiguousDomains": sum(1 for item in domains.values() if item.get("coverageState") == "AMBIGUOUS"),
        "highPriorityGaps": [
            item["domainKey"] for item in checklist
            if item.get("priority") == "HIGH" and item.get("coverageState") != "COVERED"
        ],
    }

    retry_count = state.get("retry_state", {}).get("reflection_rounds", 0)
    if not missing_domains:
        status = "CONFIRMED"
        next_queries: list[str] = []
    elif retry_count >= 2:
        status = "CANNOT_RESOLVE"
        next_queries = []
    else:
        status = "NEED_MORE_EVIDENCE"
        next_queries = [
            query
            for domain in missing_domains[:3]
            for query in (domains[domain].get("nextQueries") or [domains[domain].get("domainName", domain)])[:2]
        ]

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "coverage_reflection",
        "coverage": {
            "status": status,
            "domains": domains,
            "missingDomains": missing_domains,
            "partialDomains": partial_domains,
            "ambiguousDomains": ambiguous_domains,
            "summary": summary,
            "checklist": checklist,
            "retryable": status == "NEED_MORE_EVIDENCE",
        },
        "reflection": {
            "adequate": status == "CONFIRMED",
            "status": status,
            "domains": domains,
            "summary": summary,
            "checklist": checklist,
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
            f"{task.get('domainName') or task.get('domain')} 风险 审查 需要补充条款 例外"
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

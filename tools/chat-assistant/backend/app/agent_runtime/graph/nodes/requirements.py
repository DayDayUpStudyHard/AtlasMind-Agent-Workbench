"""Fulfillment requirements decomposition — one timeline node → N sub-items."""

from __future__ import annotations

from typing import Any


def decompose_requirements(state: dict[str, Any]) -> dict[str, Any]:
    """Decompose a timeline node's obligations into fulfillment sub-items.

    Each sub-item has: requirementId, requirement, required, sourceCitationIds,
    acceptanceCriteria, responsibleParty, evidenceExpected, ambiguity.
    """
    case_snapshot = state.get("case_snapshot") or {}
    task_input = state.get("task_input") or {}
    timeline_node_id = int(task_input.get("timelineNodeId", 0))

    # Load timeline node from DB
    try:
        from ...persistence import _conn

        with _conn() as conn:
            with conn.cursor() as cur:
                from ...persistence import _normalize_value

                cur.execute(
                    """SELECT n.id, n.clause_id AS clauseId,
                              n.node_type AS nodeType, n.label,
                              n.business_meaning AS businessMeaning,
                              n.responsible_party AS responsibleParty,
                              n.citation_json AS citationJson,
                              c.clause_number AS clauseNumber, c.content AS clauseContent
                       FROM contract_timeline_node n
                       LEFT JOIN contract_clause c ON c.id=n.clause_id
                       WHERE n.id=%s AND n.case_id=%s""",
                    (timeline_node_id, state.get("subject_id", 0)),
                )
                row = cur.fetchone()
                node = _normalize_value(row) if row else {}
        if not node:
            return {
                "errors": state.get("errors", []) + [
                    {"node": "decompose_requirements", "error": "timeline node not found"}
                ],
            }
    except Exception as exc:
        return {
            "errors": state.get("errors", []) + [
                {"node": "decompose_requirements", "error": str(exc)}
            ],
        }

    # Build requirement items from node
    node_type = str(node.get("nodeType") or "OTHER").upper()
    label = str(node.get("label") or "")
    business_meaning = str(node.get("businessMeaning") or "")
    clause_content = str(node.get("clauseContent") or "")[:12000]

    items: list[dict] = []
    item_idx = 0

    def _add(requirement: str, required: bool = True, criteria: str = ""):
        nonlocal item_idx
        item_idx += 1
        items.append({
            "requirementId": f"req-{item_idx}",
            "requirement": requirement,
            "required": required,
            "sourceCitationIds": (
                [f"CONTRACT_CLAUSE:{node.get('clauseId', '')}"]
                if node.get("clauseId") else []
            ),
            "acceptanceCriteria": criteria,
            "responsibleParty": str(node.get("responsibleParty") or "UNKNOWN"),
            "evidenceExpected": [],
            "ambiguity": "",
        })

    # Type-specific decomposition
    if node_type == "PAYMENT":
        _add(f"完成付款：{label}", criteria="付款记录、银行回单或发票")
        _add("付款金额符合合同约定", criteria="合同金额与付款凭证一致")
        if "发票" in business_meaning or "发票" in clause_content:
            _add("取得合规发票", criteria="发票信息与合同一致")
    elif node_type == "DELIVERY":
        _add(f"完成交付：{label}", criteria="交付报告、成果物或签收记录")
        _add("交付内容符合合同要求", criteria="交付物清单与合同一致")
    elif node_type == "ACCEPTANCE":
        _add(f"完成验收：{label}", criteria="验收单、验收会议纪要或测试报告")
        _add("验收标准符合合同约定", criteria="验收结果与合同验收条款一致")
    elif node_type == "NOTICE":
        _add(f"发送通知：{label}", criteria="书面通知记录或邮件")
    elif node_type == "RENEWAL":
        _add(f"完成续签评估：{label}", criteria="续签商谈记录或审批意见")
    elif node_type == "TERMINATION":
        _add(f"执行终止：{label}", criteria="解除/终止通知及双方确认")
    else:
        _add(f"完成节点要求：{label or business_meaning or '合同履约节点'}",
              criteria="合同约定证明材料")

    # Mark vague terms
    for item in items:
        req_text = item.get("requirement", "")
        if any(term in req_text + clause_content for term in ("甲方满意", "另行确认", "符合要求")):
            item["ambiguity"] = "合同标准为主观判断，缺少客观可量化指标"

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "decompose_requirements",
        "domain_tasks": items,  # Reuse domain_tasks field for requirements
    }

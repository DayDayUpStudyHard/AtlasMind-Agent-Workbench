"""Fulfillment requirements decomposition - one timeline node to many sub-items."""

from __future__ import annotations

from typing import Any


def decompose_requirements(state: dict[str, Any]) -> dict[str, Any]:
    """Decompose a timeline node's obligations into fulfillment sub-items."""
    task_input = state.get("task_input") or {}
    timeline_node_id = int(task_input.get("timelineNodeId", 0))

    try:
        from ...persistence import _conn, _normalize_value

        with _conn() as conn:
            with conn.cursor() as cur:
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

    node_type = str(node.get("nodeType") or "OTHER").upper()
    label = str(node.get("label") or "")
    business_meaning = str(node.get("businessMeaning") or "")
    clause_content = str(node.get("clauseContent") or "")[:12000]

    items: list[dict[str, Any]] = []
    item_idx = 0

    def _material_hint(text: str) -> list[str]:
        hints: list[str] = []
        lookup = text + " " + clause_content + " " + business_meaning
        mapping = [
            (("报告", "交付", "成果", "研究"), "交付物、报告、成果文件、签收记录"),
            (("付款", "发票", "开票", "收据"), "付款记录、发票、收据、银行流水"),
            (("验收", "审查", "复核"), "验收单、审查结论、复核意见、会议纪要"),
            (("施工", "建设", "安装", "调试"), "施工照片、过程记录、调试记录、签字确认"),
            (("通知", "提醒", "告知"), "书面通知、邮件、回执、送达记录"),
            (("续签", "延期"), "续签协议、延期谈判记录、双方确认函"),
            (("终止", "解除"), "终止通知、解除协议、结算单、交接清单"),
        ]
        for keywords, hint in mapping:
            if any(word in lookup for word in keywords):
                hints.append(hint)
        return list(dict.fromkeys(hints))[:3]

    def _add(requirement: str, required: bool = True, criteria: str = ""):
        nonlocal item_idx
        item_idx += 1
        text = requirement.strip()
        item_hints = _material_hint(text)
        items.append({
            "requirementId": f"req-{item_idx}",
            "requirement": text,
            "required": required,
            "sourceCitationIds": (
                [f"CONTRACT_CLAUSE:{node.get('clauseId', '')}"]
                if node.get("clauseId") else []
            ),
            "acceptanceCriteria": criteria or ("、".join(item_hints[:2]) if item_hints else ""),
            "responsibleParty": str(node.get("responsibleParty") or "UNKNOWN"),
            "evidenceExpected": item_hints,
            "ambiguity": "",
        })

    if node_type == "PAYMENT":
        _add(f"完成付款：{label}", criteria="付款记录、银行回单、发票或收据")
        _add("付款金额符合合同约定", criteria="合同金额与支付凭证一致")
        if "发票" in business_meaning or "发票" in clause_content:
            _add("取得合规发票", criteria="发票抬头、税率和金额符合约定")
    elif node_type == "DELIVERY":
        _add(f"完成交付：{label}", criteria="交付报告、成果物或签收记录")
        _add("交付内容符合合同要求", criteria="交付清单与合同条款一致")
    elif node_type == "ACCEPTANCE":
        _add(f"完成验收：{label}", criteria="验收单、验收会议纪要或测试报告")
        _add("验收标准符合合同约定", criteria="验收结果与合同条款一致")
    elif node_type == "NOTICE":
        _add(f"发出通知：{label}", criteria="书面通知、送达回执或邮件记录")
    elif node_type == "RENEWAL":
        _add(f"完成续签评估：{label}", criteria="续签谈判记录、双方确认函")
    elif node_type == "TERMINATION":
        _add(f"执行终止：{label}", criteria="解除/终止通知及双方确认")
    else:
        _add(
            f"完成节点要求：{label or business_meaning or '合同履约节点'}",
            criteria="合同约定证明材料、履约记录或复核材料",
        )

    for item in items:
        req_text = item.get("requirement", "")
        if any(term in req_text + clause_content for term in ("甲方满意", "另行确认", "符合要求", "视为通过")):
            item["ambiguity"] = "合同标准较主观，缺少可量化指标"

    return {
        "state_revision": state.get("state_revision", 0) + 1,
        "current_node": "decompose_requirements",
        "domain_tasks": items,
        "fulfillment_requirements": items,
    }

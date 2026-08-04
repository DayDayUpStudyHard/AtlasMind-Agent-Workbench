"""End-to-end regression test for inline contract submission and parsing."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from app.agent_runtime.persistence import _conn


BASE_URL = "http://localhost:15174"
POLL_TIMEOUT_SECONDS = 15
CONTRACT_TEXT = (
    "第1条 服务范围：乙方为甲方提供 IT 运维服务。\n"
    "第2条 付款方式：按季度支付，每季度 5 万元。\n"
    "第3条 违约责任：逾期每日按应付款的万分之五支付违约金。"
)


def request(method: str, path: str, body: dict | None = None, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["atlasmind-token"] = token
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{BASE_URL}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise AssertionError(f"{method} {path} could not connect: {exc.reason}") from exc

    if payload.get("code") != 200:
        raise AssertionError(f"{method} {path} failed: {payload}")
    return payload["data"]


def wait_until_ready(case_id: int, document_id: int, token: str) -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        documents = request("GET", f"/api/workspace/contracts/{case_id}/documents", token=token)
        document = next((item for item in documents if item["id"] == document_id), None)
        if document is None:
            raise AssertionError(f"Uploaded document {document_id} disappeared")
        if document["parseStatus"] == "READY":
            return document
        if document["parseStatus"] == "FAILED":
            raise AssertionError(f"Document parsing failed: {document.get('parseError')}")
        time.sleep(0.25)
    raise AssertionError(f"Document {document_id} did not become READY within {POLL_TIMEOUT_SECONDS}s")


def load_clause_types(document_id: int) -> list[str]:
    with _conn() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT clause_type FROM contract_clause WHERE document_id=%s ORDER BY id",
                (document_id,),
            )
            return [str(row["clause_type"]) for row in cursor.fetchall()]


def cleanup_case(case_id: int) -> None:
    """Remove only the uniquely named case created by this test."""
    with _conn() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT title FROM contract_case WHERE id=%s FOR UPDATE", (case_id,)
            )
            row = cursor.fetchone()
            if not row or not str(row["title"]).startswith("inline-contract-e2e-"):
                return
            cursor.execute("DELETE FROM contract_clause WHERE case_id=%s", (case_id,))
            cursor.execute("DELETE FROM contract_document WHERE case_id=%s", (case_id,))
            cursor.execute("DELETE FROM contract_case WHERE id=%s", (case_id,))
        connection.commit()


def main() -> None:
    login = request("POST", "/api/auth/login", {"username": "admin", "password": "admin123"})
    token = login["token"]

    contract_case = request(
        "POST",
        "/api/workspace/contracts",
        {
            "title": f"inline-contract-e2e-{int(time.time())}",
            "contractType": "SERVICE_PROCUREMENT",
            "counterparty": "E2E Test Corp",
            "amount": 200000,
        },
        token,
    )
    case_id = int(contract_case["id"])

    try:
        submitted = request(
            "POST",
            f"/api/workspace/contracts/{case_id}/documents",
            {
                "documentType": "MAIN",
                "fileName": "文字合同回归测试.txt",
                "contentText": CONTRACT_TEXT,
            },
            token,
        )
        document_id = int(submitted["uploadedDocumentId"])
        document = wait_until_ready(case_id, document_id, token)

        content = request(
            "GET",
            f"/api/workspace/contracts/{case_id}/documents/{document_id}/content",
            token=token,
        )
        assert content["contentText"] == CONTRACT_TEXT, "Fetched contract text differs from submitted text"
        assert document["hasInlineText"], "Document list did not expose hasInlineText"
        assert document["textLength"] == len(CONTRACT_TEXT), "Document text length is incorrect"

        clause_types = load_clause_types(document_id)
        expected_types = ["DELIVERY", "PAYMENT", "LIABILITY"]
        assert clause_types == expected_types, f"Expected {expected_types}, got {clause_types}"

        request("DELETE", f"/api/admin/contracts/documents/{document_id}", token=token)
        assert load_clause_types(document_id) == [], "Deleting a document left orphan clauses"

        print(
            f"PASS: case={case_id}, document={document_id}, status=READY, "
            f"clauses={clause_types}, cascadeDelete=OK"
        )
    finally:
        cleanup_case(case_id)


if __name__ == "__main__":
    main()

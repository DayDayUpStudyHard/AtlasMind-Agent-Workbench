"""End-to-end regression for UTF-8 contract intake extraction and confirmation."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from app.agent_runtime.persistence import _conn


BASE_URL = "http://localhost:15174"
POLL_TIMEOUT_SECONDS = 90
TITLE = "技术服务合同"
CONTRACT_TEXT = """技术服务合同
甲方：星河科技有限公司
乙方：云桥信息技术有限公司

第1条 服务内容：乙方为甲方提供企业信息系统运维和技术支持服务。
第2条 合同金额：本合同含税总金额为人民币 12.5 万元。
第3条 付款方式：甲方在验收通过后十个工作日内支付全部合同款。
第4条 合同期限：本合同自2026年8月1日起生效，于2027年7月31日到期。
第5条 违约责任：任何一方违约均应赔偿对方实际损失。
"""


def request(method: str, path: str, body: dict | None = None, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["atlasmind-token"] = token
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc
    if payload.get("code") != 200:
        raise AssertionError(f"{method} {path} failed: {payload}")
    return payload["data"]


def wait_for_intake(intake_id: int, token: str) -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        intake = request("GET", f"/api/workspace/contracts/intakes/{intake_id}", token=token)
        if intake["status"] == "NEEDS_CONFIRMATION":
            return intake
        if intake["status"] == "FAILED":
            raise AssertionError(f"Intake extraction failed: {intake.get('errorMessage')}")
        time.sleep(0.4)
    raise AssertionError(f"Intake {intake_id} did not finish in {POLL_TIMEOUT_SECONDS}s")


def wait_for_document(case_id: int, token: str) -> dict:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        case = request("GET", f"/api/workspace/contracts/{case_id}", token=token)
        if case.get("documents") and case["documents"][0]["parseStatus"] == "READY":
            return case
        time.sleep(0.25)
    raise AssertionError(f"Case {case_id} document did not become READY")


def assert_citations(intake: dict) -> None:
    text = intake["contentText"]
    for key, field in intake["validated"]["fields"].items():
        for citation in field.get("citations", []):
            start = citation["startOffset"]
            end = citation["endOffset"]
            assert text[start:end] == citation["quote"], f"Invalid citation for {key}"


def cleanup(intake_id: int | None, case_id: int | None) -> None:
    with _conn() as connection:
        with connection.cursor() as cursor:
            if case_id:
                cursor.execute("SELECT title FROM contract_case WHERE id=%s FOR UPDATE", (case_id,))
                row = cursor.fetchone()
                if row and row["title"] == TITLE:
                    for table in (
                        "contract_review_finding", "contract_obligation", "contract_clause",
                        "contract_party", "contract_document",
                    ):
                        cursor.execute(f"DELETE FROM {table} WHERE case_id=%s", (case_id,))
                    cursor.execute("DELETE FROM contract_case WHERE id=%s", (case_id,))
            if intake_id:
                cursor.execute(
                    "DELETE FROM contract_intake WHERE id=%s AND file_name=%s",
                    (intake_id, "技术服务合同.txt"),
                )
        connection.commit()


def main() -> None:
    login = request("POST", "/api/auth/login", {"username": "admin", "password": "admin123"})
    token = login["token"]
    intake_id = None
    case_id = None
    try:
        created = request("POST", "/api/workspace/contracts/intakes", {
            "fileName": "技术服务合同.txt",
            "contentText": CONTRACT_TEXT,
        }, token)
        intake_id = int(created["id"])
        intake = wait_for_intake(intake_id, token)
        fields = intake["validated"]["fields"]
        assert fields["contractTitle"]["value"] == TITLE
        assert fields["contractType"]["value"] == "SERVICE_PROCUREMENT"
        assert fields["partyA"]["value"] == "星河科技有限公司"
        assert fields["partyB"]["value"] == "云桥信息技术有限公司"
        assert fields["amount"]["value"] == 125000.0
        assert fields["currency"]["value"] == "CNY"
        assert fields["effectiveDate"]["value"] == "2026-08-01"
        assert fields["expiryDate"]["value"] == "2027-07-31"
        assert intake["validated"]["llmAvailable"] is True
        assert_citations(intake)

        confirmed = request(
            "POST",
            f"/api/workspace/contracts/intakes/{intake_id}/confirm",
            {
                "title": TITLE,
                "contractType": "SERVICE_PROCUREMENT",
                "ourEntity": "星河科技有限公司",
                "counterparty": "云桥信息技术有限公司",
                "amount": 125000,
                "currency": "CNY",
                "effectiveDate": "2026-08-01",
                "expiryDate": "2027-07-31",
                "department": "信息技术部",
                "priority": "NORMAL",
                "description": "合同 Intake E2E",
            },
            token,
        )
        case_id = int(confirmed["case"]["id"])
        case = wait_for_document(case_id, token)
        assert case["ourEntity"] == "星河科技有限公司"
        assert case["counterparty"] == "云桥信息技术有限公司"
        assert float(case["amount"]) == 125000.0
        print(
            f"PASS: intake={intake_id}, case={case_id}, llm={intake['validated']['model']}, "
            f"citations=verified, document={case['documents'][0]['parseStatus']}"
        )
    finally:
        cleanup(intake_id, case_id)


if __name__ == "__main__":
    main()

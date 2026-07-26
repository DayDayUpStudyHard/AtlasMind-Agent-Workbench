"""
pytest 公共 fixtures — base_url、session、登录态、测试数据清理。
"""

import pytest
import requests
import os


# ═══════════════════════════════════════════
# 配置 — 通过环境变量覆盖
# ═══════════════════════════════════════════

BASE_URL = os.getenv("ATLASMIND_BASE_URL", "http://localhost:18080")
ADMIN_USERNAME = os.getenv("ATLASMIND_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ATLASMIND_ADMIN_PASS", "admin123")


# ═══════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════

@pytest.fixture(scope="session")
def base_url():
    """API 根路径，默认 http://localhost:18080。"""
    return BASE_URL


@pytest.fixture(scope="session")
def session():
    """复用 TCP 连接的 requests.Session。"""
    s = requests.Session()
    yield s
    s.close()


@pytest.fixture(scope="session")
def admin_token(base_url, session):
    """登录管理员，返回 Sa-Token token 字符串。"""
    resp = session.post(f"{base_url}/api/auth/login", json={
        "username": ADMIN_USERNAME,
        "password": ADMIN_PASSWORD,
    })
    assert resp.status_code == 200, f"登录失败: {resp.text}"
    data = resp.json()
    assert data["code"] == 200, f"登录返回异常: {data}"
    return data["data"]["token"]


@pytest.fixture(scope="session")
def auth_headers(admin_token):
    """携带管理员 token 的请求头，用于需要登录的接口。"""
    return {"Authorization": f"Bearer {admin_token}"}


# ═══════════════════════════════════════════
# 测试数据追踪 — 用于 teardown 清理
# ═══════════════════════════════════════════

_created_articles = []
_created_tags = []
_created_categories = []
_created_moments = []


@pytest.fixture(scope="session")
def test_data_tracker():
    """返回一个 dict，各测试可将创建的 ID 注册进来，session 结束时统一清理。"""
    tracker = {
        "articles": _created_articles,
        "tags": _created_tags,
        "categories": _created_categories,
        "moments": _created_moments,
    }
    yield tracker
    # teardown: 逆序清理，避免外键约束
    s = requests.Session()
    _login_admin(s)

    for aid in reversed(_created_articles):
        try:
            s.delete(f"{BASE_URL}/api/admin/articles/{aid}")
        except Exception:
            pass
    for mid in reversed(_created_moments):
        try:
            s.delete(f"{BASE_URL}/api/admin/moments/{mid}")
        except Exception:
            pass
    for tid in reversed(_created_tags):
        try:
            s.delete(f"{BASE_URL}/api/admin/tags/{tid}")
        except Exception:
            pass
    for cid in reversed(_created_categories):
        try:
            s.delete(f"{BASE_URL}/api/admin/categories/{cid}")
        except Exception:
            pass
    s.close()


def _login_admin(session):
    """内部：session 登录管理员。"""
    resp = session.post(f"{BASE_URL}/api/auth/login", json={
        "username": ADMIN_USERNAME,
        "password": ADMIN_PASSWORD,
    })
    if resp.status_code == 200:
        body = resp.json()
        if body.get("data") and body["data"].get("token"):
            token = body["data"]["token"]
            session.headers.update({"Authorization": f"Bearer {token}"})


# ═══════════════════════════════════════════
# 通用断言辅助
# ═══════════════════════════════════════════

def assert_ok(resp, status_code=200):
    """断言 HTTP 200 且业务 code=200。"""
    assert resp.status_code == status_code, f"HTTP {resp.status_code}: {resp.text[:200]}"
    body = resp.json()
    assert body["code"] == 200, f"业务错误: {body}"
    return body


def assert_paginated(body):
    """断言分页结构包含 records 和 total。"""
    assert "records" in body["data"], "缺少 records 字段"
    assert "total" in body["data"], "缺少 total 字段"
    assert isinstance(body["data"]["records"], list), "records 应为数组"
    assert isinstance(body["data"]["total"], int), "total 应为整数"

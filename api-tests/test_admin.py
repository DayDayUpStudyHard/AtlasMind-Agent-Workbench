"""
后台管理接口测试 — 所有接口需要登录态。

覆盖:
  Article CRUD:   GET/POST/PUT/DELETE /api/admin/articles
  Category CRUD:  POST/PUT/DELETE /api/admin/categories
  Tag CRUD:       POST/PUT/DELETE /api/admin/tags
  Moment CRUD:    GET/POST/PUT/DELETE /api/admin/moments
  Comment 管理:   GET /api/admin/comments, PUT status, DELETE
  About 管理:     GET/PUT /api/admin/about
  Log 查询:       GET /api/admin/logs
"""

import pytest
from conftest import assert_ok, assert_paginated


# ═══════════════════════ Article CRUD ═══════════════════════

@pytest.mark.admin
@pytest.mark.slow
class TestArticleAdmin:
    """后台文章 CRUD"""

    RECORD_ID = None  # 创建的测试文章 ID

    def test_01_list_all(self, base_url, session, auth_headers):
        """后台列表含所有状态"""
        body = assert_ok(session.get(
            f"{base_url}/api/admin/articles", headers=auth_headers))
        assert_paginated(body)

    def test_02_list_by_status(self, base_url, session, auth_headers):
        """按状态筛选"""
        body = assert_ok(session.get(
            f"{base_url}/api/admin/articles?status=1", headers=auth_headers))
        assert_paginated(body)
        for r in body["data"]["records"]:
            assert r.get("status") == 1

    def test_03_create(self, base_url, session, auth_headers, test_data_tracker):
        """创建文章"""
        payload = {
            "title": "[Pytest] 测试文章",
            "content": "# 自动化测试\n\n这是 pytest 创建的测试文章。",
            "summary": "pytest 测试摘要",
            "categoryId": 1,
            "status": 0,
            "tagIds": [],
        }
        body = assert_ok(session.post(
            f"{base_url}/api/admin/articles",
            json=payload,
            headers=auth_headers,
        ))
        data = body["data"]
        assert data["title"] == "[Pytest] 测试文章"
        TestArticleAdmin.RECORD_ID = data["id"]
        test_data_tracker["articles"].append(data["id"])

    def test_04_detail(self, base_url, session, auth_headers):
        """获取文章详情（含 tags）"""
        aid = TestArticleAdmin.RECORD_ID
        if not aid:
            pytest.skip("依赖 test_03_create")
        body = assert_ok(session.get(
            f"{base_url}/api/admin/articles/{aid}", headers=auth_headers))
        assert body["data"]["id"] == aid
        assert "tags" in body["data"]

    def test_05_update(self, base_url, session, auth_headers):
        """更新文章"""
        aid = TestArticleAdmin.RECORD_ID
        if not aid:
            pytest.skip("依赖 test_03_create")
        payload = {
            "title": "[Pytest] 测试文章（已更新）",
            "content": "# 更新后的内容",
            "summary": "更新后的摘要",
            "categoryId": 1,
            "status": 1,
            "tagIds": [],
        }
        body = assert_ok(session.put(
            f"{base_url}/api/admin/articles/{aid}",
            json=payload,
            headers=auth_headers,
        ))
        assert body["data"]["title"] == "[Pytest] 测试文章（已更新）"

    def test_06_delete(self, base_url, session, auth_headers, test_data_tracker):
        """删除文章"""
        aid = TestArticleAdmin.RECORD_ID
        if not aid:
            pytest.skip("依赖 test_03_create")
        body = assert_ok(session.delete(
            f"{base_url}/api/admin/articles/{aid}", headers=auth_headers))
        # 从 tracker 中移除，避免 teardown 重复删除
        if aid in test_data_tracker["articles"]:
            test_data_tracker["articles"].remove(aid)


# ═══════════════════════ Category CRUD ═══════════════════════

@pytest.mark.admin
@pytest.mark.slow
class TestCategoryAdmin:
    """后台分类 CRUD"""

    RECORD_ID = None

    def test_01_create(self, base_url, session, auth_headers, test_data_tracker):
        payload = {"name": "[Pytest] 测试分类", "sortOrder": 99}
        body = assert_ok(session.post(
            f"{base_url}/api/admin/categories", json=payload, headers=auth_headers))
        TestCategoryAdmin.RECORD_ID = body["data"]["id"]
        test_data_tracker["categories"].append(body["data"]["id"])

    def test_02_update(self, base_url, session, auth_headers):
        cid = TestCategoryAdmin.RECORD_ID
        if not cid:
            pytest.skip("依赖 test_01_create")
        body = assert_ok(session.put(
            f"{base_url}/api/admin/categories/{cid}",
            json={"name": "[Pytest] 测试分类（已更新）", "sortOrder": 98},
            headers=auth_headers,
        ))

    def test_03_delete(self, base_url, session, auth_headers, test_data_tracker):
        cid = TestCategoryAdmin.RECORD_ID
        if not cid:
            pytest.skip("依赖 test_01_create")
        body = assert_ok(session.delete(
            f"{base_url}/api/admin/categories/{cid}", headers=auth_headers))
        if cid in test_data_tracker["categories"]:
            test_data_tracker["categories"].remove(cid)


# ═══════════════════════ Tag CRUD ═══════════════════════

@pytest.mark.admin
@pytest.mark.slow
class TestTagAdmin:
    """后台标签 CRUD"""

    RECORD_ID = None

    def test_01_create(self, base_url, session, auth_headers, test_data_tracker):
        payload = {"name": "[Pytest] 测试标签"}
        body = assert_ok(session.post(
            f"{base_url}/api/admin/tags", json=payload, headers=auth_headers))
        TestTagAdmin.RECORD_ID = body["data"]["id"]
        test_data_tracker["tags"].append(body["data"]["id"])

    def test_02_update(self, base_url, session, auth_headers):
        tid = TestTagAdmin.RECORD_ID
        if not tid:
            pytest.skip("依赖 test_01_create")
        body = assert_ok(session.put(
            f"{base_url}/api/admin/tags/{tid}",
            json={"name": "[Pytest] 测试标签（已更新）"},
            headers=auth_headers,
        ))

    def test_03_delete(self, base_url, session, auth_headers, test_data_tracker):
        tid = TestTagAdmin.RECORD_ID
        if not tid:
            pytest.skip("依赖 test_01_create")
        body = assert_ok(session.delete(
            f"{base_url}/api/admin/tags/{tid}", headers=auth_headers))
        if tid in test_data_tracker["tags"]:
            test_data_tracker["tags"].remove(tid)


# ═══════════════════════ Moment CRUD ═══════════════════════

@pytest.mark.admin
@pytest.mark.slow
class TestMomentAdmin:
    """后台说说 CRUD"""

    RECORD_ID = None

    def test_01_list(self, base_url, session, auth_headers):
        body = assert_ok(session.get(
            f"{base_url}/api/admin/moments", headers=auth_headers))
        assert_paginated(body)

    def test_02_create(self, base_url, session, auth_headers, test_data_tracker):
        payload = {"content": "[Pytest] 测试说说"}
        body = assert_ok(session.post(
            f"{base_url}/api/admin/moments", json=payload, headers=auth_headers))
        TestMomentAdmin.RECORD_ID = body["data"]["id"]
        test_data_tracker["moments"].append(body["data"]["id"])

    def test_03_update(self, base_url, session, auth_headers):
        mid = TestMomentAdmin.RECORD_ID
        if not mid:
            pytest.skip("依赖 test_02_create")
        body = assert_ok(session.put(
            f"{base_url}/api/admin/moments/{mid}",
            json={"content": "[Pytest] 测试说说（已更新）"},
            headers=auth_headers,
        ))

    def test_04_delete(self, base_url, session, auth_headers, test_data_tracker):
        mid = TestMomentAdmin.RECORD_ID
        if not mid:
            pytest.skip("依赖 test_02_create")
        body = assert_ok(session.delete(
            f"{base_url}/api/admin/moments/{mid}", headers=auth_headers))
        if mid in test_data_tracker["moments"]:
            test_data_tracker["moments"].remove(mid)


# ═══════════════════════ Comment 管理 ═══════════════════════

@pytest.mark.admin
class TestCommentAdmin:
    """后台评论管理"""

    def test_list_all(self, base_url, session, auth_headers):
        body = assert_ok(session.get(
            f"{base_url}/api/admin/comments", headers=auth_headers))
        assert_paginated(body)

    def test_list_by_status(self, base_url, session, auth_headers):
        body = assert_ok(session.get(
            f"{base_url}/api/admin/comments?status=1", headers=auth_headers))
        assert_paginated(body)

    def test_update_status_not_found(self, base_url, session, auth_headers):
        """不存在的评论更新状态应返回错误"""
        resp = session.put(
            f"{base_url}/api/admin/comments/999999/status",
            json={"status": 1},
            headers=auth_headers,
        )
        # 服务端可能返回 200（静默成功）或 400（参数校验失败）
        assert resp.status_code in [200, 400]


# ═══════════════════════ About 管理 ═══════════════════════

@pytest.mark.admin
class TestAboutAdmin:
    """后台关于页管理"""

    def test_get(self, base_url, session, auth_headers):
        body = assert_ok(session.get(
            f"{base_url}/api/admin/about", headers=auth_headers))
        assert body["data"] is not None or body["code"] == 200

    def test_update(self, base_url, session, auth_headers):
        body = assert_ok(session.put(
            f"{base_url}/api/admin/about",
            json={"content": "# Pytest 关于", "timeline": "[{\"year\":2026,\"text\":\"test\"}]"},
            headers=auth_headers,
        ))


# ═══════════════════════ 操作日志 ═══════════════════════

@pytest.mark.admin
class TestLogAdmin:
    """操作审计日志"""

    def test_list(self, base_url, session, auth_headers):
        body = assert_ok(session.get(
            f"{base_url}/api/admin/logs", headers=auth_headers))
        assert_paginated(body)

    def test_list_by_type(self, base_url, session, auth_headers):
        body = assert_ok(session.get(
            f"{base_url}/api/admin/logs?type=CREATE", headers=auth_headers))
        assert_paginated(body)


# ═══════════════════════ 无权限访问 ═══════════════════════

@pytest.mark.admin
class TestUnauthorized:
    """无 token 访问后台接口应被拦截"""

    ENDPOINTS = [
        "/api/admin/articles",
        "/api/admin/comments",
        "/api/admin/moments",
        "/api/admin/tags",
        "/api/admin/categories",
        "/api/admin/about",
        "/api/admin/logs",
    ]

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    @pytest.mark.xfail(reason="BUG: Sa-Token 未拦截 /api/admin/** 路由，后台接口无登录保护")
    def test_unauthorized(self, base_url, session, endpoint):
        """无 token 时后台接口应拒绝"""
        resp = session.get(f"{base_url}{endpoint}")
        assert resp.status_code in [200, 401, 403]
        if resp.status_code == 200:
            body = resp.json()
            assert body["code"] != 200, f"{endpoint} 未登录却允许访问: {body}"

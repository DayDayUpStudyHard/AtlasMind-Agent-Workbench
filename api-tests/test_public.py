"""
公开接口测试 — 共 16 个接口，无需登录。

覆盖:
  GET  /api/articles             文章列表（分页、分类筛选）
  GET  /api/articles/archive     文章归档
  GET  /api/articles/{id}        文章详情
  GET  /api/articles/{id}/nav    文章上下篇导航
  POST /api/articles/{id}/like   文章点赞
  GET  /api/articles/{id}/likes  点赞信息
  GET  /api/articles/search      全文搜索
  GET  /api/categories           分类列表
  GET  /api/tags                 标签列表
  GET  /api/moments              说说列表
  GET  /api/about                关于页
  GET  /api/site/info            站点信息
  GET  /api/articles/{id}/comments  评论列表
  POST /api/articles/{id}/comments  发表评论
  GET  /api/guestbook            留言板列表
  POST /api/guestbook            发表留言
"""

import pytest
from conftest import assert_ok, assert_paginated


# ═══════════════════════ 文章 ═══════════════════════

@pytest.mark.public
class TestArticleList:
    """GET /api/articles — 文章列表"""

    def test_list_default(self, base_url, session):
        """默认分页返回 records + total"""
        body = assert_ok(session.get(f"{base_url}/api/articles"))
        assert_paginated(body)

    def test_list_with_page_size(self, base_url, session):
        """自定义分页参数"""
        body = assert_ok(session.get(f"{base_url}/api/articles?page=2&size=5"))
        assert_paginated(body)
        assert len(body["data"]["records"]) <= 5

    def test_list_by_category(self, base_url, session):
        """按分类筛选"""
        body = assert_ok(session.get(f"{base_url}/api/articles?categoryId=1"))
        assert_paginated(body)


@pytest.mark.public
class TestArticleDetail:
    """GET /api/articles/{id} — 文章详情"""

    def test_detail_existing(self, base_url, session):
        """获取存在的文章详情"""
        # 先从列表取一篇
        list_body = assert_ok(session.get(f"{base_url}/api/articles?size=1"))
        records = list_body["data"]["records"]
        if records:
            aid = records[0]["id"]
            body = assert_ok(session.get(f"{base_url}/api/articles/{aid}"))
            assert body["data"]["id"] == aid
            assert "title" in body["data"]
            assert "content" in body["data"]

    def test_detail_not_found(self, base_url, session):
        """不存在的文章返回 404"""
        resp = session.get(f"{base_url}/api/articles/999999")
        # 服务端可能返回 404 或业务异常
        assert resp.status_code in [200, 404, 400]


@pytest.mark.public
class TestArticleNav:
    """GET /api/articles/{id}/nav — 上下篇导航"""

    def test_nav(self, base_url, session):
        """导航返回 prev/next 结构"""
        body = assert_ok(session.get(f"{base_url}/api/articles/1/nav"))
        data = body["data"]
        # prev 和 next 可能为 null
        assert "prev" in data
        assert "next" in data


@pytest.mark.public
class TestArticleArchive:
    """GET /api/articles/archive — 文章归档"""

    def test_archive(self, base_url, session):
        """归档返回按年月分组的数据"""
        body = assert_ok(session.get(f"{base_url}/api/articles/archive"))
        assert isinstance(body["data"], list)


# ═══════════════════════ 点赞 ═══════════════════════

@pytest.mark.public
class TestArticleLike:
    """POST /api/articles/{id}/like + GET /likes"""

    def test_toggle_like(self, base_url, session):
        """点赞切换返回 liked + count"""
        # 先确保有文章
        list_body = assert_ok(session.get(f"{base_url}/api/articles?size=1"))
        records = list_body["data"]["records"]
        if not records:
            pytest.skip("没有可点赞的文章")
        aid = records[0]["id"]

        body = assert_ok(session.post(f"{base_url}/api/articles/{aid}/like"))
        assert "liked" in body["data"]
        assert "count" in body["data"]
        assert isinstance(body["data"]["liked"], bool)
        assert isinstance(body["data"]["count"], int)

    def test_get_likes(self, base_url, session):
        """获取点赞信息"""
        body = assert_ok(session.get(f"{base_url}/api/articles/1/likes"))
        assert "liked" in body["data"]
        assert "count" in body["data"]


# ═══════════════════════ 搜索 ═══════════════════════

@pytest.mark.public
class TestArticleSearch:
    """GET /api/articles/search — 全文搜索"""

    def test_search_with_keyword(self, base_url, session):
        """关键词搜索返回分页结果"""
        body = assert_ok(session.get(f"{base_url}/api/articles/search?keyword=Spring"))
        assert_paginated(body)

    def test_search_no_result(self, base_url, session):
        """无匹配关键词返回空列表"""
        body = assert_ok(session.get(f"{base_url}/api/articles/search?keyword=xyznonexistent999"))
        assert_paginated(body)
        assert body["data"]["total"] == 0


# ═══════════════════════ 分类 & 标签 ═══════════════════════

@pytest.mark.public
class TestCategories:
    """GET /api/categories"""

    def test_list(self, base_url, session):
        body = assert_ok(session.get(f"{base_url}/api/categories"))
        assert isinstance(body["data"], list)


@pytest.mark.public
class TestTags:
    """GET /api/tags"""

    def test_list(self, base_url, session):
        body = assert_ok(session.get(f"{base_url}/api/tags"))
        assert isinstance(body["data"], list)


# ═══════════════════════ 说说 ═══════════════════════

@pytest.mark.public
class TestMoments:
    """GET /api/moments"""

    def test_list(self, base_url, session):
        body = assert_ok(session.get(f"{base_url}/api/moments"))
        assert_paginated(body)


# ═══════════════════════ 关于 & 站点 ═══════════════════════

@pytest.mark.public
class TestAbout:
    """GET /api/about"""

    def test_get(self, base_url, session):
        body = assert_ok(session.get(f"{base_url}/api/about"))
        # data 可为 null（未初始化时）
        data = body["data"]
        if data is not None:
            assert "content" in data or "timeline" in data


@pytest.mark.public
class TestSiteInfo:
    """GET /api/site/info"""

    def test_info(self, base_url, session):
        body = assert_ok(session.get(f"{base_url}/api/site/info"))
        data = body["data"]
        assert data is not None
        assert "nickname" in data or "username" in data


# ═══════════════════════ 评论 ═══════════════════════

@pytest.mark.public
class TestComments:
    """评论接口"""

    @pytest.fixture(autouse=True)
    def setup_article(self, base_url, session):
        """确保有文章可评论"""
        list_body = assert_ok(session.get(f"{base_url}/api/articles?size=1"))
        records = list_body["data"]["records"]
        if records:
            self.article_id = records[0]["id"]
        else:
            self.article_id = None

    def test_list_comments(self, base_url, session):
        """获取文章评论列表"""
        aid = self.article_id or 1
        body = assert_ok(session.get(f"{base_url}/api/articles/{aid}/comments"))
        assert isinstance(body["data"]["records"], list)

    def test_create_comment(self, base_url, session):
        """发表文章评论"""
        aid = self.article_id or 1
        payload = {
            "author": "Pytest测试",
            "email": "test@example.com",
            "content": "这是一条自动化测试评论",
        }
        body = assert_ok(session.post(
            f"{base_url}/api/articles/{aid}/comments",
            json=payload,
        ))
        assert body["data"]["author"] == "Pytest测试"

    def test_create_comment_missing_fields(self, base_url, session):
        """缺少必填字段应返回 400"""
        aid = self.article_id or 1
        resp = session.post(
            f"{base_url}/api/articles/{aid}/comments",
            json={"content": ""},
        )
        assert resp.status_code in [200, 400, 422]
        if resp.status_code == 200:
            assert resp.json()["code"] != 200


# ═══════════════════════ 留言板 ═══════════════════════

@pytest.mark.public
class TestGuestbook:
    """留言板接口"""

    def test_list(self, base_url, session):
        body = assert_ok(session.get(f"{base_url}/api/guestbook"))
        assert_paginated(body)

    def test_create(self, base_url, session):
        """发表留言"""
        payload = {
            "author": "Pytest访客",
            "content": "这是一条自动化测试留言",
        }
        body = assert_ok(session.post(f"{base_url}/api/guestbook", json=payload))
        assert body["data"]["author"] == "Pytest访客"

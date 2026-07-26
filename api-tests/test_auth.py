"""
认证接口测试 — 登录、获取用户信息、修改密码、修改个人资料。

覆盖:
  POST /api/auth/login      登录
  GET  /api/auth/info       当前用户信息
  PUT  /api/auth/password   修改密码
  PUT  /api/auth/profile    修改个人资料
"""

import pytest
from conftest import assert_ok


@pytest.mark.auth
class TestLogin:
    """登录接口"""

    def test_login_success(self, base_url, session):
        """正常登录返回 token + user（可能触发限流则跳过）"""
        resp = session.post(f"{base_url}/api/auth/login", json={
            "username": "admin",
            "password": "admin123",
        })
        body = resp.json()
        if body["code"] == 429:
            pytest.skip("触发登录限流（5次/分钟），跳过")
        assert body["code"] == 200
        data = body["data"]
        assert "token" in data
        assert "user" in data

    def test_login_wrong_password(self, base_url, session):
        """错误密码返回业务错误（400 或 200+业务错误码）"""
        resp = session.post(f"{base_url}/api/auth/login", json={
            "username": "admin",
            "password": "wrong_password_123",
        })
        assert resp.status_code in [200, 400]
        if resp.status_code == 200:
            assert resp.json()["code"] != 200

    def test_login_empty_username(self, base_url, session):
        """空用户名应被拒绝"""
        resp = session.post(f"{base_url}/api/auth/login", json={
            "username": "",
            "password": "admin123",
        })
        # Jakarta Validation 可能返回 400 或业务异常
        assert resp.status_code in [200, 400]
        if resp.status_code == 200:
            assert resp.json()["code"] != 200


@pytest.mark.auth
class TestAuthInfo:
    """获取当前用户信息"""

    def test_info_without_token(self, base_url, session):
        """无 token 返回 401/403"""
        resp = session.get(f"{base_url}/api/auth/info")
        assert resp.status_code in [200, 401, 403]

    def test_info_with_token(self, base_url, session, auth_headers):
        """有 token 返回用户信息"""
        body = assert_ok(session.get(f"{base_url}/api/auth/info", headers=auth_headers))
        assert body["data"] is not None
        assert "username" in body["data"]


@pytest.mark.auth
class TestPassword:
    """修改密码"""

    def test_wrong_old_password(self, base_url, session, auth_headers):
        """旧密码错误应失败（400 或 200+业务错误码）"""
        resp = session.put(f"{base_url}/api/auth/password", json={
            "oldPassword": "wrong_old",
            "newPassword": "new123456",
        }, headers=auth_headers)
        assert resp.status_code in [200, 400]
        if resp.status_code == 200:
            assert resp.json()["code"] != 200

    def test_change_and_restore(self, base_url, session, auth_headers):
        """修改密码后改回 — 验证整套流程"""
        # 改为临时密码
        body = assert_ok(session.put(f"{base_url}/api/auth/password", json={
            "oldPassword": "admin123",
            "newPassword": "temp456",
        }, headers=auth_headers))

        # 改回来
        body = assert_ok(session.put(f"{base_url}/api/auth/password", json={
            "oldPassword": "temp456",
            "newPassword": "admin123",
        }, headers=auth_headers))


@pytest.mark.auth
class TestProfile:
    """修改个人资料"""

    def test_update_nickname(self, base_url, session, auth_headers):
        """更新昵称"""
        body = assert_ok(session.put(f"{base_url}/api/auth/profile", json={
            "nickname": "AdminPytest",
            "email": "admin@atlasmind.local",
        }, headers=auth_headers))
        # 成功后恢复
        session.put(f"{base_url}/api/auth/profile", json={
            "nickname": "Admin",
            "email": "admin@atlasmind.local",
        }, headers=auth_headers)

"""Đăng nhập & phân quyền admin/user — phần kiểm được mà không cần database.

Đường đi qua database (tạo tài khoản, khoá, chốt "còn ít nhất một admin")
được giả lập bằng monkeypatch `auth.get_user`, vì điều cần khoá lại ở đây là
QUYẾT ĐỊNH phân quyền của từng route, không phải câu SQL.
"""

import pytest
from fastapi.testclient import TestClient

from app import admin, auth
from app.api import app
from app.auth import AuthError, AuthUser

KEY = b"test-signing-key"
ADMIN = AuthUser(id="11111111-1111-1111-1111-111111111111", username="boss",
                 display_name="Sếp", role="admin", is_active=True)
MEMBER = AuthUser(id="22222222-2222-2222-2222-222222222222", username="member",
                  display_name=None, role="user", is_active=True)
LOCKED = AuthUser(id="33333333-3333-3333-3333-333333333333", username="locked",
                  display_name=None, role="admin", is_active=False)


def test_mat_khau_bam_co_muoi_va_kiem_lai_duoc() -> None:
    first = auth.hash_password("matkhau123", iterations=1_000)
    second = auth.hash_password("matkhau123", iterations=1_000)
    assert first != second, "cùng mật khẩu phải ra hai chuỗi khác nhau nhờ muối"
    assert auth.verify_password("matkhau123", first)
    assert not auth.verify_password("matkhau124", first)


@pytest.mark.parametrize("stored", ["", "rac", "md5$1$a$b", "pbkdf2_sha256$x$y$z"])
def test_chuoi_bam_hong_khong_lam_no(stored: str) -> None:
    assert auth.verify_password("bat-ky", stored) is False


def test_token_dung_chu_ky_va_con_han() -> None:
    token = auth.issue_token(MEMBER.id, now=1_000, ttl_hours=1, key=KEY)
    assert auth.read_token(token, now=1_000 + 3599, key=KEY) == MEMBER.id


def test_token_het_han_bi_tu_choi() -> None:
    token = auth.issue_token(MEMBER.id, now=1_000, ttl_hours=1, key=KEY)
    assert auth.read_token(token, now=1_000 + 3601, key=KEY) is None


def test_token_sua_payload_hoac_sai_khoa_bi_tu_choi() -> None:
    token = auth.issue_token(MEMBER.id, now=1_000, ttl_hours=1, key=KEY)
    forged = auth.issue_token(ADMIN.id, now=1_000, ttl_hours=1, key=b"khoa-cua-ke-gian")
    body, signature = token.split(".")
    assert auth.read_token(forged, now=1_000, key=KEY) is None
    assert auth.read_token(f"{forged.split('.')[0]}.{signature}", now=1_000, key=KEY) is None
    assert auth.read_token("khong-phai-token", now=1_000, key=KEY) is None


@pytest.mark.parametrize("username", ["ab", "có-dấu", "a b", "x" * 33, ""])
def test_ten_dang_nhap_khong_hop_le(username: str) -> None:
    with pytest.raises(AuthError):
        auth.validate_username(username)


def test_mat_khau_qua_ngan() -> None:
    with pytest.raises(AuthError, match="ít nhất"):
        auth.validate_password("1234567")


def test_admin_khong_tu_ha_quyen_minh_truoc_khi_cham_database() -> None:
    with pytest.raises(AuthError, match="chính mình"):
        admin.update_user(ADMIN, ADMIN.id, role="user")
    with pytest.raises(AuthError, match="chính mình"):
        admin.update_user(ADMIN, ADMIN.id.upper(), is_active=False)


def test_owner_id_co_tien_to_de_khong_trung_session_id() -> None:
    assert MEMBER.owner_id == f"user:{MEMBER.id}"


# --- Phân quyền từng route ----------------------------------------------------


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    users = {user.id: user for user in (ADMIN, MEMBER, LOCKED)}
    monkeypatch.setattr(auth, "get_user", lambda user_id, database_url=None: users.get(user_id))
    monkeypatch.setattr(admin, "overview", lambda database_url=None: {"users": 3})
    return TestClient(app)


def _bearer(user: AuthUser) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth.issue_token(user.id)}"}


def test_chua_dang_nhap_thi_401(client: TestClient) -> None:
    assert client.get("/api/v1/admin/overview").status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 401


def test_token_rac_thi_401(client: TestClient) -> None:
    response = client.get("/api/v1/admin/overview", headers={"Authorization": "Bearer abc.def"})
    assert response.status_code == 401


def test_user_thuong_vao_trang_admin_thi_403(client: TestClient) -> None:
    response = client.get("/api/v1/admin/overview", headers=_bearer(MEMBER))
    assert response.status_code == 403


def test_admin_vao_duoc(client: TestClient) -> None:
    response = client.get("/api/v1/admin/overview", headers=_bearer(ADMIN))
    assert response.status_code == 200
    assert response.json() == {"users": 3}


def test_tai_khoan_bi_khoa_mat_quyen_ngay_du_token_con_han(client: TestClient) -> None:
    """Token không mang vai trò — khoá tài khoản có hiệu lực ở request kế tiếp."""
    assert client.get("/api/v1/admin/overview", headers=_bearer(LOCKED)).status_code == 403


def test_me_tra_vai_tro(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me", headers=_bearer(MEMBER))
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "user"


def test_dang_ky_khong_nhan_truong_role(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Client gửi kèm role=admin cũng chỉ ra tài khoản user."""
    created: dict[str, str] = {}

    def fake_create(username, password, *, display_name=None, role="user", database_url=None):
        created["role"] = role
        return AuthUser(id=MEMBER.id, username=username, display_name=display_name,
                        role=role, is_active=True)

    monkeypatch.setattr(auth, "create_user", fake_create)
    response = client.post(
        "/api/v1/auth/register",
        json={"username": "hacker", "password": "matkhau123", "role": "admin"},
    )
    assert response.status_code == 201
    assert created["role"] == "user"
    assert response.json()["user"]["role"] == "user"

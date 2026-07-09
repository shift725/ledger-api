import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APIClient


@pytest.fixture(autouse=True, scope='session')
def _fast_password_hashing():
    """測試環境改用最快的雜湊器。

    PBKDF2 的 120 萬輪是給正式環境擋離線暴力破解用的，本機一次要 0.84 秒；每個測試
    都建使用者，光雜湊就吃掉整輪八成時間。測試只驗「對的密碼能過、錯的不能過」，
    這個性質任何雜湊器都成立。本檔是 dev-only（runtime image 無 pytest），
    正式環境的 PASSWORD_HASHERS 不受影響。
    """
    settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """每測試前清 cache：DRF throttle 計數存 cache，跨測試累積會偽陽性觸發 429。"""
    cache.clear()


@pytest.fixture
def user(db):
    """一個已建立的一般使用者（email 登入、UUIDv7 主鍵）。"""
    return get_user_model().objects.create_user(
        username='testuser',  # CustomUser 仍需 username（email 只是 USERNAME_FIELD）
        email='user@example.com',
        password='pw-12345',
    )


@pytest.fixture
def auth_client(user):
    """已認證的 DRF APIClient（force_authenticate，繞過 token 細節）。"""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def other_user(db):
    """第二個使用者，用來驗證資料隔離（A 拿不到 B 的資料）。"""
    return get_user_model().objects.create_user(
        username='otheruser',
        email='other@example.com',
        password='pw-12345',
    )

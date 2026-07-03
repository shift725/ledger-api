import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APIClient


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

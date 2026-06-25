import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


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

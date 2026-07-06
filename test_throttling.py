"""全域限流（throttling）行為：匿名依 IP、登入依 user pk，超率回 429。

放根目錄而非 ledger/：限流是跨領域的全域設定，非記帳領域。用 APITestCase（unittest 風格）
—— setUp/tearDown 清 cache＋壓 rate 直接，且不 import pytest，容器 Django runner 亦可
`manage.py test test_throttling` 單獨跑。
"""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

User = get_user_model()


class ThrottlingTests(APITestCase):
    # 壓 rate 直接改 class 屬性，不用 override_settings(REST_FRAMEWORK=…)：throttle 類在首次載入時
    # 就把 THROTTLE_RATES 綁成當下的 rates dict，override 換掉的是 api_settings 另一物件、綁定不跟著
    # 變 → 只有 throttle 模組剛好在 override 內首次載入才生效（順序相依、跑全套會漏）。
    def setUp(self):
        cache.clear()  # LocMemCache 跨測試殘留計數會偽陽性觸發 429
        self._orig_rates = SimpleRateThrottle.THROTTLE_RATES
        # Anon/User 都繼承 SimpleRateThrottle 的 THROTTLE_RATES；壓到 3/min 免真打 61 發。
        SimpleRateThrottle.THROTTLE_RATES = {'anon': '3/min', 'user': '3/min'}

    def tearDown(self):
        SimpleRateThrottle.THROTTLE_RATES = self._orig_rates
        cache.clear()

    def test_anonymous_requests_throttled_after_limit(self):
        User.objects.create_user(username='u', email='u@example.com', password='pw-12345')
        url = reverse('auth:login')
        bad = {'email': 'u@example.com', 'password': 'wrong'}
        for _ in range(3):  # 未超率：帳密錯照樣被 throttle 計數
            resp = self.client.post(url, bad, format='json')
            self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        resp = self.client.post(url, bad, format='json')
        self.assertEqual(resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertTrue(resp.has_header('Retry-After'))

    def test_authenticated_requests_throttled_after_limit(self):
        user = User.objects.create_user(username='u', email='u@example.com', password='pw-12345')
        self.client.force_authenticate(user=user)
        url = '/api/ledger/accounts/'
        for _ in range(3):
            self.assertEqual(self.client.get(url).status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get(url).status_code, status.HTTP_429_TOO_MANY_REQUESTS)


class ScopedThrottlingTests(APITestCase):
    """scoped throttle：只有 balance-history 掛 reports-heavy 桶，便宜端點不連坐。

    自帶 rates patch——user 保持 300/min（沿用上面的 3/min 會讓 user 桶搶先觸發、測錯對象）；
    reports-heavy 壓到 3/min 免真打 21 發。
    """

    BALANCE_HISTORY = '/api/ledger/reports/balance-history/'
    BALANCE = '/api/ledger/reports/balance/'

    def setUp(self):
        cache.clear()
        self._orig_rates = SimpleRateThrottle.THROTTLE_RATES
        SimpleRateThrottle.THROTTLE_RATES = {
            'anon': '60/min',
            'user': '300/min',  # 保持高位，隔離出 reports-heavy 桶（否則 user 桶先於 3 發爆）
            'reports-heavy': '3/min',
        }
        self.user = User.objects.create_user(
            username='u', email='u@example.com', password='pw-12345'
        )
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        SimpleRateThrottle.THROTTLE_RATES = self._orig_rates
        cache.clear()

    def test_balance_history_throttled_but_cheap_endpoint_not(self):
        for _ in range(3):
            self.assertEqual(self.client.get(self.BALANCE_HISTORY).status_code, status.HTTP_200_OK)
        resp = self.client.get(self.BALANCE_HISTORY)
        self.assertEqual(resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertTrue(resp.has_header('Retry-After'))
        # 同期打便宜的 balance/：不在 reports-heavy 桶 → 仍 200（桶隔離實證）
        self.assertEqual(self.client.get(self.BALANCE).status_code, status.HTTP_200_OK)

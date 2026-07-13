"""DB 層約束的最小 smoke：證明約束真的在資料庫擋下髒資料。

每個違規寫入都包在 `transaction.atomic()` 裡——IntegrityError 會弄髒外層測試交易，
用 savepoint 框住才不會讓同一測試的後續 ORM 操作炸掉。複用 conftest 的 `user` fixture。
"""

import io
import logging
import threading
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

try:
    import pytest
except ImportError as exc:
    # 容器 runtime image 不含 pytest（dev-only）。本檔整份是 pytest 原生，
    # @pytest.mark.* 裝飾器在 import 當下就要 pytest，無法只搬 import。
    # 缺席時丟 SkipTest：unittest 探索會把整個模組標為 skipped 而非中斷，
    # 讓容器無範圍 `manage.py test` 跑完其餘測試並 exit 0。
    import unittest

    raise unittest.SkipTest('ledger 測試為 pytest 專屬，容器 Django runner 略過') from exc
import yaml
from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIClient

from ledger import reports, services
from ledger.models import (
    Account,
    Category,
    RecurringRule,
    SavingsGoal,
    Tag,
    Transaction,
    next_due,
)
from ledger.serializers import CategorySerializer, TransactionSerializer
from ledger.tasks import post_due_recurring_rules


@pytest.mark.django_db
def test_account_name_unique_per_user(user):
    Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
    with pytest.raises(IntegrityError), transaction.atomic():
        Account.objects.create(user=user, name='現金', type=Account.Type.BANK)


@pytest.mark.django_db
def test_account_single_default_per_user(user):
    Account.objects.create(user=user, name='現金', type=Account.Type.CASH, is_default=True)
    # 名字刻意取不同，才能隔離出「部分唯一索引」而非撞到 (user, name)
    with pytest.raises(IntegrityError), transaction.atomic():
        Account.objects.create(user=user, name='銀行', type=Account.Type.BANK, is_default=True)


@pytest.mark.django_db
def test_savings_goal_period_unique(user):
    SavingsGoal.objects.create(
        user=user,
        period_type=SavingsGoal.PeriodType.MONTHLY,
        year=2026,
        month=6,
        amount=Decimal('10000'),
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        SavingsGoal.objects.create(
            user=user,
            period_type=SavingsGoal.PeriodType.MONTHLY,
            year=2026,
            month=6,
            amount=Decimal('20000'),
        )


@pytest.mark.django_db
def test_savings_goal_yearly_nulls_not_distinct(user):
    # 同年兩筆年度目標（month=NULL）→ nulls_distinct=False 應擋下
    SavingsGoal.objects.create(
        user=user,
        period_type=SavingsGoal.PeriodType.YEARLY,
        year=2026,
        month=None,
        amount=Decimal('100000'),
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        SavingsGoal.objects.create(
            user=user,
            period_type=SavingsGoal.PeriodType.YEARLY,
            year=2026,
            month=None,
            amount=Decimal('200000'),
        )


@pytest.mark.django_db
def test_savings_goal_yearly_rejects_month(user):
    # 年度卻帶 month → CheckConstraint 應擋下
    with pytest.raises(IntegrityError), transaction.atomic():
        SavingsGoal.objects.create(
            user=user,
            period_type=SavingsGoal.PeriodType.YEARLY,
            year=2026,
            month=5,
            amount=Decimal('100000'),
        )


@pytest.mark.django_db
def test_savings_goal_monthly_month_out_of_range(user):
    # 月度 month=13 → CheckConstraint 應擋下
    with pytest.raises(IntegrityError), transaction.atomic():
        SavingsGoal.objects.create(
            user=user,
            period_type=SavingsGoal.PeriodType.MONTHLY,
            year=2026,
            month=13,
            amount=Decimal('10000'),
        )


@pytest.mark.django_db
def test_str_representations(user):
    account = Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
    category = Category.objects.create(user=user, name='飲食')
    tag = Tag.objects.create(user=user, name='日本旅遊')
    txn = Transaction.objects.create(
        user=user,
        account=account,
        amount=Decimal('100.00'),
        type=Transaction.Type.EXPENSE,
        name='午餐',
    )
    goal = SavingsGoal.objects.create(
        user=user,
        period_type=SavingsGoal.PeriodType.MONTHLY,
        year=2026,
        month=6,
        amount=Decimal('10000'),
    )

    assert str(account) == '現金'
    assert str(category) == '飲食'
    assert str(tag) == '日本旅遊'
    assert '午餐' in str(txn)
    assert '2026' in str(goal)


# --- 定期定額：日期算術（純函式，不碰 DB）與 DB 約束 ---


@pytest.mark.parametrize(
    'day_of_month,on_or_after,expected',
    [
        # 今天就是到期日 → 回今天（規則建立當天到期，由隔日任務 catch-up 補建）
        (9, date(2026, 7, 9), date(2026, 7, 9)),
        # 本月的日子已過 → 跳下個月
        (5, date(2026, 7, 9), date(2026, 8, 5)),
        # 短月 clamp：31 號在 2 月落在月底；閏年是 29
        (31, date(2026, 2, 1), date(2026, 2, 28)),
        (31, date(2024, 2, 1), date(2024, 2, 29)),
        # clamp 不造成漂移：2 月落在 28 號，3 月仍回到 31 號
        (31, date(2026, 3, 1), date(2026, 3, 31)),
        # 跨年
        (1, date(2026, 12, 2), date(2027, 1, 1)),
    ],
)
def test_next_due(day_of_month, on_or_after, expected):
    assert next_due(day_of_month, on_or_after) == expected


@pytest.mark.django_db
def test_recurring_rule_str(user):
    account = Account.objects.create(user=user, name='銀行', type=Account.Type.BANK)
    rule = RecurringRule.objects.create(
        user=user,
        account=account,
        amount=Decimal('18000.00'),
        type=Transaction.Type.EXPENSE,
        name='房租',
        day_of_month=5,
        next_run_date=date(2026, 8, 5),
    )
    assert '房租' in str(rule)


@pytest.mark.django_db
@pytest.mark.parametrize('day_of_month', [0, 32])
def test_recurring_rule_day_of_month_constraint(user, day_of_month):
    # 繞過 serializer 直接寫 DB → CheckConstraint 是最後防線
    account = Account.objects.create(user=user, name='銀行', type=Account.Type.BANK)
    with pytest.raises(IntegrityError), transaction.atomic():
        RecurringRule.objects.create(
            user=user,
            account=account,
            amount=Decimal('100.00'),
            type=Transaction.Type.EXPENSE,
            day_of_month=day_of_month,
            next_run_date=date(2026, 8, 1),
        )


@pytest.mark.django_db
def test_transaction_unique_per_rule_occurrence(user):
    # 冪等的真正機制：同一規則的同一到期日只能有一筆交易，資料庫層擋下重複記帳
    account = Account.objects.create(user=user, name='銀行', type=Account.Type.BANK)
    rule = RecurringRule.objects.create(
        user=user,
        account=account,
        amount=Decimal('18000.00'),
        type=Transaction.Type.EXPENSE,
        day_of_month=5,
        next_run_date=date(2026, 8, 5),
    )
    due = datetime(2026, 8, 5, tzinfo=UTC)
    Transaction.objects.create(
        user=user,
        account=account,
        amount=Decimal('18000.00'),
        type=Transaction.Type.EXPENSE,
        occurred_at=due,
        source_rule=rule,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Transaction.objects.create(
            user=user,
            account=account,
            amount=Decimal('18000.00'),
            type=Transaction.Type.EXPENSE,
            occurred_at=due,
            source_rule=rule,
        )


@pytest.mark.django_db
def test_manual_transactions_may_share_occurred_at(user):
    # source_rule=NULL：PostgreSQL 預設 NULL 互不相等，故上面那條唯一約束不誤傷手動交易
    account = Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
    due = datetime(2026, 8, 5, tzinfo=UTC)
    for _ in range(2):
        Transaction.objects.create(
            user=user,
            account=account,
            amount=Decimal('50.00'),
            type=Transaction.Type.EXPENSE,
            occurred_at=due,
        )
    assert Transaction.objects.filter(source_rule__isnull=True).count() == 2


# --- CRUD API：Category / Tag 兩個同形資源參數化，驗 OwnedModelViewSet 的隔離契約 ---

SIMPLE_RESOURCES = [
    pytest.param('/api/ledger/categories/', Category, id='category'),
    pytest.param('/api/ledger/tags/', Tag, id='tag'),
]


@pytest.mark.django_db
@pytest.mark.parametrize('url,model', SIMPLE_RESOURCES)
class TestOwnedResourceCrud:
    """五資源共用的隔離契約，先用最簡單的 Category / Tag 打通 CRUD 管線。"""

    def test_requires_authentication(self, url, model):
        # 未帶 token → IsAuthenticated 擋下 → 401
        assert APIClient().get(url).status_code == 401

    def test_create_forces_owner(self, url, model, auth_client, user, other_user):
        # client 惡意夾帶 user=別人；perform_create 應無視、擁有者仍是登入者
        resp = auth_client.post(url, {'name': '測試', 'user': str(other_user.id)})
        assert resp.status_code == 201
        assert model.objects.get(id=resp.data['id']).user == user

    def test_list_returns_only_own(self, url, model, auth_client, user, other_user):
        model.objects.create(user=user, name='我的')
        model.objects.create(user=other_user, name='別人的')
        resp = auth_client.get(url)
        assert resp.status_code == 200
        assert [row['name'] for row in resp.data['results']] == ['我的']

    def test_cannot_reach_others_object(self, url, model, auth_client, other_user):
        # 別人的物件不在我的 queryset 裡 → 讀/改/刪皆 404（連存在與否都不透露）
        theirs = model.objects.create(user=other_user, name='別人的')
        detail = f'{url}{theirs.id}/'
        assert auth_client.get(detail).status_code == 404
        assert auth_client.patch(detail, {'name': '竄改'}).status_code == 404
        assert auth_client.delete(detail).status_code == 404

    def test_timestamps_not_exposed(self, url, model, auth_client, user):
        obj = model.objects.create(user=user, name='我的')
        resp = auth_client.get(f'{url}{obj.id}/')
        assert 'created_at' not in resp.data
        assert 'updated_at' not in resp.data

    def test_duplicate_name_returns_400_not_500(self, url, model, auth_client, user):
        # (user, name) 唯一約束不含在 serializer fields（user 由 view 設）→ DRF 不自動驗，
        # 沒有 validate 時會落到 DB 炸 IntegrityError→500。序列化器補檢查回乾淨 400。
        model.objects.create(user=user, name='重複')
        resp = auth_client.post(url, {'name': '重複'})
        assert resp.status_code == 400
        assert 'name' in resp.data

    def test_rename_to_existing_name_returns_400(self, url, model, auth_client, user):
        model.objects.create(user=user, name='甲')
        obj = model.objects.create(user=user, name='乙')
        resp = auth_client.patch(f'{url}{obj.id}/', {'name': '甲'})
        assert resp.status_code == 400

    def test_rename_to_own_current_name_ok(self, url, model, auth_client, user):
        # 排除自己：改成自己現有的名字（等同沒改）不該被誤判成重複
        obj = model.objects.create(user=user, name='丙')
        resp = auth_client.patch(f'{url}{obj.id}/', {'name': '丙'})
        assert resp.status_code == 200

    def test_duplicate_name_allowed_across_users(self, url, model, auth_client, user, other_user):
        # 唯一性是 per-user：別人叫「共用名」不該擋我也用「共用名」
        model.objects.create(user=other_user, name='共用名')
        resp = auth_client.post(url, {'name': '共用名'})
        assert resp.status_code == 201


@pytest.mark.django_db
def test_unique_name_mixin_without_request_skips_check():
    # 無 request context（context-less 實例化）→ 重名 guard 跳過、不取 request.user 而炸。
    # 這道 guard 讓序列化器在沒有 request 的場合仍能安全實例化與驗證。
    serializer = CategorySerializer(data={'name': '任意名'})
    assert serializer.is_valid(), serializer.errors


# --- 分頁：掛在 OwnedModelViewSet 基底 → 五資源同一條路徑，用最便宜的 Category 驗證 ---


@pytest.mark.django_db
class TestListPagination:
    URL = '/api/ledger/categories/'

    def test_envelope_and_page_split(self, auth_client, user):
        for i in range(25):
            Category.objects.create(user=user, name=f'分類{i}')
        page1 = auth_client.get(self.URL)
        assert page1.status_code == 200
        assert page1.data['count'] == 25
        assert len(page1.data['results']) == 20
        assert page1.data['next'] is not None
        assert page1.data['previous'] is None
        page2 = auth_client.get(self.URL, {'page': 2})
        assert len(page2.data['results']) == 5
        assert page2.data['next'] is None


# --- Account：is_default 切換、刪除 409、balance 唯讀，外加隔離 ---


@pytest.mark.django_db
class TestAccountViewSet:
    URL = '/api/ledger/accounts/'

    def test_requires_authentication(self):
        assert APIClient().get(self.URL).status_code == 401

    def test_create_forces_owner_and_balance_readonly(self, auth_client, user, other_user):
        resp = auth_client.post(
            self.URL,
            {
                'name': '現金',
                'type': 'cash',
                'balance': '9999.00',  # 唯讀，應被忽略（餘額由交易維護，非 client 設定）
                'user': str(other_user.id),  # 應被忽略
            },
        )
        assert resp.status_code == 201
        acc = Account.objects.get(id=resp.data['id'])
        assert acc.user == user
        assert acc.balance == Decimal('0')

    def test_cannot_reach_others_account(self, auth_client, other_user):
        theirs = Account.objects.create(user=other_user, name='別人的', type=Account.Type.CASH)
        detail = f'{self.URL}{theirs.id}/'
        assert auth_client.get(detail).status_code == 404
        assert auth_client.patch(detail, {'name': '竄改'}).status_code == 404
        assert auth_client.delete(detail).status_code == 404  # destroy 覆寫後仍走 get_queryset

    def test_second_default_demotes_first_on_create(self, auth_client, user):
        first = Account.objects.create(
            user=user, name='現金', type=Account.Type.CASH, is_default=True
        )
        resp = auth_client.post(self.URL, {'name': '銀行', 'type': 'bank', 'is_default': True})
        assert resp.status_code == 201  # 不撞部分唯一索引、不 500
        first.refresh_from_db()
        assert first.is_default is False
        assert Account.objects.get(id=resp.data['id']).is_default is True

    def test_set_default_on_update_demotes_first(self, auth_client, user):
        first = Account.objects.create(
            user=user, name='現金', type=Account.Type.CASH, is_default=True
        )
        second = Account.objects.create(user=user, name='銀行', type=Account.Type.BANK)
        resp = auth_client.patch(f'{self.URL}{second.id}/', {'is_default': True})
        assert resp.status_code == 200
        first.refresh_from_db()
        second.refresh_from_db()
        assert first.is_default is False
        assert second.is_default is True

    def test_delete_account_with_transactions_returns_409(self, auth_client, user):
        acc = Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
        Transaction.objects.create(
            user=user, account=acc, amount=Decimal('100'), type=Transaction.Type.EXPENSE
        )
        resp = auth_client.delete(f'{self.URL}{acc.id}/')
        assert resp.status_code == 409  # PROTECT → ProtectedError → 409（非 500）
        assert Account.objects.filter(id=acc.id).exists()

    def test_delete_empty_account_ok(self, auth_client, user):
        acc = Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
        resp = auth_client.delete(f'{self.URL}{acc.id}/')
        assert resp.status_code == 204
        assert not Account.objects.filter(id=acc.id).exists()

    def test_duplicate_name_returns_400_not_500(self, auth_client, user):
        Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
        resp = auth_client.post(self.URL, {'name': '現金', 'type': 'bank'})
        assert resp.status_code == 400  # 撞 (user,name) 唯一約束 → 乾淨 400，非 DB 500
        assert 'name' in resp.data

    def test_rename_to_existing_name_returns_400(self, auth_client, user):
        Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
        acc = Account.objects.create(user=user, name='銀行', type=Account.Type.BANK)
        resp = auth_client.patch(f'{self.URL}{acc.id}/', {'name': '現金'})
        assert resp.status_code == 400

    def test_rename_to_own_current_name_ok(self, auth_client, user):
        acc = Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
        resp = auth_client.patch(f'{self.URL}{acc.id}/', {'name': '現金'})
        assert resp.status_code == 200


# --- Transaction：可讀關聯 + 關聯 queryset 收斂到本人（資安關鍵）---


@pytest.mark.django_db
class TestTransactionViewSet:
    URL = '/api/ledger/transactions/'

    def _account(self, owner, name='現金'):
        return Account.objects.create(user=owner, name=name, type=Account.Type.CASH)

    def test_requires_authentication(self):
        assert APIClient().get(self.URL).status_code == 401

    def test_create_forces_owner(self, auth_client, user, other_user):
        acc = self._account(user)
        resp = auth_client.post(
            self.URL,
            {
                'account': str(acc.id),
                'amount': '100.00',
                'type': 'expense',
                'user': str(other_user.id),  # 應被忽略
            },
            format='json',
        )
        assert resp.status_code == 201
        assert Transaction.objects.get(id=resp.data['id']).user == user

    def test_rejects_others_account(self, auth_client, other_user):
        # 別人的 account 不在收斂後的 queryset 內 → 400（不是 500、不靜默接受）
        theirs = self._account(other_user, name='別人的')
        resp = auth_client.post(
            self.URL,
            {'account': str(theirs.id), 'amount': '100.00', 'type': 'expense'},
            format='json',
        )
        assert resp.status_code == 400

    def test_rejects_others_category(self, auth_client, user, other_user):
        acc = self._account(user)
        theirs_cat = Category.objects.create(user=other_user, name='別人的分類')
        resp = auth_client.post(
            self.URL,
            {
                'account': str(acc.id),
                'category': str(theirs_cat.id),
                'amount': '100.00',
                'type': 'expense',
            },
            format='json',
        )
        assert resp.status_code == 400

    def test_rejects_others_tag(self, auth_client, user, other_user):
        acc = self._account(user)
        theirs_tag = Tag.objects.create(user=other_user, name='別人的標籤')
        resp = auth_client.post(
            self.URL,
            {
                'account': str(acc.id),
                'amount': '100.00',
                'type': 'expense',
                'tags': [str(theirs_tag.id)],
            },
            format='json',
        )
        assert resp.status_code == 400

    def test_response_includes_related_names(self, auth_client, user):
        acc = self._account(user)
        cat = Category.objects.create(user=user, name='飲食')
        tag = Tag.objects.create(user=user, name='日本旅遊')
        txn = Transaction.objects.create(
            user=user,
            account=acc,
            category=cat,
            amount=Decimal('100'),
            type=Transaction.Type.EXPENSE,
        )
        txn.tags.add(tag)
        resp = auth_client.get(f'{self.URL}{txn.id}/')
        assert resp.data['account_name'] == '現金'
        assert resp.data['category_name'] == '飲食'
        assert resp.data['tag_names'] == ['日本旅遊']

    def test_occurred_at_defaults_when_omitted(self, auth_client, user):
        acc = self._account(user)
        resp = auth_client.post(
            self.URL,
            {'account': str(acc.id), 'amount': '100.00', 'type': 'expense'},
            format='json',
        )
        assert resp.status_code == 201
        assert resp.data['occurred_at'] is not None

    def test_cannot_reach_others_transaction(self, auth_client, other_user):
        their_acc = self._account(other_user, name='別人的')
        theirs = Transaction.objects.create(
            user=other_user,
            account=their_acc,
            amount=Decimal('50'),
            type=Transaction.Type.INCOME,
        )
        detail = f'{self.URL}{theirs.id}/'
        assert auth_client.get(detail).status_code == 404
        assert auth_client.patch(detail, {'amount': '1.00'}, format='json').status_code == 404
        assert auth_client.delete(detail).status_code == 404


# --- Transaction 列表過濾：TransactionFilter 的八個參數與安全行為 ---


@pytest.mark.django_db
class TestTransactionFilters:
    URL = '/api/ledger/transactions/'

    @pytest.fixture
    def data(self, user):
        # 三筆交易蓋出可區分的維度：帳戶×2、類型×2、金額三檔、六七月各有、
        # 一筆掛 tag、一筆有 description。
        cash = Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
        bank = Account.objects.create(user=user, name='銀行', type=Account.Type.BANK)
        travel = Tag.objects.create(user=user, name='旅遊')
        Transaction.objects.create(
            user=user,
            account=cash,
            amount=Decimal('120'),
            type=Transaction.Type.EXPENSE,
            name='六月午餐',
            occurred_at=datetime(2026, 6, 10, 12, 0, tzinfo=UTC),
        )
        hotel = Transaction.objects.create(
            user=user,
            account=bank,
            amount=Decimal('3000'),
            type=Transaction.Type.EXPENSE,
            name='七月住宿',
            description='含早餐的溫泉旅館',
            occurred_at=datetime(2026, 7, 5, 18, 0, tzinfo=UTC),
        )
        hotel.tags.add(travel)
        Transaction.objects.create(
            user=user,
            account=bank,
            amount=Decimal('50000'),
            type=Transaction.Type.INCOME,
            name='薪水',
            occurred_at=datetime(2026, 7, 1, 9, 0, tzinfo=UTC),
        )
        return {'cash': cash, 'travel': travel}

    def _names(self, resp):
        assert resp.status_code == 200
        return {row['name'] for row in resp.data['results']}

    def test_occurred_range(self, auth_client, data):
        resp = auth_client.get(
            self.URL,
            {'occurred_after': '2026-07-01T00:00:00Z', 'occurred_before': '2026-07-31T23:59:59Z'},
        )
        assert self._names(resp) == {'七月住宿', '薪水'}

    def test_account(self, auth_client, data):
        resp = auth_client.get(self.URL, {'account': str(data['cash'].id)})
        assert self._names(resp) == {'六月午餐'}

    def test_type(self, auth_client, data):
        resp = auth_client.get(self.URL, {'type': 'income'})
        assert self._names(resp) == {'薪水'}

    def test_amount_range_inclusive(self, auth_client, data):
        # 「超過 1000 的支出」型查詢；min/max 皆含等於（3000 在 amount_min=3000 要出現）
        resp = auth_client.get(self.URL, {'amount_min': '3000', 'type': 'expense'})
        assert self._names(resp) == {'七月住宿'}
        resp = auth_client.get(self.URL, {'amount_max': '120'})
        assert self._names(resp) == {'六月午餐'}

    def test_tags_any_single_value(self, auth_client, data):
        resp = auth_client.get(self.URL, {'tags_any': str(data['travel'].id)})
        assert self._names(resp) == {'七月住宿'}

    def test_others_account_uuid_yields_empty_not_400(self, auth_client, other_user, data):
        # 安全：合法但非本人的 UUID 不可變成存在性探測器——一律 200 空，
        # 與「跨用戶存取回 404 藏存在性」同一原則。
        theirs = Account.objects.create(user=other_user, name='別人的', type=Account.Type.CASH)
        resp = auth_client.get(self.URL, {'account': str(theirs.id)})
        assert resp.status_code == 200
        assert resp.data['results'] == []

    def test_malformed_uuid_rejected(self, auth_client, data):
        # 格式錯誤是輸入驗證問題，照常 400
        assert auth_client.get(self.URL, {'account': 'not-a-uuid'}).status_code == 400

    def test_search_hits_name_and_description(self, auth_client, data):
        # SearchFilter：一個 ?search= 對 name/description 做 icontains OR
        assert self._names(auth_client.get(self.URL, {'search': '住宿'})) == {'七月住宿'}
        assert self._names(auth_client.get(self.URL, {'search': '早餐'})) == {'七月住宿'}

    def test_ordering_by_amount(self, auth_client, data):
        resp = auth_client.get(self.URL, {'ordering': 'amount'})
        assert [row['name'] for row in resp.data['results']] == ['六月午餐', '七月住宿', '薪水']
        resp = auth_client.get(self.URL, {'ordering': '-amount'})
        assert [row['name'] for row in resp.data['results']] == ['薪水', '七月住宿', '六月午餐']


# --- Transaction 多標籤過濾：tags_any（OR）／tags_all（AND）的語意與安全邊界 ---


@pytest.mark.django_db
class TestTransactionTagFilters:
    URL = '/api/ledger/transactions/'

    @pytest.fixture
    def tags(self, user):
        # 四筆交易蓋出 OR/AND 的所有分界：[旅遊]、[旅遊+餐飲]、[餐飲]、[]；
        # 「未使用」tag 存在但沒掛任何交易，驗 AND 混入它時整體必空。
        acc = Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
        travel = Tag.objects.create(user=user, name='旅遊')
        food = Tag.objects.create(user=user, name='餐飲')
        unused = Tag.objects.create(user=user, name='未使用')

        def make(name, tag_list):
            txn = Transaction.objects.create(
                user=user,
                account=acc,
                amount=Decimal('100'),
                type=Transaction.Type.EXPENSE,
                name=name,
            )
            txn.tags.add(*tag_list)

        make('機票', [travel])
        make('旅館早餐', [travel, food])
        make('午餐', [food])
        make('雜項', [])
        return {'travel': travel, 'food': food, 'unused': unused}

    def _ids(self, *tag_objs):
        return ','.join(str(t.id) for t in tag_objs)

    def _names(self, resp):
        assert resp.status_code == 200
        return {row['name'] for row in resp.data['results']}

    def test_any_matches_either_tag_without_duplicates(
        self, auth_client, tags, django_assert_num_queries
    ):
        # OR：命中任一 tag 即列出；掛兩個命中 tag 的「旅館早餐」只能出現一次
        # （tags__in 的 JOIN 會出多列，靠 distinct 收斂），count 同步正確。
        # 查詢數維持 3（COUNT＋主查＋tags prefetch）——多值過濾只讓主查變複雜，不加查詢。
        with django_assert_num_queries(3):
            resp = auth_client.get(self.URL, {'tags_any': self._ids(tags['travel'], tags['food'])})
        names = [row['name'] for row in resp.data['results']]
        assert sorted(names) == ['午餐', '旅館早餐', '機票']
        assert resp.data['count'] == 3

    def test_all_requires_every_tag(self, auth_client, tags):
        resp = auth_client.get(self.URL, {'tags_all': self._ids(tags['travel'], tags['food'])})
        assert self._names(resp) == {'旅館早餐'}

    def test_all_single_matches_superset(self, auth_client, tags):
        # 「包含」語意：掛了指定 tag 之外還多掛別的也算命中
        resp = auth_client.get(self.URL, {'tags_all': self._ids(tags['travel'])})
        assert self._names(resp) == {'機票', '旅館早餐'}

    def test_all_with_unmatched_tag_yields_empty(self, auth_client, tags):
        resp = auth_client.get(self.URL, {'tags_all': self._ids(tags['travel'], tags['unused'])})
        assert self._names(resp) == set()

    def test_any_and_all_stack(self, auth_client, tags):
        # 兩參數同給 = 條件交集（filter backend 對同一 queryset 依序疊加）
        resp = auth_client.get(
            self.URL,
            {'tags_any': self._ids(tags['food']), 'tags_all': self._ids(tags['travel'])},
        )
        assert self._names(resp) == {'旅館早餐'}

    def test_others_tag_uuid_yields_empty_not_400(self, auth_client, other_user, tags):
        # 安全：合法但非本人的 UUID 不可變成存在性探測器——一律 200 空/不命中，
        # 與帳戶/分類過濾的 UUIDFilter 同一原則。
        theirs = Tag.objects.create(user=other_user, name='別人的標籤')
        assert self._names(auth_client.get(self.URL, {'tags_any': str(theirs.id)})) == set()
        resp = auth_client.get(self.URL, {'tags_all': self._ids(tags['travel'], theirs)})
        assert self._names(resp) == set()

    def test_malformed_uuid_in_csv_rejected(self, auth_client, tags):
        # 逐值驗格式：清單裡混一個壞值就是 400（輸入驗證問題，照常拒絕）
        bad = f'{tags["travel"].id},not-a-uuid'
        assert auth_client.get(self.URL, {'tags_any': bad}).status_code == 400
        assert auth_client.get(self.URL, {'tags_all': 'not-a-uuid'}).status_code == 400

    def test_empty_param_is_ignored(self, auth_client, tags):
        # 空字串照 django-filter 慣例忽略（不過濾）
        resp = auth_client.get(self.URL, {'tags_any': ''})
        assert resp.data['count'] == 4

    def test_csv_empty_member_ignored(self, auth_client, tags):
        # 連續逗號（a,,b）的空成員被靜默忽略、其餘合法值照常過濾（實測行為）——
        # 與「空參數整體忽略」同一寬容精神，這裡把它釘成契約。
        raw = f'{tags["travel"].id},,{tags["food"].id}'
        resp = auth_client.get(self.URL, {'tags_any': raw})
        assert resp.status_code == 200
        assert resp.data['count'] == 3


# --- Transaction 餘額維護：建/編輯/刪皆對帳（balance == Σincome − Σexpense）---


@pytest.mark.django_db
class TestTransactionBalance:
    URL = '/api/ledger/transactions/'

    def _account(self, owner, name='現金'):
        return Account.objects.create(user=owner, name=name, type=Account.Type.CASH)

    def _post(self, client, acc, amount, type_):
        return client.post(
            self.URL,
            {'account': str(acc.id), 'amount': amount, 'type': type_},
            format='json',
        )

    def test_create_income_increases_balance(self, auth_client, user):
        acc = self._account(user)
        assert self._post(auth_client, acc, '100.00', 'income').status_code == 201
        acc.refresh_from_db()
        assert acc.balance == Decimal('100.00')

    def test_create_expense_decreases_balance(self, auth_client, user):
        acc = self._account(user)
        assert self._post(auth_client, acc, '30.00', 'expense').status_code == 201
        acc.refresh_from_db()
        assert acc.balance == Decimal('-30.00')  # 允許負餘額（透支/信用卡情境）

    def test_reconciliation_invariant(self, auth_client, user):
        # 混合多筆 → balance 恆等於 Σincome − Σexpense
        acc = self._account(user)
        self._post(auth_client, acc, '100.00', 'income')
        self._post(auth_client, acc, '250.50', 'income')
        self._post(auth_client, acc, '30.00', 'expense')
        acc.refresh_from_db()
        assert acc.balance == Decimal('320.50')  # 100 + 250.50 − 30

    def test_edit_amount_adjusts_balance(self, auth_client, user):
        acc = self._account(user)
        txn_id = self._post(auth_client, acc, '100.00', 'expense').data['id']
        auth_client.patch(f'{self.URL}{txn_id}/', {'amount': '40.00'}, format='json')
        acc.refresh_from_db()
        assert acc.balance == Decimal('-40.00')  # 還原 -100、套用 -40（不是 -140）

    def test_edit_type_flip_income_to_expense(self, auth_client, user):
        acc = self._account(user)
        txn_id = self._post(auth_client, acc, '100.00', 'income').data['id']
        auth_client.patch(f'{self.URL}{txn_id}/', {'type': 'expense'}, format='json')
        acc.refresh_from_db()
        assert acc.balance == Decimal('-100.00')  # +100 還原後套 -100

    def test_edit_moves_balance_between_accounts(self, auth_client, user):
        a = self._account(user, name='現金')
        b = self._account(user, name='銀行')
        txn_id = self._post(auth_client, a, '100.00', 'expense').data['id']
        auth_client.patch(f'{self.URL}{txn_id}/', {'account': str(b.id)}, format='json')
        a.refresh_from_db()
        b.refresh_from_db()
        assert a.balance == Decimal('0.00')  # 舊帳戶還原
        assert b.balance == Decimal('-100.00')  # 新帳戶套用

    def test_delete_reverses_balance(self, auth_client, user):
        acc = self._account(user)
        txn_id = self._post(auth_client, acc, '100.00', 'income').data['id']
        auth_client.delete(f'{self.URL}{txn_id}/')
        acc.refresh_from_db()
        assert acc.balance == Decimal('0.00')  # 反向沖銷回 0


# --- 並發：F() 生產路徑不丟更新 + select_for_update 鎖機制（真交易，故 transaction=True）---


def _run_concurrently(target, count):
    """開 count 條執行緒跑 target()，收集各執行緒的例外。

    thread-local 連線各自 close，否則洩漏、卡住 teardown；worker 的錯不吞、往外浮。
    """
    errors = []

    def wrapped():
        try:
            target()
        except Exception as exc:
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=wrapped) for _ in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors


@pytest.mark.django_db(transaction=True)
def test_concurrent_creates_no_lost_update(user):
    # 招牌：20 條執行緒各記一筆 +1 收入到同一帳戶 → balance 必為 20。
    # F() 讓加法在 DB 端算（UPDATE balance = balance + 1），並發 UPDATE 由 DB 排隊 → 無丟失。
    # 若改成 Python 端「讀 balance → +1 → save」，這裡會掉更新、結果少於 20。
    acc = Account.objects.create(user=user, name='現金', type=Account.Type.CASH)

    def create_one():
        Transaction.objects.create(
            user=user, account=acc, amount=Decimal('1'), type=Transaction.Type.INCOME
        )
        services.apply_to_balance(acc.id, Transaction.Type.INCOME, Decimal('1'))

    _run_concurrently(create_one, count=20)
    acc.refresh_from_db()
    assert acc.balance == Decimal('20')


@pytest.mark.django_db(transaction=True)
def test_select_for_update_serializes_read_modify_write(user):
    # 鎖機制示範（非生產路徑）：故意用「讀-改-寫」（無 F()）——不鎖的話 20 條並發會掉更新。
    # select_for_update 鎖住該列，後到者卡住等前者 commit → 序列化讀-改-寫 → 結果正確。
    # 這正是 perform_update 讀舊值時依賴的機制（同筆並發編輯讀到的是已提交的前一版）。
    acc = Account.objects.create(user=user, name='現金', type=Account.Type.CASH)

    def increment_locked():
        with transaction.atomic():
            locked = Account.objects.select_for_update().get(pk=acc.id)
            locked.balance = locked.balance + Decimal('1')
            locked.save()

    _run_concurrently(increment_locked, count=20)
    acc.refresh_from_db()
    assert acc.balance == Decimal('20')


# --- SavingsGoal：判別式 validate（月度/年度）→ 400，外加任意 year/month 與隔離 ---


@pytest.mark.django_db
class TestSavingsGoalViewSet:
    URL = '/api/ledger/savings-goals/'

    def test_requires_authentication(self):
        assert APIClient().get(self.URL).status_code == 401

    def test_create_monthly_forces_owner(self, auth_client, user, other_user):
        resp = auth_client.post(
            self.URL,
            {
                'period_type': 'monthly',
                'year': 2026,
                'month': 6,
                'amount': '10000.00',
                'user': str(other_user.id),  # 應被忽略
            },
            format='json',
        )
        assert resp.status_code == 201
        assert SavingsGoal.objects.get(id=resp.data['id']).user == user

    def test_create_yearly_ok(self, auth_client):
        resp = auth_client.post(
            self.URL,
            {'period_type': 'yearly', 'year': 2025, 'amount': '120000.00'},
            format='json',
        )
        assert resp.status_code == 201

    def test_monthly_missing_month_rejected(self, auth_client):
        resp = auth_client.post(
            self.URL,
            {'period_type': 'monthly', 'year': 2026, 'amount': '10000.00'},
            format='json',
        )
        assert resp.status_code == 400

    def test_monthly_month_out_of_range_rejected(self, auth_client):
        resp = auth_client.post(
            self.URL,
            {'period_type': 'monthly', 'year': 2026, 'month': 13, 'amount': '10000.00'},
            format='json',
        )
        assert resp.status_code == 400

    def test_yearly_with_month_rejected(self, auth_client):
        resp = auth_client.post(
            self.URL,
            {'period_type': 'yearly', 'year': 2026, 'month': 5, 'amount': '10000.00'},
            format='json',
        )
        assert resp.status_code == 400

    def test_duplicate_period_rejected(self, auth_client, user):
        # 同期間重複 → 乾淨 400，而非落到 DB 唯一約束回 500
        SavingsGoal.objects.create(
            user=user,
            period_type=SavingsGoal.PeriodType.MONTHLY,
            year=2026,
            month=6,
            amount=Decimal('10000'),
        )
        resp = auth_client.post(
            self.URL,
            {'period_type': 'monthly', 'year': 2026, 'month': 6, 'amount': '20000.00'},
            format='json',
        )
        assert resp.status_code == 400

    def test_can_edit_past_period(self, auth_client, user):
        # 允許任意（含過去）year/month 的新增與修改
        goal = SavingsGoal.objects.create(
            user=user,
            period_type=SavingsGoal.PeriodType.MONTHLY,
            year=2020,
            month=1,
            amount=Decimal('5000'),
        )
        resp = auth_client.patch(f'{self.URL}{goal.id}/', {'amount': '6000.00'}, format='json')
        assert resp.status_code == 200
        goal.refresh_from_db()
        assert goal.amount == Decimal('6000.00')

    def test_cannot_reach_others_goal(self, auth_client, other_user):
        theirs = SavingsGoal.objects.create(
            user=other_user,
            period_type=SavingsGoal.PeriodType.YEARLY,
            year=2026,
            amount=Decimal('100000'),
        )
        detail = f'{self.URL}{theirs.id}/'
        assert auth_client.get(detail).status_code == 404
        assert auth_client.patch(detail, {'amount': '1.00'}, format='json').status_code == 404
        assert auth_client.delete(detail).status_code == 404


# --- RecurringRule：CRUD、兩層隔離、next_run_date 推算與重算語意 ---


@pytest.mark.django_db
class TestRecurringRuleViewSet:
    URL = '/api/ledger/recurring-rules/'

    def _account(self, owner, name='銀行'):
        return Account.objects.create(user=owner, name=name, type=Account.Type.BANK)

    def _rule(self, owner, account=None, **kwargs):
        kwargs.setdefault('amount', Decimal('18000.00'))
        kwargs.setdefault('type', Transaction.Type.EXPENSE)
        kwargs.setdefault('day_of_month', 5)
        kwargs.setdefault('next_run_date', next_due(kwargs['day_of_month'], timezone.localdate()))
        return RecurringRule.objects.create(
            user=owner, account=account or self._account(owner), **kwargs
        )

    def test_requires_authentication(self):
        assert APIClient().get(self.URL).status_code == 401

    def test_create_forces_owner_and_computes_next_run_date(self, auth_client, user, other_user):
        acc = self._account(user)
        resp = auth_client.post(
            self.URL,
            {
                'account': str(acc.id),
                'amount': '18000.00',
                'type': 'expense',
                'name': '房租',
                'day_of_month': 5,
                'user': str(other_user.id),  # 應被忽略
                'next_run_date': '2000-01-01',  # 唯讀，應被忽略（游標由系統推算）
            },
            format='json',
        )
        assert resp.status_code == 201
        rule = RecurringRule.objects.get(id=resp.data['id'])
        assert rule.user == user
        assert rule.next_run_date == next_due(5, timezone.localdate())

    def test_list_returns_only_own(self, auth_client, user, other_user):
        self._rule(user, name='我的')
        self._rule(other_user, name='別人的')
        resp = auth_client.get(self.URL)
        assert resp.status_code == 200
        assert [row['name'] for row in resp.data['results']] == ['我的']

    def test_cannot_reach_others_rule(self, auth_client, other_user):
        theirs = self._rule(other_user)
        detail = f'{self.URL}{theirs.id}/'
        assert auth_client.get(detail).status_code == 404
        assert auth_client.patch(detail, {'amount': '1.00'}).status_code == 404
        assert auth_client.delete(detail).status_code == 404

    @pytest.mark.parametrize('day', [0, 32])
    def test_day_of_month_out_of_range_returns_400(self, auth_client, user, day):
        acc = self._account(user)
        resp = auth_client.post(
            self.URL,
            {'account': str(acc.id), 'amount': '100.00', 'type': 'expense', 'day_of_month': day},
            format='json',
        )
        assert resp.status_code == 400

    def test_rejects_others_account(self, auth_client, other_user):
        # 第二層隔離：serializer 把 account queryset 收斂到本人 → 別人的 id 是 400 不是 500
        theirs = self._account(other_user, name='別人的')
        resp = auth_client.post(
            self.URL,
            {'account': str(theirs.id), 'amount': '100.00', 'type': 'expense', 'day_of_month': 5},
            format='json',
        )
        assert resp.status_code == 400

    def test_rejects_others_category(self, auth_client, user, other_user):
        acc = self._account(user)
        theirs_cat = Category.objects.create(user=other_user, name='別人的分類')
        resp = auth_client.post(
            self.URL,
            {
                'account': str(acc.id),
                'category': str(theirs_cat.id),
                'amount': '100.00',
                'type': 'expense',
                'day_of_month': 5,
            },
            format='json',
        )
        assert resp.status_code == 400

    def test_delete_account_with_rule_returns_409(self, auth_client, user):
        # RecurringRule.account 也是 PROTECT：訊息要涵蓋規則，不能只說「尚有交易」
        acc = self._account(user)
        self._rule(user, account=acc)
        resp = auth_client.delete(f'/api/ledger/accounts/{acc.id}/')
        assert resp.status_code == 409
        assert Account.objects.filter(id=acc.id).exists()

    def test_changing_day_of_month_recomputes_next_run_date(self, auth_client, user):
        rule = self._rule(user, day_of_month=5)
        resp = auth_client.patch(f'{self.URL}{rule.id}/', {'day_of_month': 20}, format='json')
        assert resp.status_code == 200
        rule.refresh_from_db()
        assert rule.next_run_date == next_due(20, timezone.localdate())

    def test_reactivating_recomputes_from_today_without_backfilling(self, auth_client, user):
        # 停用期間不補帳：暫停是使用者的意思表示，不是服務停機
        today = timezone.localdate()
        rule = self._rule(
            user, day_of_month=5, is_active=False, next_run_date=today - timedelta(days=90)
        )
        resp = auth_client.patch(f'{self.URL}{rule.id}/', {'is_active': True}, format='json')
        assert resp.status_code == 200
        rule.refresh_from_db()
        assert rule.next_run_date == next_due(5, today)
        assert rule.next_run_date >= today

    def test_editing_amount_leaves_next_run_date_untouched(self, auth_client, user):
        rule = self._rule(user, day_of_month=5)
        original = rule.next_run_date
        resp = auth_client.patch(f'{self.URL}{rule.id}/', {'amount': '25000.00'}, format='json')
        assert resp.status_code == 200
        rule.refresh_from_db()
        assert rule.next_run_date == original
        assert rule.amount == Decimal('25000.00')


# --- 定期定額任務：冪等（唯一約束）、catch-up、短月 clamp、單條失敗隔離 ---


def _run_recurring_task(today):
    """把「今天」釘死再跑任務。

    一律 .apply() 不用 .delay()：容器的 manage.py test 吃生產 broker，.delay() 會把任務
    投給 live worker，本地斷言什麼都收不到。
    """
    with mock.patch('ledger.tasks.timezone.localdate', return_value=today):
        return post_due_recurring_rules.apply().get()


def _make_rule(owner, **kwargs):
    account = kwargs.pop('account', None) or Account.objects.create(
        user=owner, name=kwargs.pop('account_name', '銀行'), type=Account.Type.BANK
    )
    kwargs.setdefault('amount', Decimal('18000.00'))
    kwargs.setdefault('type', Transaction.Type.EXPENSE)
    kwargs.setdefault('day_of_month', 5)
    return RecurringRule.objects.create(user=owner, account=account, **kwargs)


@pytest.mark.django_db
def test_task_posts_due_rule(user):
    category = Category.objects.create(user=user, name='居住')
    rule = _make_rule(
        user,
        category=category,
        name='房租',
        description='每月房租',
        next_run_date=date(2026, 7, 5),
    )

    assert _run_recurring_task(date(2026, 7, 5)) == 1

    txn = Transaction.objects.get(source_rule=rule)
    assert txn.user_id == user.id
    assert txn.amount == Decimal('18000.00')
    assert txn.type == Transaction.Type.EXPENSE
    assert (txn.name, txn.description) == ('房租', '每月房租')
    assert txn.category_id == category.id
    # occurred_at ＝ 到期日的當地 00:00
    local = timezone.localtime(txn.occurred_at)
    assert (local.date(), local.time()) == (date(2026, 7, 5), time(0, 0))

    rule.account.refresh_from_db()
    assert rule.account.balance == Decimal('-18000.00')
    rule.refresh_from_db()
    assert rule.next_run_date == date(2026, 8, 5)


@pytest.mark.django_db
def test_task_skips_not_yet_due_and_inactive(user):
    future = _make_rule(user, account_name='未到期', next_run_date=date(2026, 7, 10))
    paused = _make_rule(
        user, account_name='已停用', is_active=False, next_run_date=date(2026, 7, 1)
    )

    assert _run_recurring_task(date(2026, 7, 5)) == 0

    assert not Transaction.objects.exists()
    future.refresh_from_db()
    paused.refresh_from_db()
    assert future.next_run_date == date(2026, 7, 10)
    assert paused.next_run_date == date(2026, 7, 1)


@pytest.mark.django_db
def test_task_is_idempotent_on_redelivery(user):
    # 冪等的證明必須繞過游標：把 next_run_date 撥回原值再跑一次，模擬 beat 重複投遞／
    # 任務重試。擋下第二筆的是 (source_rule, occurred_at) 唯一約束，不是游標。
    rule = _make_rule(user, next_run_date=date(2026, 7, 5))
    _run_recurring_task(date(2026, 7, 5))
    RecurringRule.objects.filter(pk=rule.pk).update(next_run_date=date(2026, 7, 5))

    assert _run_recurring_task(date(2026, 7, 5)) == 0  # 一筆都沒新建

    assert Transaction.objects.filter(source_rule=rule).count() == 1
    rule.account.refresh_from_db()
    assert rule.account.balance == Decimal('-18000.00')  # 餘額沒被扣第二次


@pytest.mark.django_db
def test_task_catches_up_all_missed_occurrences(user):
    # 停機三個月，房租還是欠三筆：逐期補建，occurred_at 各自是原到期日
    rule = _make_rule(user, amount=Decimal('1000.00'), next_run_date=date(2026, 4, 5))

    assert _run_recurring_task(date(2026, 6, 5)) == 3

    dates = sorted(
        timezone.localtime(t.occurred_at).date()
        for t in Transaction.objects.filter(source_rule=rule)
    )
    assert dates == [date(2026, 4, 5), date(2026, 5, 5), date(2026, 6, 5)]
    rule.account.refresh_from_db()
    assert rule.account.balance == Decimal('-3000.00')
    rule.refresh_from_db()
    assert rule.next_run_date == date(2026, 7, 5)


@pytest.mark.django_db
def test_task_clamps_short_month(user):
    # 每月 31 號：2 月落在月底，且不因此漂移——3 月仍回到 31 號
    rule = _make_rule(
        user, amount=Decimal('100.00'), day_of_month=31, next_run_date=date(2026, 1, 31)
    )

    assert _run_recurring_task(date(2026, 2, 28)) == 2

    dates = sorted(
        timezone.localtime(t.occurred_at).date()
        for t in Transaction.objects.filter(source_rule=rule)
    )
    assert dates == [date(2026, 1, 31), date(2026, 2, 28)]
    rule.refresh_from_db()
    assert rule.next_run_date == date(2026, 3, 31)


@pytest.mark.django_db
def test_task_isolates_failing_rule(user, caplog):
    # 一條爛規則不炸整批：它自己 rollback，其餘照建，錯誤留在 log 裡（背景任務沒有回應可看，
    # log 是唯一的觀測窗）
    bad = _make_rule(
        user,
        account_name='壞的',
        amount=Decimal('111.00'),
        day_of_month=5,
        next_run_date=date(2026, 7, 5),
    )
    good = _make_rule(
        user,
        account_name='好的',
        amount=Decimal('222.00'),
        day_of_month=20,
        next_run_date=date(2026, 7, 20),
    )
    real_apply = services.apply_to_balance

    def explode(account_id, txn_type, amount):
        if amount == Decimal('111.00'):
            raise RuntimeError('模擬單條規則失敗')
        real_apply(account_id, txn_type, amount)

    with caplog.at_level(logging.ERROR, logger='ledger.tasks'):
        with mock.patch('ledger.tasks.services.apply_to_balance', side_effect=explode):
            assert _run_recurring_task(date(2026, 7, 25)) == 1

    assert not Transaction.objects.filter(source_rule=bad).exists()
    bad.refresh_from_db()
    assert bad.next_run_date == date(2026, 7, 5)  # 游標沒推進，下次還會再試

    assert Transaction.objects.filter(source_rule=good).count() == 1
    good.account.refresh_from_db()
    assert good.account.balance == Decimal('-222.00')
    assert '處理失敗' in caplog.text


@pytest.mark.django_db
def test_task_keeps_users_isolated(user, other_user):
    mine = _make_rule(user, amount=Decimal('100.00'), next_run_date=date(2026, 7, 5))
    theirs = _make_rule(other_user, amount=Decimal('900.00'), next_run_date=date(2026, 7, 5))

    assert _run_recurring_task(date(2026, 7, 5)) == 2

    assert Transaction.objects.get(source_rule=mine).user_id == user.id
    assert Transaction.objects.get(source_rule=theirs).user_id == other_user.id
    mine.account.refresh_from_db()
    theirs.account.refresh_from_db()
    assert (mine.account.balance, theirs.account.balance) == (
        Decimal('-100.00'),
        Decimal('-900.00'),
    )


@pytest.mark.django_db
def test_task_invalidates_balance_history_cache(user, django_capture_on_commit_callbacks):
    # 自動記帳改了餘額 → 該 user 的 balance-history 快取必須失效，否則 TTL 內讀到舊值
    rule = _make_rule(user, next_run_date=date(2026, 7, 5))
    reports.balance_history_cached(user)  # 先把快取填起來
    assert cache.get(f'reports:balance-history:{user.id}') is not None

    with django_capture_on_commit_callbacks(execute=True):
        _run_recurring_task(date(2026, 7, 5))

    assert cache.get(f'reports:balance-history:{rule.user_id}') is None


# --- carry-forward：建交易時把上月月度目標帶入「真實當下月」（mock 固定 now → 決定性）---


def _at_month(year, month):
    """把 services 看到的『現在』釘死成指定年月 → carry-forward 的當下月變決定性。"""
    return mock.patch(
        'ledger.services.timezone.now', return_value=datetime(year, month, 15, tzinfo=UTC)
    )


@pytest.mark.django_db
class TestCarryForwardSavingsGoal:
    URL = '/api/ledger/transactions/'

    def _account(self, user):
        return Account.objects.create(user=user, name='現金', type=Account.Type.CASH)

    def _monthly_goal(self, user, year, month, amount):
        return SavingsGoal.objects.create(
            user=user,
            period_type=SavingsGoal.PeriodType.MONTHLY,
            year=year,
            month=month,
            amount=Decimal(amount),
        )

    def _month_goals(self, user, year, month):
        return SavingsGoal.objects.filter(
            user=user, period_type=SavingsGoal.PeriodType.MONTHLY, year=year, month=month
        )

    def _post_txn(self, client, acc, occurred_at=None):
        body = {'account': str(acc.id), 'amount': '10.00', 'type': 'expense'}
        if occurred_at:
            body['occurred_at'] = occurred_at
        return client.post(self.URL, body, format='json')

    def test_first_txn_copies_prev_month_goal(self, auth_client, user):
        # 上月有目標 → 當下月第一筆交易自動建當下月目標、複製上月金額
        self._monthly_goal(user, 2026, 6, '5000')
        acc = self._account(user)
        with _at_month(2026, 7):
            assert self._post_txn(auth_client, acc).status_code == 201
        assert self._month_goals(user, 2026, 7).get().amount == Decimal('5000')

    def test_no_prev_goal_creates_nothing(self, auth_client, user):
        # 上月從未設定 → 不建（carry-forward 只複製、不無中生有）
        acc = self._account(user)
        with _at_month(2026, 7):
            self._post_txn(auth_client, acc)
        assert not self._month_goals(user, 2026, 7).exists()

    def test_second_txn_does_not_duplicate(self, auth_client, user):
        # 同月第二筆 → get_or_create 找到既有，不重複
        self._monthly_goal(user, 2026, 6, '5000')
        acc = self._account(user)
        with _at_month(2026, 7):
            self._post_txn(auth_client, acc)
            self._post_txn(auth_client, acc)
        assert self._month_goals(user, 2026, 7).count() == 1

    def test_january_prev_is_december_last_year(self, auth_client, user):
        # month==1 → 上月為 (y−1, 12)，跨年正確
        self._monthly_goal(user, 2025, 12, '8000')
        acc = self._account(user)
        with _at_month(2026, 1):
            self._post_txn(auth_client, acc)
        assert self._month_goals(user, 2026, 1).get().amount == Decimal('8000')

    def test_backfilled_past_txn_does_not_build_history(self, auth_client, user):
        # 補登：occurred_at 在過去月，但 carry-forward 只碰真實當下月 → 不建該過去月目標
        self._monthly_goal(user, 2026, 6, '5000')
        acc = self._account(user)
        with _at_month(2026, 7):
            resp = self._post_txn(auth_client, acc, occurred_at='2026-03-10T00:00:00Z')
            assert resp.status_code == 201
        assert not self._month_goals(user, 2026, 3).exists()  # 過去月不冒出來
        assert self._month_goals(user, 2026, 7).exists()  # 只碰當下月


@pytest.mark.django_db(transaction=True)
def test_carry_forward_concurrent_creates_single_goal(user):
    # 並發護欄：新月同時多請求 → get_or_create 的唯一約束 + savepoint 使只生一筆（不重複、不 500）。
    # 包在 transaction.atomic() 內模擬 perform_create 的真實情境（savepoint 在外層交易內安全）。
    SavingsGoal.objects.create(
        user=user,
        period_type=SavingsGoal.PeriodType.MONTHLY,
        year=2026,
        month=6,
        amount=Decimal('5000'),
    )

    def carry():
        with _at_month(2026, 7), transaction.atomic():
            services.carry_forward_savings_goal(user)

    _run_concurrently(carry, count=10)
    assert (
        SavingsGoal.objects.filter(
            user=user, period_type=SavingsGoal.PeriodType.MONTHLY, year=2026, month=7
        ).count()
        == 1
    )


# --- 交易列表查詢數：N+1 展示 + 固定查詢數鎖定 ---


@pytest.mark.django_db
class TestTransactionListQueryCount:
    URL = '/api/ledger/transactions/'
    N = 20

    def _build_transactions(self, user):
        # 每筆都掛 account + category + 2 個 tags，讓序列化的每個關聯欄位都有東西可抓。
        acc = Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
        cat = Category.objects.create(user=user, name='飲食')
        tags = [Tag.objects.create(user=user, name=f'標籤{i}') for i in range(2)]
        for _ in range(self.N):
            txn = Transaction.objects.create(
                user=user,
                account=acc,
                category=cat,
                amount=Decimal('100'),
                type=Transaction.Type.EXPENSE,
            )
            txn.tags.add(*tags)

    def test_naive_serialization_query_count_grows_linearly(self, user):
        # 展示（非回歸防線）：未優化的 queryset 序列化時，每筆各自抓
        # account.name、category.name、tags×2 欄位 ≈ 1 + 4N 次查詢——隨筆數線性成長。
        self._build_transactions(user)
        with CaptureQueriesContext(connection) as ctx:
            TransactionSerializer(Transaction.objects.all(), many=True).data
        print(f'\nnaive 序列化 {self.N} 筆交易 = {len(ctx)} 次查詢')
        assert len(ctx) >= 3 * self.N

    def test_list_endpoint_query_count_is_fixed(self, auth_client, user, django_assert_num_queries):
        # 回歸防線：分頁 COUNT 一次、select_related JOIN 一次帶回 account/category、
        # prefetch_related 一次帶回全部 tags → 固定 3 次、與筆數無關。
        # 改壞 queryset/serializer 這裡當場紅。
        self._build_transactions(user)
        with django_assert_num_queries(3):
            resp = auth_client.get(self.URL)
        assert resp.status_code == 200
        # N=20 恰等於 page_size：單頁裝滿，斷言才不用管翻頁；要調大 N 先想分頁。
        assert len(resp.data['results']) == self.N


# --- 報表：即時餘額（balance/）與當日統計（today/）---


@pytest.mark.django_db
class TestReportBalance:
    URL = '/api/ledger/reports/balance/'

    def test_requires_authentication(self):
        assert APIClient().get(self.URL).status_code == 401

    def test_overview_sums_and_isolates(self, auth_client, user, other_user):
        Account.objects.create(
            user=user, name='現金', type=Account.Type.CASH, balance=Decimal('1000.00')
        )
        bank = Account.objects.create(
            user=user,
            name='銀行',
            type=Account.Type.BANK,
            balance=Decimal('25000.00'),
            is_default=True,
        )
        # 別人的帳戶不得混入總額或清單
        Account.objects.create(
            user=other_user, name='別人的', type=Account.Type.CASH, balance=Decimal('99999.00')
        )
        resp = auth_client.get(self.URL)
        assert resp.status_code == 200
        assert resp.data['total_balance'] == '26000.00'  # 1000 + 25000，金額為字串
        # 順序沿 Account 預設排序（-is_default, name）→ 預設帳戶在前
        assert resp.data['accounts'][0] == {
            'id': str(bank.id),
            'name': '銀行',
            'type': 'bank',
            'balance': '25000.00',
        }
        assert [row['name'] for row in resp.data['accounts']] == ['銀行', '現金']

    def test_no_accounts_returns_zero(self, auth_client, user):
        resp = auth_client.get(self.URL)
        assert resp.status_code == 200
        assert resp.data['total_balance'] == '0.00'
        assert resp.data['accounts'] == []

    def test_query_count_is_one(self, auth_client, user, django_assert_num_queries):
        for i in range(3):
            Account.objects.create(
                user=user, name=f'帳戶{i}', type=Account.Type.CASH, balance=Decimal('100.00')
            )
        with django_assert_num_queries(1):  # 一次取回全部帳戶、Python 端加總
            assert auth_client.get(self.URL).status_code == 200


@pytest.mark.django_db
class TestReportToday:
    URL = '/api/ledger/reports/today/'

    def test_requires_authentication(self):
        assert APIClient().get(self.URL).status_code == 401

    def test_counts_taipei_day_not_utc(self, auth_client, user):
        # 台北今日 00:30 == UTC 昨日 16:30：用 UTC 日界會漏算這兩筆 → 專證台北邊界。
        # 以 localtime(now) 造「今日」某時刻，跑在今日任何時點都歸今日、不 flaky。
        acc = Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
        now_local = timezone.localtime()
        today_0030 = now_local.replace(hour=0, minute=30, second=0, microsecond=0)
        yesterday_same = today_0030 - timedelta(days=1)
        Transaction.objects.create(
            user=user,
            account=acc,
            amount=Decimal('120.00'),
            type=Transaction.Type.EXPENSE,
            occurred_at=today_0030,
        )
        Transaction.objects.create(
            user=user,
            account=acc,
            amount=Decimal('500.00'),
            type=Transaction.Type.INCOME,
            occurred_at=today_0030,
        )
        # 昨天同一時刻的一筆：不得計入今日
        Transaction.objects.create(
            user=user,
            account=acc,
            amount=Decimal('999.00'),
            type=Transaction.Type.EXPENSE,
            occurred_at=yesterday_same,
        )
        resp = auth_client.get(self.URL)
        assert resp.status_code == 200
        assert resp.data['date'] == now_local.date().isoformat()
        assert resp.data['expense'] == '120.00'
        assert resp.data['income'] == '500.00'
        assert resp.data['net'] == '380.00'  # 500 − 120（收入減支出）

    def test_empty_day_returns_zeros(self, auth_client, user):
        resp = auth_client.get(self.URL)
        assert resp.status_code == 200
        assert resp.data['expense'] == '0.00'
        assert resp.data['income'] == '0.00'
        assert resp.data['net'] == '0.00'

    def test_query_count_is_one(self, auth_client, user, django_assert_num_queries):
        acc = Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
        for _ in range(3):  # occurred_at 預設 now() = 今日
            Transaction.objects.create(
                user=user, account=acc, amount=Decimal('10.00'), type=Transaction.Type.EXPENSE
            )
        with django_assert_num_queries(1):  # 單一條件聚合
            assert auth_client.get(self.URL).status_code == 200


# --- 報表：月度收支（summary/、by-category/、by-tag/）---


@pytest.mark.django_db
class TestReportSummary:
    SUMMARY = '/api/ledger/reports/summary/'
    BY_CATEGORY = '/api/ledger/reports/summary/by-category/'
    BY_TAG = '/api/ledger/reports/summary/by-tag/'

    @pytest.fixture
    def july(self, user):
        # 2026 七月（台北）的一組資料，含月界那筆：台北 7/1 00:30 == UTC 6/30 16:30。
        acc = Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
        food = Category.objects.create(user=user, name='飲食')
        salary = Category.objects.create(user=user, name='薪資')
        travel = Tag.objects.create(user=user, name='旅遊')
        work = Tag.objects.create(user=user, name='工作')
        # 月界：UTC 看是六月，台北看是七月 → 必須歸七月
        boundary = Transaction.objects.create(
            user=user,
            account=acc,
            category=food,
            amount=Decimal('100.00'),
            type=Transaction.Type.EXPENSE,
            occurred_at=datetime(2026, 6, 30, 16, 30, tzinfo=UTC),
        )
        boundary.tags.add(travel)
        # 七月收入（分類 薪資、無標籤）
        Transaction.objects.create(
            user=user,
            account=acc,
            category=salary,
            amount=Decimal('5000.00'),
            type=Transaction.Type.INCOME,
            occurred_at=datetime(2026, 7, 10, 2, 0, tzinfo=UTC),  # 台北 7/10 10:00
        )
        # 七月支出（未分類、掛兩標籤）
        multi = Transaction.objects.create(
            user=user,
            account=acc,
            category=None,
            amount=Decimal('300.00'),
            type=Transaction.Type.EXPENSE,
            occurred_at=datetime(2026, 7, 15, 5, 0, tzinfo=UTC),
        )
        multi.tags.add(travel, work)
        # 六月一筆（台北 6/15）：不得進七月
        Transaction.objects.create(
            user=user,
            account=acc,
            category=food,
            amount=Decimal('999.00'),
            type=Transaction.Type.EXPENSE,
            occurred_at=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
        )
        return {'travel': travel, 'work': work}

    def test_requires_authentication(self):
        assert APIClient().get(self.SUMMARY).status_code == 401

    def test_specified_month(self, auth_client, july):
        resp = auth_client.get(self.SUMMARY, {'year': 2026, 'month': 7})
        assert resp.status_code == 200
        # income 5000；expense 100（邊界）+ 300 = 400；net 4600。六月的 999 不算。
        assert resp.data == {
            'year': 2026,
            'month': 7,
            'income': '5000.00',
            'expense': '400.00',
            'net': '4600.00',
        }

    def test_taipei_month_boundary(self, auth_client, july):
        # 邊界那筆歸七月、不歸六月
        june = auth_client.get(self.SUMMARY, {'year': 2026, 'month': 6})
        assert june.data['expense'] == '999.00'  # 只有那筆六月支出
        july_resp = auth_client.get(self.SUMMARY, {'year': 2026, 'month': 7})
        assert july_resp.data['expense'] == '400.00'  # 含邊界 100、不含 999

    def test_defaults_to_current_taipei_month(self, auth_client, user):
        acc = Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
        now_local = timezone.localtime()
        Transaction.objects.create(  # occurred_at 預設 now() = 當月
            user=user, account=acc, amount=Decimal('42.00'), type=Transaction.Type.EXPENSE
        )
        resp = auth_client.get(self.SUMMARY)
        assert resp.status_code == 200
        assert resp.data['year'] == now_local.year
        assert resp.data['month'] == now_local.month
        assert resp.data['expense'] == '42.00'

    def test_empty_month_zeros(self, auth_client, user):
        resp = auth_client.get(self.SUMMARY, {'year': 2020, 'month': 1})
        assert resp.status_code == 200
        assert resp.data == {
            'year': 2020,
            'month': 1,
            'income': '0.00',
            'expense': '0.00',
            'net': '0.00',
        }

    def test_invalid_params_return_400(self, auth_client, user):
        assert auth_client.get(self.SUMMARY, {'year': 2026, 'month': 13}).status_code == 400
        assert auth_client.get(self.SUMMARY, {'month': 0}).status_code == 400
        assert auth_client.get(self.SUMMARY, {'year': 'abc'}).status_code == 400
        assert auth_client.get(self.SUMMARY, {'year': 10000}).status_code == 400

    def test_by_category_buckets_and_clean_sum(self, auth_client, july):
        resp = auth_client.get(self.BY_CATEGORY, {'year': 2026, 'month': 7})
        assert resp.status_code == 200
        cats = resp.data['categories']
        by_name = {c['category_name']: c for c in cats}
        assert by_name['飲食']['expense'] == '100.00'
        assert by_name['飲食']['income'] == '0.00'
        assert by_name['薪資']['income'] == '5000.00'
        assert by_name['薪資']['expense'] == '0.00'
        # 未分類桶：category_id / category_name 皆 null
        uncat = next(c for c in cats if c['category_id'] is None)
        assert uncat['category_name'] is None
        assert uncat['expense'] == '300.00'
        assert cats[0]['category_id'] is None  # expense 300 最高 → 降冪排最前
        # 乾淨加總不變式：各桶加總 == summary 總額（單值 FK，不重疊）
        summary = auth_client.get(self.SUMMARY, {'year': 2026, 'month': 7}).data
        assert str(sum(Decimal(c['income']) for c in cats)) == summary['income']
        assert str(sum(Decimal(c['expense']) for c in cats)) == summary['expense']

    def test_by_tag_overlaps_and_untagged_absent(self, auth_client, july):
        resp = auth_client.get(self.BY_TAG, {'year': 2026, 'month': 7})
        assert resp.status_code == 200
        tags = {t['tag_name']: t for t in resp.data['tags']}
        # 旅遊掛 boundary(100)+multi(300) → 400；工作只掛 multi(300)
        assert tags['旅遊']['expense'] == '400.00'
        assert tags['工作']['expense'] == '300.00'
        # 無標籤的薪資那筆不出現；旅遊+工作合計 700 > summary 400（重疊維度不可加總）
        assert set(tags) == {'旅遊', '工作'}

    def test_query_counts_are_one_each(self, auth_client, july, django_assert_num_queries):
        params = {'year': 2026, 'month': 7}
        with django_assert_num_queries(1):
            auth_client.get(self.SUMMARY, params)
        with django_assert_num_queries(1):
            auth_client.get(self.BY_CATEGORY, params)
        with django_assert_num_queries(1):
            auth_client.get(self.BY_TAG, params)


# --- 報表：逐月餘額歷史（balance-history/，TruncMonth＋running sum＋forward-fill）---


@pytest.mark.django_db
class TestReportBalanceHistory:
    URL = '/api/ledger/reports/balance-history/'
    TXN = '/api/ledger/transactions/'

    def _post(self, client, acc, amount, type_, occurred_at):
        # 走 API 建交易 → services 維護 Account.balance（供末月不變式對帳）
        resp = client.post(
            self.TXN,
            {
                'account': str(acc.id),
                'amount': amount,
                'type': type_,
                'occurred_at': occurred_at,
            },
            format='json',
        )
        assert resp.status_code == 201
        return resp

    def test_requires_authentication(self):
        assert APIClient().get(self.URL).status_code == 401

    def test_running_sum_forward_fill_and_invariant(self, auth_client, user):
        acc = Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
        # 五月 +100 收入、七月 −30 支出（六月無交易 → 缺月）。UTC 時刻選在台北同月內。
        self._post(auth_client, acc, '100.00', 'income', '2026-05-10T02:00:00Z')
        self._post(auth_client, acc, '30.00', 'expense', '2026-07-15T05:00:00Z')
        resp = auth_client.get(self.URL)
        assert resp.status_code == 200
        entry = next(e for e in resp.data if e['account_id'] == str(acc.id))
        months = {mo['month']: mo['balance'] for mo in entry['months']}
        assert months['2026-05'] == '100.00'
        assert months['2026-06'] == '100.00'  # 缺月 forward-fill：沿用五月餘額
        assert months['2026-07'] == '70.00'  # 100 − 30
        # 不變式：最後一月餘額 == Account.balance 現值
        acc.refresh_from_db()
        assert acc.balance == Decimal('70.00')
        assert Decimal(entry['months'][-1]['balance']) == acc.balance

    def test_taipei_month_boundary(self, auth_client, user):
        acc = Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
        # 台北 7/1 00:30 == UTC 6/30 16:30：TruncMonth 應歸七月、不歸六月
        self._post(auth_client, acc, '100.00', 'income', '2026-06-30T16:30:00Z')
        resp = auth_client.get(self.URL)
        entry = next(e for e in resp.data if e['account_id'] == str(acc.id))
        assert entry['months'][0]['month'] == '2026-07'  # 首月＝七月（非六月）
        months = {mo['month']: mo['balance'] for mo in entry['months']}
        assert months['2026-07'] == '100.00'

    def test_account_without_transactions_has_empty_months(self, auth_client, user):
        Account.objects.create(user=user, name='空帳戶', type=Account.Type.CASH)
        resp = auth_client.get(self.URL)
        entry = next(e for e in resp.data if e['account_name'] == '空帳戶')
        assert entry['months'] == []

    def test_isolation(self, auth_client, user, other_user):
        Account.objects.create(user=other_user, name='別人的', type=Account.Type.CASH)
        mine = Account.objects.create(user=user, name='我的', type=Account.Type.CASH)
        resp = auth_client.get(self.URL)
        assert str(mine.id) in {e['account_id'] for e in resp.data}
        assert all(e['account_name'] != '別人的' for e in resp.data)

    def test_query_count_is_two(self, auth_client, user, django_assert_num_queries):
        acc = Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
        for month in (5, 6, 7):
            self._post(auth_client, acc, '10.00', 'expense', f'2026-{month:02d}-15T05:00:00Z')
        with django_assert_num_queries(2):  # 帳戶清單 + 每月淨變化聚合（與筆數／月份數無關）
            assert auth_client.get(self.URL).status_code == 200


# --- 報表：balance-history 快取（cache-aside + 交易寫入後 on_commit 失效）---


@pytest.mark.django_db
class TestBalanceHistoryCache:
    URL = '/api/ledger/reports/balance-history/'
    TXN = '/api/ledger/transactions/'

    def _post_income(self, client, acc, amount, capture):
        # 走 API 建交易 → 觸發 perform_create 的 on_commit 失效；capture 讓 callback 在
        # 測試交易（會 rollback、on_commit 平時不觸發）內實際執行。
        with capture(execute=True):
            resp = client.post(
                self.TXN,
                {
                    'account': str(acc.id),
                    'amount': amount,
                    'type': 'income',
                    'occurred_at': '2026-05-10T02:00:00Z',
                },
                format='json',
            )
        assert resp.status_code == 201
        return resp

    def test_warm_read_served_from_cache_without_queries(
        self, auth_client, user, django_assert_num_queries
    ):
        acc = Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
        Transaction.objects.create(
            user=user,
            account=acc,
            amount=Decimal('100.00'),
            type=Transaction.Type.INCOME,
            occurred_at=datetime(2026, 5, 10, 2, 0, tzinfo=UTC),
        )
        with django_assert_num_queries(2):  # 冷讀：帳戶清單 + 每月淨變化聚合
            cold = auth_client.get(self.URL)
        with django_assert_num_queries(0):  # 暖讀：整份回應來自快取，零 DB 查詢
            warm = auth_client.get(self.URL)
        assert warm.status_code == 200
        assert warm.data == cold.data

    def test_warm_cache_is_isolated_per_user(self, auth_client, user, other_user):
        # user 先暖好自己的快取；other_user 的讀取不得拿到 user 的資料（key 帶 user pk）。
        Account.objects.create(user=user, name='我的', type=Account.Type.CASH)
        auth_client.get(self.URL)
        Account.objects.create(user=other_user, name='別人的', type=Account.Type.CASH)
        other_client = APIClient()
        other_client.force_authenticate(user=other_user)
        resp = other_client.get(self.URL)
        names = {e['account_name'] for e in resp.data}
        assert '別人的' in names
        assert '我的' not in names  # key 若非 per-user，這裡會漏出 user 的暖快取

    def test_create_transaction_invalidates_cache(
        self, auth_client, user, django_capture_on_commit_callbacks, django_assert_num_queries
    ):
        acc = Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
        warm = auth_client.get(self.URL)  # 暖快取：此帳戶尚無交易 → months 空
        assert next(e for e in warm.data if e['account_id'] == str(acc.id))['months'] == []
        self._post_income(auth_client, acc, '100.00', django_capture_on_commit_callbacks)
        with django_assert_num_queries(2):  # 失效後重新冷讀（非回舊快取）
            after = auth_client.get(self.URL)
        entry = next(e for e in after.data if e['account_id'] == str(acc.id))
        assert entry['months'][-1]['balance'] == '100.00'  # 新交易已反映

    def test_update_transaction_invalidates_cache(
        self, auth_client, user, django_capture_on_commit_callbacks
    ):
        acc = Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
        resp = self._post_income(auth_client, acc, '100.00', django_capture_on_commit_callbacks)
        txn_id = resp.data['id']
        auth_client.get(self.URL)  # 暖快取：末月餘額 100
        with django_capture_on_commit_callbacks(execute=True):
            upd = auth_client.patch(f'{self.TXN}{txn_id}/', {'amount': '250.00'}, format='json')
        assert upd.status_code == 200
        after = auth_client.get(self.URL)
        entry = next(e for e in after.data if e['account_id'] == str(acc.id))
        assert entry['months'][-1]['balance'] == '250.00'  # 改額已反映（非舊快取 100）

    def test_delete_transaction_invalidates_cache(
        self, auth_client, user, django_capture_on_commit_callbacks
    ):
        acc = Account.objects.create(user=user, name='現金', type=Account.Type.CASH)
        resp = self._post_income(auth_client, acc, '100.00', django_capture_on_commit_callbacks)
        txn_id = resp.data['id']
        auth_client.get(self.URL)  # 暖快取：末月餘額 100
        with django_capture_on_commit_callbacks(execute=True):
            dele = auth_client.delete(f'{self.TXN}{txn_id}/')
        assert dele.status_code == 204
        after = auth_client.get(self.URL)
        entry = next(e for e in after.data if e['account_id'] == str(acc.id))
        assert entry['months'] == []  # 交易刪光 → 空 months（非舊快取）


# --- 報表：儲蓄目標達成狀態（savings-goal-status/，月度／年度雙態）---


@pytest.mark.django_db
class TestReportSavingsGoalStatus:
    URL = '/api/ledger/reports/savings-goal-status/'

    def _account(self, user):
        return Account.objects.create(user=user, name='現金', type=Account.Type.CASH)

    def _txn(self, user, acc, amount, type_, occurred_at):
        Transaction.objects.create(
            user=user, account=acc, amount=Decimal(amount), type=type_, occurred_at=occurred_at
        )

    def test_requires_authentication(self):
        assert APIClient().get(self.URL).status_code == 401

    def test_monthly_achieved(self, auth_client, user):
        acc = self._account(user)
        SavingsGoal.objects.create(
            user=user,
            period_type=SavingsGoal.PeriodType.MONTHLY,
            year=2026,
            month=7,
            amount=Decimal('10000.00'),
        )
        # 七月 net = 50000 − 38000 = 12000 >= 10000 → 達成、difference 正
        self._txn(
            user, acc, '50000.00', Transaction.Type.INCOME, datetime(2026, 7, 10, 2, 0, tzinfo=UTC)
        )
        self._txn(
            user, acc, '38000.00', Transaction.Type.EXPENSE, datetime(2026, 7, 20, 2, 0, tzinfo=UTC)
        )
        resp = auth_client.get(self.URL, {'year': 2026, 'month': 7})
        assert resp.status_code == 200
        assert resp.data['period_type'] == 'monthly'
        assert resp.data['year'] == 2026
        assert resp.data['month'] == 7
        assert resp.data['goal_amount'] == '10000.00'
        assert resp.data['actual_net'] == '12000.00'
        assert resp.data['difference'] == '2000.00'  # actual − goal
        assert resp.data['achieved'] is True

    def test_monthly_not_achieved(self, auth_client, user):
        acc = self._account(user)
        SavingsGoal.objects.create(
            user=user,
            period_type=SavingsGoal.PeriodType.MONTHLY,
            year=2026,
            month=7,
            amount=Decimal('10000.00'),
        )
        # net = 5000 − 3000 = 2000 < 10000 → 未達成、difference 負
        self._txn(
            user, acc, '5000.00', Transaction.Type.INCOME, datetime(2026, 7, 10, 2, 0, tzinfo=UTC)
        )
        self._txn(
            user, acc, '3000.00', Transaction.Type.EXPENSE, datetime(2026, 7, 12, 2, 0, tzinfo=UTC)
        )
        resp = auth_client.get(self.URL, {'year': 2026, 'month': 7})
        assert resp.data['actual_net'] == '2000.00'
        assert resp.data['difference'] == '-8000.00'
        assert resp.data['achieved'] is False

    def test_goal_unset_returns_null_but_net_computed(self, auth_client, user):
        acc = self._account(user)
        self._txn(
            user, acc, '5000.00', Transaction.Type.INCOME, datetime(2026, 7, 10, 2, 0, tzinfo=UTC)
        )
        self._txn(
            user, acc, '2000.00', Transaction.Type.EXPENSE, datetime(2026, 7, 12, 2, 0, tzinfo=UTC)
        )
        resp = auth_client.get(self.URL, {'year': 2026, 'month': 7})
        assert resp.status_code == 200
        # 未設目標是正常狀態（前端要顯示它）→ 不 404，goal 相關欄位 null
        assert resp.data['goal_amount'] is None
        assert resp.data['difference'] is None
        assert resp.data['achieved'] is None
        assert resp.data['actual_net'] == '3000.00'  # actual_net 仍照算

    def test_yearly_when_month_omitted(self, auth_client, user):
        acc = self._account(user)
        SavingsGoal.objects.create(
            user=user,
            period_type=SavingsGoal.PeriodType.YEARLY,
            year=2026,
            month=None,
            amount=Decimal('100000.00'),
        )
        # 全年跨兩月 net = (50000 + 30000) − 10000 = 70000 < 100000 → 未達成
        self._txn(
            user, acc, '50000.00', Transaction.Type.INCOME, datetime(2026, 3, 10, 2, 0, tzinfo=UTC)
        )
        self._txn(
            user, acc, '10000.00', Transaction.Type.EXPENSE, datetime(2026, 3, 15, 2, 0, tzinfo=UTC)
        )
        self._txn(
            user, acc, '30000.00', Transaction.Type.INCOME, datetime(2026, 9, 10, 2, 0, tzinfo=UTC)
        )
        resp = auth_client.get(self.URL, {'year': 2026})  # 省略 month → 年度
        assert resp.status_code == 200
        assert resp.data['period_type'] == 'yearly'
        assert resp.data['month'] is None
        assert resp.data['goal_amount'] == '100000.00'
        assert resp.data['actual_net'] == '70000.00'
        assert resp.data['difference'] == '-30000.00'
        assert resp.data['achieved'] is False

    def test_query_count_is_two(self, auth_client, user, django_assert_num_queries):
        acc = self._account(user)
        SavingsGoal.objects.create(
            user=user,
            period_type=SavingsGoal.PeriodType.MONTHLY,
            year=2026,
            month=7,
            amount=Decimal('10000.00'),
        )
        self._txn(
            user, acc, '5000.00', Transaction.Type.INCOME, datetime(2026, 7, 10, 2, 0, tzinfo=UTC)
        )
        with django_assert_num_queries(2):  # goal lookup + 期間淨額聚合
            assert auth_client.get(self.URL, {'year': 2026, 'month': 7}).status_code == 200


# --- 報表：任意日期區間收支（summary/range/，含當日、當前時區半開區間）---


@pytest.mark.django_db
class TestReportRangeSummary:
    URL = '/api/ledger/reports/summary/range/'
    TODAY = '/api/ledger/reports/today/'

    def _account(self, user):
        return Account.objects.create(user=user, name='現金', type=Account.Type.CASH)

    def _txn(self, user, acc, amount, type_, occurred_at):
        Transaction.objects.create(
            user=user, account=acc, amount=Decimal(amount), type=type_, occurred_at=occurred_at
        )

    def test_requires_authentication(self):
        assert APIClient().get(self.URL).status_code == 401

    def test_sum_and_taipei_boundaries(self, auth_client, user):
        # 區間 [7/1, 7/31] 台北 → 內部半開 [台北 7/1 00:00, 8/1 00:00)。一次蓋：加總正確 +
        # start 當日界含 + end 當日深夜界含 + end+1 凌晨不含 + start 前一日不含。
        acc = self._account(user)
        # 含：台北 7/1 00:30（UTC 6/30 16:30）——start 當日界內
        self._txn(
            user, acc, '10.00', Transaction.Type.INCOME, datetime(2026, 6, 30, 16, 30, tzinfo=UTC)
        )
        # 含：台北 7/31 23:59（UTC 7/31 15:59）——end 當日深夜仍算進來
        self._txn(
            user, acc, '20.00', Transaction.Type.INCOME, datetime(2026, 7, 31, 15, 59, tzinfo=UTC)
        )
        # 不含：台北 8/1 00:30（UTC 7/31 16:30）——越過 end+1 排除界
        self._txn(
            user, acc, '999.00', Transaction.Type.INCOME, datetime(2026, 7, 31, 16, 30, tzinfo=UTC)
        )
        # 不含：台北 6/30 23:00（UTC 6/30 15:00）——start 前一日
        self._txn(
            user, acc, '888.00', Transaction.Type.EXPENSE, datetime(2026, 6, 30, 15, 0, tzinfo=UTC)
        )
        resp = auth_client.get(self.URL, {'start': '2026-07-01', 'end': '2026-07-31'})
        assert resp.status_code == 200
        assert resp.data == {
            'start': '2026-07-01',
            'end': '2026-07-31',
            'income': '30.00',  # 10 + 20，兩筆界外不算
            'expense': '0.00',
            'net': '30.00',
        }

    def test_single_day_range_matches_today(self, auth_client, user):
        # 不變式：start==end 單日區間，收支數字 == today/ 同日值（信封不同：start/end vs date）。
        acc = self._account(user)
        now_local = timezone.localtime()
        today_0030 = now_local.replace(hour=0, minute=30, second=0, microsecond=0)
        self._txn(user, acc, '120.00', Transaction.Type.EXPENSE, today_0030)
        self._txn(user, acc, '500.00', Transaction.Type.INCOME, today_0030)
        today_data = auth_client.get(self.TODAY).data
        today = now_local.date().isoformat()
        resp = auth_client.get(self.URL, {'start': today, 'end': today})
        assert resp.status_code == 200
        assert (resp.data['income'], resp.data['expense'], resp.data['net']) == (
            today_data['income'],
            today_data['expense'],
            today_data['net'],
        )

    def test_empty_range_zeros(self, auth_client, user):
        resp = auth_client.get(self.URL, {'start': '2020-01-01', 'end': '2020-01-31'})
        assert resp.status_code == 200
        assert resp.data == {
            'start': '2020-01-01',
            'end': '2020-01-31',
            'income': '0.00',
            'expense': '0.00',
            'net': '0.00',
        }

    def test_isolation(self, auth_client, user, other_user):
        other_acc = Account.objects.create(user=other_user, name='別人的', type=Account.Type.CASH)
        self._txn(
            other_user,
            other_acc,
            '999.00',
            Transaction.Type.INCOME,
            datetime(2026, 7, 10, 2, 0, tzinfo=UTC),
        )
        resp = auth_client.get(self.URL, {'start': '2026-07-01', 'end': '2026-07-31'})
        assert resp.status_code == 200
        assert resp.data['income'] == '0.00'  # 別人的交易不混入

    def test_missing_param_returns_400(self, auth_client, user):
        assert auth_client.get(self.URL, {'end': '2026-07-31'}).status_code == 400
        assert auth_client.get(self.URL, {'start': '2026-07-01'}).status_code == 400
        assert auth_client.get(self.URL).status_code == 400

    def test_malformed_date_returns_400(self, auth_client, user):
        # 鎖 %Y-%m-%d：錯分隔符 / 無分隔一律 400（fromisoformat 會誤收 '20260701'，故不用它）
        for bad in ('2026/07/01', '20260701'):
            resp = auth_client.get(self.URL, {'start': bad, 'end': '2026-07-31'})
            assert resp.status_code == 400, bad

    def test_start_after_end_returns_400(self, auth_client, user):
        resp = auth_client.get(self.URL, {'start': '2026-07-31', 'end': '2026-07-01'})
        assert resp.status_code == 400

    def test_query_count_is_one(self, auth_client, user, django_assert_num_queries):
        acc = self._account(user)
        for _ in range(3):
            self._txn(
                user,
                acc,
                '10.00',
                Transaction.Type.EXPENSE,
                datetime(2026, 7, 15, 5, 0, tzinfo=UTC),
            )
        params = {'start': '2026-07-01', 'end': '2026-07-31'}
        with django_assert_num_queries(1):  # 單一條件聚合，與筆數無關
            assert auth_client.get(self.URL, params).status_code == 200


# --- 報表：全端點未授權掃描（8 支迴圈打 → 皆 401）---


@pytest.mark.django_db
def test_all_report_endpoints_require_authentication():
    client = APIClient()
    paths = [
        '/api/ledger/reports/balance/',
        '/api/ledger/reports/today/',
        '/api/ledger/reports/summary/',
        '/api/ledger/reports/summary/by-category/',
        '/api/ledger/reports/summary/by-tag/',
        '/api/ledger/reports/balance-history/',
        '/api/ledger/reports/savings-goal-status/',
        '/api/ledger/reports/summary/range/',
    ]
    for path in paths:
        assert client.get(path).status_code == 401, path


@pytest.mark.django_db
class TestOpenAPISchema:
    """schema／docs 端點與 schema 品質看守。

    兩支端點刻意匿名可讀（schema 是對外契約、不含業務資料），因此不進上面的 401 掃描；
    validate 包成測試＝不動 CI 設定就有 schema 規格閘門。
    """

    def test_schema_endpoint_public(self):
        assert APIClient().get('/api/schema/').status_code == 200

    def test_docs_page_public(self):
        assert APIClient().get('/api/docs/').status_code == 200

    def test_schema_covers_all_api_surfaces(self):
        # 抽查三個來源各一段：核心繼承（auth）、router CRUD、報表 @action——
        # 任何一塊從 schema 消失（URLconf 改壞、decorator 蓋掉 action）都會在這裡現形。
        paths = SchemaGenerator().get_schema(request=None, public=True)['paths']
        for sample in (
            '/api/auth/login/',
            '/api/ledger/transactions/',
            '/api/ledger/recurring-rules/',
            '/api/ledger/reports/summary/range/',
            '/api/ledger/reports/balance-history/',
        ):
            assert sample in paths, sample

    def test_schema_passes_spectacular_validation(self):
        # --validate 在產出當下跑 OpenAPI 規格檢查，違規直接拋錯；stdout 吞掉不吐整份 schema。
        call_command('spectacular', '--validate', stdout=io.StringIO())

    def test_write_operations_expose_request_body(self):
        # 回歸看守：schema 產生器的假 request 帶 AnonymousUser（不是 None）——serializer
        # 或 get_queryset 拿它過濾 UUID 外鍵會炸，spectacular 只降級成警告、整個 view 的
        # 推導被安靜丟棄，症狀是文件頁 Try it out 沒有 request body。五資源 POST 必帶 body。
        paths = SchemaGenerator().get_schema(request=None, public=True)['paths']
        for resource in (
            'accounts',
            'categories',
            'tags',
            'transactions',
            'savings-goals',
            'recurring-rules',
        ):
            assert 'requestBody' in paths[f'/api/ledger/{resource}/']['post'], resource

    def test_account_type_enum_named_stably(self):
        # Account.Type 出現在 CRUD 與報表兩個 component，enum 撞名時 spectacular 會退化成
        # 雜湊尾名（Type346Enum 之類）——名字不穩，下游型別產生器每次生出不同識別字。
        # ENUM_NAME_OVERRIDES 釘住後，這裡看守它一直在。
        comps = SchemaGenerator().get_schema(request=None, public=True)['components']['schemas']
        assert 'AccountTypeEnum' in comps

    def test_transaction_type_enum_named_stably(self):
        # income/expense 這組 choices 由交易與定期定額規則共用，欄位都叫 type，與
        # Account.Type 撞名 → 未釘名時退化成雜湊尾名（TypeB16Enum）。兩個 component
        # 共用同一個 enum 是對的，名字必須穩定。
        comps = SchemaGenerator().get_schema(request=None, public=True)['components']['schemas']
        assert 'TransactionTypeEnum' in comps

    def test_report_money_fields_are_strings(self):
        # 報表金額在 schema 必須是 string(decimal)：client 拿 schema 生型別，
        # 標成 number 等於邀請浮點解析。抽查三個代表 component 的金額欄位。
        components = SchemaGenerator().get_schema(request=None, public=True)['components'][
            'schemas'
        ]
        for component, field in (
            ('BalanceOverview', 'total_balance'),
            ('MonthSummary', 'net'),
            ('SavingsGoalStatus', 'actual_net'),
        ):
            prop = components[component]['properties'][field]
            assert prop['type'] == 'string', (component, field)
            assert prop['format'] == 'decimal', (component, field)

    def test_frozen_contract_matches_generated_schema(self):
        # 契約凍結看守：repo 根 openapi.yaml 是對前端凍結的契約落檔（下游拿它生型別）。
        # 動到 API 形狀的任何變更都會在這裡紅——刻意變更的儀式是重新 export＋依 SemVer
        # 升版（只加不改=minor、破壞形狀=major）：
        #   docker compose exec --user root web \
        #     python manage.py spectacular --validate --file /app/openapi.yaml
        # 語意比對（parse 後結構相等）而非 byte 比對：換行/縮排差異不算漂移。
        frozen = yaml.safe_load(
            (Path(settings.BASE_DIR) / 'openapi.yaml').read_text(encoding='utf-8')
        )
        generated = SchemaGenerator().get_schema(request=None, public=True)
        assert generated == frozen, 'openapi.yaml 落後於現行 schema——用上方指令重新 export'

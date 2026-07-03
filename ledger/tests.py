"""DB 層約束的最小 smoke：證明約束真的在資料庫擋下髒資料。

每個違規寫入都包在 `transaction.atomic()` 裡——IntegrityError 會弄髒外層測試交易，
用 savepoint 框住才不會讓同一測試的後續 ORM 操作炸掉。複用 conftest 的 `user` fixture。
"""

import threading
from datetime import UTC, datetime
from decimal import Decimal
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
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from ledger import services
from ledger.models import Account, Category, SavingsGoal, Tag, Transaction
from ledger.serializers import TransactionSerializer


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

    def test_tag(self, auth_client, data):
        resp = auth_client.get(self.URL, {'tag': str(data['travel'].id)})
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

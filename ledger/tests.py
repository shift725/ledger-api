"""DB 層約束的最小 smoke：證明約束真的在資料庫擋下髒資料。

每個違規寫入都包在 `transaction.atomic()` 裡——IntegrityError 會弄髒外層測試交易，
用 savepoint 框住才不會讓同一測試的後續 ORM 操作炸掉。複用 conftest 的 `user` fixture。
"""

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from ledger.models import Account, Category, SavingsGoal, Tag, Transaction


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
        assert [row['name'] for row in resp.data] == ['我的']

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

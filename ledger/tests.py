"""DB 層約束的最小 smoke：證明約束真的在資料庫擋下髒資料。

每個違規寫入都包在 `transaction.atomic()` 裡——IntegrityError 會弄髒外層測試交易，
用 savepoint 框住才不會讓同一測試的後續 ORM 操作炸掉。複用 conftest 的 `user` fixture。
"""

from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

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

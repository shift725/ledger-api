from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from accounts.models import UUIDv7Mixin


class TimeStampedModel(UUIDv7Mixin):
    """業務 model 共用基底：UUIDv7 主鍵（繼承自 UUIDv7Mixin）＋ 建檔／更新時間。

    UUIDv7Mixin 只提供 id；created_at/updated_at 由本類別補上，五個 ledger model 共用。
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Account(TimeStampedModel):
    """資金帳戶（現金／銀行／信用卡…）。balance 為衍生快取，由交易維護。"""

    class Type(models.TextChoices):
        CASH = 'cash', '現金'
        BANK = 'bank', '銀行'
        CREDIT_CARD = 'credit_card', '信用卡'
        E_WALLET = 'e_wallet', '電子錢包'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='accounts'
    )
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=20, choices=Type.choices)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ['-is_default', 'name']
        constraints = [
            models.UniqueConstraint(fields=['user', 'name'], name='uniq_account_name_per_user'),
            models.UniqueConstraint(
                fields=['user'],
                condition=models.Q(is_default=True),
                name='uniq_default_account_per_user',
            ),
        ]

    def __str__(self):
        return self.name


class Category(TimeStampedModel):
    """互斥主分類（單值 FK、選填）；報表加總乾淨等於總額。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='categories'
    )
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['user', 'name'], name='uniq_category_name_per_user'),
        ]

    def __str__(self):
        return self.name


class Tag(TimeStampedModel):
    """可疊加的橫切標記（M2M）；總額不可由各標籤加總（會重複計算）。"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tags'
    )
    name = models.CharField(max_length=50)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['user', 'name'], name='uniq_tag_name_per_user'),
        ]

    def __str__(self):
        return self.name


class Transaction(TimeStampedModel):
    """交易／帳目（核心）。amount 恆正，方向由 type 決定。"""

    class Type(models.TextChoices):
        INCOME = 'income', '收入'
        EXPENSE = 'expense', '支出'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='transactions'
    )
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='transactions')
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions',
    )
    amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))]
    )
    type = models.CharField(max_length=10, choices=Type.choices)
    name = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)
    tags = models.ManyToManyField(Tag, blank=True, related_name='transactions')

    class Meta:
        ordering = ['-occurred_at', '-created_at']
        indexes = [
            models.Index(fields=['user', 'occurred_at'], name='idx_txn_user_occurred'),
        ]

    def __str__(self):
        return f'{self.name or self.get_type_display()}: {self.amount}'


class SavingsGoal(TimeStampedModel):
    """儲蓄目標（單表，年／月由 period_type 區分）。"""

    class PeriodType(models.TextChoices):
        MONTHLY = 'monthly', '月度'
        YEARLY = 'yearly', '年度'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='savings_goals'
    )
    period_type = models.CharField(max_length=10, choices=PeriodType.choices)
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField(null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ['-year', '-month']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'period_type', 'year', 'month'],
                nulls_distinct=False,
                name='uniq_savings_goal_period',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(period_type='monthly', month__gte=1, month__lte=12)
                    | models.Q(period_type='yearly', month__isnull=True)
                ),
                name='ck_savings_goal_month_matches_type',
            ),
        ]

    def __str__(self):
        period = self.month if self.period_type == self.PeriodType.MONTHLY else '全年'
        return f'{self.get_period_type_display()} {self.year}-{period}: {self.amount}'

import calendar
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
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
    # 跨帳戶轉帳（轉帳、領現金）的兩腿標記：排除在收支統計外（非真實收支），
    # 但仍影響帳戶餘額與餘額走勢（錢確實在帳戶間移動）。
    is_transfer = models.BooleanField(default=False)
    tags = models.ManyToManyField(Tag, blank=True, related_name='transactions')
    # 由定期定額規則自動產生時回填；規則刪除後交易保留（帳務事實不因規則消失而改變）。
    source_rule = models.ForeignKey(
        'RecurringRule',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions',
    )

    class Meta:
        ordering = ['-occurred_at', '-created_at']
        indexes = [
            models.Index(fields=['user', 'occurred_at'], name='idx_txn_user_occurred'),
        ]
        constraints = [
            # 自動記帳的冪等保證：一條規則的同一個到期日最多一筆交易。重複投遞、並發 worker、
            # 任務重試都撞在這條索引上，不必在應用層上鎖（鎖只保護記得上鎖的路徑，約束保護全部）。
            # 手動交易的 source_rule 是 NULL，PostgreSQL 預設 NULL 互不相等 → 完全不受此約束限制。
            models.UniqueConstraint(
                fields=['source_rule', 'occurred_at'], name='uniq_txn_per_rule_occurrence'
            ),
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


def next_due(day_of_month, on_or_after):
    """算出第一個不早於 on_or_after 的到期日；短月把日期收到當月最後一天。

    每月 31 號的規則在 2 月落在 28（閏年 29）號——訂閱計費的通行語意。收窄只影響該月，
    下一期一律拿原始 day_of_month 重算，故不會逐月往前漂移。
    規則建立（起算日＝今天）與任務推進下一期（起算日＝本期到期日的隔天）共用這一份語意。
    """

    def clamped(year, month):
        return date(year, month, min(day_of_month, calendar.monthrange(year, month)[1]))

    year, month = on_or_after.year, on_or_after.month
    if clamped(year, month) < on_or_after:
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return clamped(year, month)


class RecurringRule(TimeStampedModel):
    """定期定額規則：每月固定一天自動產生一筆交易（房租、薪水、訂閱）。

    next_run_date 是游標——讓每日任務只撈得出到期的規則，不必每晚重算所有規則的全部歷史。
    它不是正確性機制：「一條規則的同一到期日只有一筆交易」由 Transaction 的
    uniq_txn_per_rule_occurrence 唯一約束保證，游標被重複推進或推進失敗都不會造成重複記帳。
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='recurring_rules'
    )
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='recurring_rules')
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recurring_rules',
    )
    amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))]
    )
    # 與 Transaction 同一組 choices：規則產出的就是交易，方向語意不該有第二套定義。
    type = models.CharField(max_length=10, choices=Transaction.Type.choices)
    name = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    day_of_month = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(31)]
    )
    is_active = models.BooleanField(default=True)
    next_run_date = models.DateField()

    class Meta:
        ordering = ['day_of_month', '-created_at']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(day_of_month__gte=1, day_of_month__lte=31),
                name='ck_recurring_rule_day_of_month',
            ),
        ]

    def __str__(self):
        return f'{self.name or self.get_type_display()}: 每月 {self.day_of_month} 號 {self.amount}'

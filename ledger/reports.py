"""報表聚合：純函式吃 user，全在 DB 端聚合，view 只驗參數並包成回應。

金額一律 str()——DRF 的 JSONEncoder 對裸 Decimal 會轉 float、丟精度與尾零；聚合掛
Coalesce(Value(0.00)) 讓空集合回 "0.00" 而非 null，並保住 scale=2。時區邊界一律走
current timezone（settings.TIME_ZONE）、不寫死時區字串。
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone

from .models import Account, SavingsGoal, Transaction

# 金額欄位型別統一：Coalesce 的 fallback 與聚合輸出都綁 (12,2)，回傳字串格式穩定。
_MONEY = DecimalField(max_digits=12, decimal_places=2)
_ZERO = Value(Decimal('0.00'), output_field=_MONEY)


def _sum_amount(txn_type):
    """指定類型的金額加總；空集合回 0.00（Coalesce 保 scale）。"""
    return Coalesce(Sum('amount', filter=Q(type=txn_type)), _ZERO, output_field=_MONEY)


def balance_overview(user):
    """所有帳戶總餘額＋各帳戶餘額（首頁顯眼位置用）。1 查詢取回帳戶、Python 端加總。"""
    accounts = list(Account.objects.filter(user=user))  # 順序沿 Account.Meta.ordering
    total = sum((a.balance for a in accounts), Decimal('0.00'))
    return {
        'total_balance': str(total),
        'accounts': [
            {'id': str(a.id), 'name': a.name, 'type': a.type, 'balance': str(a.balance)}
            for a in accounts
        ],
    }


def today_summary(user):
    """今日（當前時區）收支：進頁面即時顯示今天花了多少。1 查詢，收支條件聚合。"""
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)  # 半開區間 [今日 00:00, 明日 00:00)
    agg = Transaction.objects.filter(
        user=user, occurred_at__gte=start, occurred_at__lt=end
    ).aggregate(
        expense=_sum_amount(Transaction.Type.EXPENSE),
        income=_sum_amount(Transaction.Type.INCOME),
    )
    return {
        'date': start.date().isoformat(),
        'expense': str(agg['expense']),
        'income': str(agg['income']),
        'net': str(agg['income'] - agg['expense']),
    }


def _month_bounds(year, month):
    """當前時區的半開月區間 [月初, 次月初) aware datetime 對，直接命中 idx_txn_user_occurred。"""
    tz = timezone.get_current_timezone()
    ny, nm = (year + 1, 1) if month == 12 else (year, month + 1)
    return datetime(year, month, 1, tzinfo=tz), datetime(ny, nm, 1, tzinfo=tz)


def month_summary(user, year, month):
    """指定月（當前時區）的收入／支出／淨額。1 查詢：範圍過濾＋條件聚合。"""
    start, end = _month_bounds(year, month)
    agg = Transaction.objects.filter(
        user=user, occurred_at__gte=start, occurred_at__lt=end
    ).aggregate(
        income=_sum_amount(Transaction.Type.INCOME),
        expense=_sum_amount(Transaction.Type.EXPENSE),
    )
    return {
        'year': year,
        'month': month,
        'income': str(agg['income']),
        'expense': str(agg['expense']),
        'net': str(agg['income'] - agg['expense']),
    }


def summary_by_category(user, year, month):
    """指定月各分類收支；未分類（category=NULL）自成一桶，依支出降冪。1 查詢（GROUP BY）。

    單值 FK → 各桶加總乾淨等於當月總額（與 by-tag 的可重疊維度相對）。
    """
    start, end = _month_bounds(year, month)
    rows = (
        Transaction.objects.filter(user=user, occurred_at__gte=start, occurred_at__lt=end)
        .values('category', 'category__name')
        .annotate(
            income=_sum_amount(Transaction.Type.INCOME),
            expense=_sum_amount(Transaction.Type.EXPENSE),
        )
        .order_by('-expense')
    )
    return {
        'year': year,
        'month': month,
        'categories': [
            {
                'category_id': str(r['category']) if r['category'] is not None else None,
                'category_name': r['category__name'],
                'income': str(r['income']),
                'expense': str(r['expense']),
            }
            for r in rows
        ],
    }


def summary_by_tag(user, year, month):
    """指定月各標籤收支（M2M）。一筆掛 N 標籤即計進 N 桶——可重疊、不可加總當總額；
    無標籤交易不出現（tags__isnull=False 保 INNER JOIN、剔除 NULL 桶）。1 查詢（GROUP BY）。
    """
    start, end = _month_bounds(year, month)
    rows = (
        Transaction.objects.filter(user=user, occurred_at__gte=start, occurred_at__lt=end)
        .filter(tags__isnull=False)
        .values('tags', 'tags__name')
        .annotate(
            income=_sum_amount(Transaction.Type.INCOME),
            expense=_sum_amount(Transaction.Type.EXPENSE),
        )
        .order_by('-expense')
    )
    return {
        'year': year,
        'month': month,
        'tags': [
            {
                'tag_id': str(r['tags']),
                'tag_name': r['tags__name'],
                'income': str(r['income']),
                'expense': str(r['expense']),
            }
            for r in rows
        ],
    }


def _month_range(start, end):
    """(year, month) 從 start 到 end（含）逐月遞增。用整數進位、不做 datetime 加月。"""
    y, m = start
    while (y, m) <= end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def balance_history(user):
    """每帳戶的逐月餘額序列（連續月份、缺月沿用前值 forward-fill）。固定 2 查詢。

    查詢① 帳戶清單、查詢② 每帳戶每月淨變化（TruncMonth 當前時區歸月、GROUP BY）；
    Python 端 per-account 累加 running sum 並補滿月序列。範圍＝該帳戶首筆交易月 →
    max(當前月, 末筆交易月)，讓未來補登的交易不被默默丟掉；無交易帳戶回 months: []。
    末月餘額 == Account.balance，balance-history 順帶當對帳。
    """
    accounts = list(Account.objects.filter(user=user))
    monthly = (
        Transaction.objects.filter(user=user)
        .annotate(m=TruncMonth('occurred_at'))
        .values('account', 'm')
        .annotate(
            income=_sum_amount(Transaction.Type.INCOME),
            expense=_sum_amount(Transaction.Type.EXPENSE),
        )
    )
    # account_id → {(year, month): 當月淨變化}
    changes = {}
    for r in monthly:
        key = (r['m'].year, r['m'].month)
        changes.setdefault(r['account'], {})[key] = r['income'] - r['expense']

    now = timezone.localtime()
    current = (now.year, now.month)
    result = []
    for acc in accounts:
        acc_changes = changes.get(acc.id, {})
        if not acc_changes:
            result.append({'account_id': str(acc.id), 'account_name': acc.name, 'months': []})
            continue
        running = Decimal('0.00')
        months = []
        for y, m in _month_range(min(acc_changes), max(max(acc_changes), current)):
            running += acc_changes.get((y, m), Decimal('0.00'))  # 缺月＝淨變化 0 → 沿用前值
            months.append({'month': f'{y:04d}-{m:02d}', 'balance': str(running)})
        result.append({'account_id': str(acc.id), 'account_name': acc.name, 'months': months})
    return result


def savings_goal_status(user, year, month=None):
    """儲蓄目標達成狀態：帶 month＝月度、省略＝年度（對映 SavingsGoal 的 period_type＋month 可空）。

    查詢① 目標 lookup、查詢② 期間收支淨額聚合。actual_net = income − expense；目標未設 →
    goal_amount/difference/achieved 皆 null（「未設目標」是正常狀態、不 404），actual_net 照算。
    difference = actual_net − goal_amount；achieved = actual_net >= goal_amount。
    """
    if month is not None:
        period_type = SavingsGoal.PeriodType.MONTHLY
        start, end = _month_bounds(year, month)
    else:
        period_type = SavingsGoal.PeriodType.YEARLY
        tz = timezone.get_current_timezone()
        start, end = datetime(year, 1, 1, tzinfo=tz), datetime(year + 1, 1, 1, tzinfo=tz)

    goal = SavingsGoal.objects.filter(
        user=user, period_type=period_type, year=year, month=month
    ).first()
    agg = Transaction.objects.filter(
        user=user, occurred_at__gte=start, occurred_at__lt=end
    ).aggregate(
        income=_sum_amount(Transaction.Type.INCOME),
        expense=_sum_amount(Transaction.Type.EXPENSE),
    )
    actual_net = agg['income'] - agg['expense']

    status = {
        'period_type': period_type.value,
        'year': year,
        'month': month,
        'goal_amount': None,
        'actual_net': str(actual_net),
        'difference': None,
        'achieved': None,
    }
    if goal is not None:
        status['goal_amount'] = str(goal.amount)
        status['difference'] = str(actual_net - goal.amount)
        status['achieved'] = actual_net >= goal.amount
    return status

"""報表聚合：純函式吃 user，全在 DB 端聚合，view 只驗參數並包成回應。

金額一律 str()——DRF 的 JSONEncoder 對裸 Decimal 會轉 float、丟精度與尾零；聚合掛
Coalesce(Value(0.00)) 讓空集合回 "0.00" 而非 null，並保住 scale=2。時區邊界一律走
current timezone（settings.TIME_ZONE）、不寫死時區字串。
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.core.cache import cache
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


def _txns_in_range(user, start, end):
    """[start, end) 半開區間的使用者交易 queryset；lazy——外層續接 GROUP BY 或聚合都仍是 1 查詢。

    end 為排除界、呼叫端傳次一時刻表達含當日；命中 idx_txn_user_occurred。
    """
    return Transaction.objects.filter(user=user, occurred_at__gte=start, occurred_at__lt=end)


def _range_net(user, start, end):
    """區間收支聚合，回 dict{income, expense}（皆 Decimal）。

    str() 由各信封出口統一處理——savings-goal 要拿原值算 difference/achieved，故核心層不轉字串。
    """
    return _txns_in_range(user, start, end).aggregate(
        income=_sum_amount(Transaction.Type.INCOME),
        expense=_sum_amount(Transaction.Type.EXPENSE),
    )


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
    agg = _range_net(user, start, end)
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
    agg = _range_net(user, start, end)
    return {
        'year': year,
        'month': month,
        'income': str(agg['income']),
        'expense': str(agg['expense']),
        'net': str(agg['income'] - agg['expense']),
    }


def range_summary(user, start_date, end_date):
    """任意日期區間 [start_date, end_date]（含當日）的收入／支出／淨額。1 查詢。

    date 轉當前時區半開區間 [start 00:00, end+1 00:00)：end 含當日故加一天當排除界，命中索引。
    """
    tz = timezone.get_current_timezone()
    start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=tz)
    end_next = end_date + timedelta(days=1)  # 含當日 → 排除界＝隔日 00:00
    end = datetime(end_next.year, end_next.month, end_next.day, tzinfo=tz)
    agg = _range_net(user, start, end)
    return {
        'start': start_date.isoformat(),
        'end': end_date.isoformat(),
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
        _txns_in_range(user, start, end)
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
        _txns_in_range(user, start, end)
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
    Python 端 per-account 累加 running sum 並補滿月序列。範圍＝首筆交易月（純期初餘額
    無交易者＝當前月）→ max(當前月, 末筆交易月)，讓未來補登的交易不被默默丟掉。

    running 錨定到 Account.balance：從「未記成交易的期初餘額」（balance − 交易淨額）起算，
    末月餘額因此恆等於 Account.balance——期初餘額不是交易，單純累加交易的 running sum
    看不到它（就是「走勢末月 ≠ 儀表板真餘額」的根因）。無交易且無期初餘額者回 months: []。
    （錨定＝以 balance 為準：此端點不再獨立對帳，要偵測 balance 漂移另設 reconcile。）
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
        if not acc_changes and not acc.balance:
            # 無交易且無期初餘額 → 沒有可畫的點
            result.append({'account_id': str(acc.id), 'account_name': acc.name, 'months': []})
            continue
        # 錨定：running 從「未記成交易的期初餘額」（balance − 交易淨額）起，逐月加淨變化後
        # 末月自然收斂回 acc.balance（與月份落點無關）。純期初餘額無交易者只有當前月一點。
        net = sum(acc_changes.values(), Decimal('0.00'))
        running = acc.balance - net
        start = min(acc_changes) if acc_changes else current
        end = max([*acc_changes, current])
        months = []
        for y, m in _month_range(start, end):
            running += acc_changes.get((y, m), Decimal('0.00'))  # 缺月＝淨變化 0 → 沿用前值
            months.append({'month': f'{y:04d}-{m:02d}', 'balance': str(running)})
        result.append({'account_id': str(acc.id), 'account_name': acc.name, 'months': months})
    return result


# balance-history 是唯一全歷史、讀取量隨終身交易數成長的報表（已掛 reports-heavy 桶）→
# 只對它做 cache-aside。TTL 兜底不經交易的顯示變動（如帳戶改名）；交易建/改/刪走顯式失效。
_BALANCE_HISTORY_TTL = 300  # 秒


def _balance_history_key(user_id):
    return f'reports:balance-history:{user_id}'


def balance_history_cached(user):
    """balance_history 的 cache-aside 包裝：命中回快取、未命中算完存 TTL。"""
    return cache.get_or_set(
        _balance_history_key(user.id), lambda: balance_history(user), _BALANCE_HISTORY_TTL
    )


def invalidate_balance_history(user_id):
    """失效某 user 的 balance-history 快取。由交易寫入的 on_commit 呼叫（TransactionViewSet），
    只在 DB commit 後才清——避免並發讀者拿未提交的舊資料回填、髒值撐滿整個 TTL。"""
    cache.delete(_balance_history_key(user_id))


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
    agg = _range_net(user, start, end)
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

"""定期定額：每天把到期的規則轉成真實交易。

投遞語意是 at-least-once——beat 可能重複投遞、worker 可能重試，同一條規則的同一個到期日
因此可能被處理兩次。冪等不靠鎖，靠 Transaction 的 (source_rule, occurred_at) 唯一約束：
建交易一律走 get_or_create，並發的輸家在唯一索引上等待、拿到 IntegrityError、由 get_or_create
的內部 savepoint 吞下後重查，`created` 為假就不動餘額。鎖只保護記得上鎖的路徑，約束保護全部。
"""

import logging
from datetime import datetime, time, timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from . import reports, services
from .models import RecurringRule, Transaction, next_due

logger = logging.getLogger(__name__)


@shared_task
def post_due_recurring_rules():
    """beat 每日觸發：把所有到期規則轉成交易，逐條獨立成敗。

    先取 id 清單再逐條處理：每條規則有自己的 atomic，一條爛規則 rollback 自己那一份，
    其餘照建。回傳新建交易筆數（無 result backend，僅供 eager 模式的測試與日誌）。
    """
    today = timezone.localdate()
    rule_ids = list(
        RecurringRule.objects.filter(is_active=True, next_run_date__lte=today).values_list(
            'id', flat=True
        )
    )
    posted = 0
    for rule_id in rule_ids:
        try:
            posted += _post_rule(rule_id, today)
        except Exception:
            logger.exception('定期定額規則 %s 處理失敗', rule_id)
    logger.info('定期定額處理完成：到期規則 %s 條、新增交易 %s 筆', len(rule_ids), posted)
    return posted


def _post_rule(rule_id, today):
    """補齊單一規則所有錯過的期數，回傳實際新建的交易筆數。

    catch-up：停機三個月，房租還是欠三筆——逐期建，occurred_at 各自是原到期日而非今天。
    迴圈必然終止，因為 next_due 的起算日是本期到期日的隔天，游標每輪嚴格遞增。
    """
    created_count = 0
    with transaction.atomic():
        rule = RecurringRule.objects.select_related('user').get(pk=rule_id)
        while rule.next_run_date <= today:
            due = rule.next_run_date
            txn, created = Transaction.objects.get_or_create(
                source_rule=rule,
                occurred_at=timezone.make_aware(datetime.combine(due, time.min)),
                defaults={
                    'user_id': rule.user_id,
                    'account_id': rule.account_id,
                    'category_id': rule.category_id,
                    'amount': rule.amount,
                    'type': rule.type,
                    'name': rule.name,
                    'description': rule.description,
                },
            )
            if created:
                services.apply_to_balance(txn.account_id, txn.type, txn.amount)
                created_count += 1
            rule.next_run_date = next_due(rule.day_of_month, due + timedelta(days=1))
        rule.save(update_fields=['next_run_date', 'updated_at'])

        if created_count:
            # 與 API 建交易同一組服務函式：餘額、儲蓄目標帶入、快取失效三件事只有一份實作。
            services.carry_forward_savings_goal(rule.user)
            user_id = rule.user_id
            transaction.on_commit(lambda: reports.invalidate_balance_history(user_id))
    return created_count

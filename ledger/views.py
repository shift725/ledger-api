from datetime import datetime

from django.db import transaction
from django.db.models import ProtectedError
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import reports, schema, services
from .filters import TransactionFilter
from .models import Account, Category, RecurringRule, SavingsGoal, Tag, Transaction
from .serializers import (
    AccountSerializer,
    CategorySerializer,
    RecurringRuleSerializer,
    SavingsGoalSerializer,
    TagSerializer,
    TransactionSerializer,
)


class LedgerPagination(PageNumberPagination):
    # 掛在 ledger 基底而非全域 REST_FRAMEWORK：核心 /api/auth/ 端點的回應形狀不受影響。
    page_size = 20


class OwnedModelViewSet(viewsets.ModelViewSet):
    """業務資源共用基底：強制登入 + 依 request.user 做資料隔離。

    - get_queryset：把可見資料限縮到當前使用者（別人的物件不在集合內 → 讀/改/刪皆 404）。
    - perform_create：寫入時把 user 設為當前使用者，無視 client 夾帶的 user。
    - 分頁：list 一律回 count/next/previous/results 信封（LedgerPagination）。

    五個資源共用這一份，資安邊界只有一處要審。
    """

    permission_classes = [IsAuthenticated]
    pagination_class = LedgerPagination

    def get_queryset(self):
        return super().get_queryset().filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class CategoryViewSet(OwnedModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class TagViewSet(OwnedModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer


class AccountViewSet(OwnedModelViewSet):
    queryset = Account.objects.all()
    serializer_class = AccountSerializer

    def perform_create(self, serializer):
        with transaction.atomic():
            self._demote_existing_default(serializer)
            serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        with transaction.atomic():
            self._demote_existing_default(serializer)
            serializer.save()

    def _demote_existing_default(self, serializer):
        # 設為預設帳戶時，先清掉本人舊的預設，否則撞「一人一個預設」部分唯一索引。
        # 併發雙寫的罕見情況交給 DB 約束兜底（其一報 IntegrityError）。
        if serializer.validated_data.get('is_default'):
            self.get_queryset().filter(is_default=True).update(is_default=False)

    def destroy(self, request, *args, **kwargs):
        # Transaction.account 與 RecurringRule.account 都是 PROTECT：刪還被引用的帳戶會丟
        # ProtectedError，攔成 409 而非 500。
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {'detail': '帳戶尚有交易或定期定額規則，無法刪除'},
                status=status.HTTP_409_CONFLICT,
            )


class TransactionViewSet(OwnedModelViewSet):
    # 序列化每筆都要 account/category 名稱與 tags：FK 用 select_related（JOIN 一次帶回）、
    # M2M 用 prefetch_related（第二條查詢+記憶體組裝）→ 查詢數固定，不隨筆數線性成長（N+1）。
    queryset = Transaction.objects.select_related('account', 'category').prefetch_related('tags')
    serializer_class = TransactionSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = TransactionFilter
    search_fields = ['name', 'description']
    # ?ordering=amount 在等值金額上頁界順序不保證穩定（非唯一排序鍵＋offset 分頁），
    # 個人規模可接受；client 要穩定可自帶次鍵 ?ordering=amount,-occurred_at。
    ordering_fields = ['occurred_at', 'amount']

    def perform_create(self, serializer):
        with transaction.atomic():
            txn = serializer.save(user=self.request.user)
            services.apply_to_balance(txn.account_id, txn.type, txn.amount)
            # carry-forward 只在建立時觸發（編輯/刪除不碰）；與建交易同一 atomic，一起成敗。
            services.carry_forward_savings_goal(self.request.user)
            self._invalidate_balance_history_on_commit()

    def perform_update(self, serializer):
        # 編輯 = 還原舊影響 + 套用新影響（帳戶可被改掉，故 reverse 打舊帳戶、apply 打新帳戶）。
        # 舊值必須是「已提交的前一版」：select_for_update 鎖住這筆交易列，讓同筆並發編輯
        # 排隊——後到者等前者 commit 後才讀到新值，避免兩個編輯各自 reverse 同一份過期舊值
        # （F() 擋 lost update，擋不了過期讀）。
        with transaction.atomic():
            # 剝掉列表用的優化再上鎖：PostgreSQL 禁止 FOR UPDATE 套在 outer join 的
            # nullable 邊（category 是 SET_NULL → LEFT JOIN，不剝直接 NotSupportedError）；
            # 鎖舊值只需本列三欄，prefetch 一併剝掉省一次無謂查詢。
            locked = (
                self.get_queryset()
                .select_related(None)
                .prefetch_related(None)
                .select_for_update()
                .get(pk=serializer.instance.pk)
            )
            old_account_id, old_type, old_amount = locked.account_id, locked.type, locked.amount
            txn = serializer.save()
            services.reverse_from_balance(old_account_id, old_type, old_amount)
            services.apply_to_balance(txn.account_id, txn.type, txn.amount)
            self._invalidate_balance_history_on_commit()

    def perform_destroy(self, instance):
        with transaction.atomic():
            services.reverse_from_balance(instance.account_id, instance.type, instance.amount)
            instance.delete()
            self._invalidate_balance_history_on_commit()

    def _invalidate_balance_history_on_commit(self):
        # 交易改動了餘額 → 失效該 user 的 balance-history 快取。掛 on_commit：只在本次
        # atomic 真正 commit 後才清，rollback 時不誤清；user pk 綁進閉包，不留 self 參照。
        user_id = self.request.user.id
        transaction.on_commit(lambda: reports.invalidate_balance_history(user_id))


class SavingsGoalViewSet(OwnedModelViewSet):
    queryset = SavingsGoal.objects.all()
    serializer_class = SavingsGoalSerializer


class RecurringRuleViewSet(OwnedModelViewSet):
    # 序列化附帳戶／分類名稱：select_related 讓列表的查詢數不隨規則數成長。
    queryset = RecurringRule.objects.select_related('account', 'category')
    serializer_class = RecurringRuleSerializer


def _int_param(raw, *, default, lo, hi, name):
    """query 整數參數轉型並驗範圍；未帶回 default，非法拋 ValidationError（DRF → 400）。

    先驗參數再進 reports，避免非法 year/month 讓 datetime() 在聚合層炸 500。
    """
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError({name: f'必須是 {lo}–{hi} 的整數'})
    if not lo <= value <= hi:
        raise ValidationError({name: f'必須介於 {lo}–{hi} 之間'})
    return value


def _date_param(raw, *, name):
    """query 日期參數轉 date；未帶或格式錯拋 ValidationError（→ 400）。

    鎖 strptime('%Y-%m-%d')；不用 fromisoformat（3.11 起連 '20260706' 等都收，契約會漂）。
    """
    if raw is None:
        raise ValidationError({name: '必填，格式須為 YYYY-MM-DD'})
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        raise ValidationError({name: '格式須為 YYYY-MM-DD'})


class ReportViewSet(viewsets.ViewSet):
    """唯讀報表端點集合（/api/ledger/reports/…）：各 action 委派 reports.py 的純函式。

    用 ViewSet（非 ModelViewSet）：報表不是 CRUD 資源、無單一 queryset/序列化器；每支都吃
    request.user 過濾，資安邊界落在 reports 函式內。
    """

    permission_classes = [IsAuthenticated]
    # 預設無 throttle scope（ScopedRateThrottle 對 None 是 no-op）。設為 class 屬性，個別 @action
    # 才能用 initkwargs 覆寫成別的桶——DRF as_view 會檢查該屬性存在、缺了報 TypeError。
    throttle_scope = None

    @staticmethod
    def _period(request):
        """取 year/month（未帶＝當前時區當月），驗 year 1–9999、month 1–12。"""
        now = timezone.localtime()
        return (
            _int_param(
                request.query_params.get('year'), default=now.year, lo=1, hi=9999, name='year'
            ),
            _int_param(
                request.query_params.get('month'), default=now.month, lo=1, hi=12, name='month'
            ),
        )

    @schema.balance
    @action(detail=False)
    def balance(self, request):
        return Response(reports.balance_overview(request.user))

    @schema.today
    @action(detail=False)
    def today(self, request):
        return Response(reports.today_summary(request.user))

    @schema.summary
    @action(detail=False)
    def summary(self, request):
        year, month = self._period(request)
        return Response(reports.month_summary(request.user, year, month))

    @schema.summary_by_category
    @action(detail=False, url_path='summary/by-category')
    def summary_by_category(self, request):
        year, month = self._period(request)
        return Response(reports.summary_by_category(request.user, year, month))

    @schema.summary_by_tag
    @action(detail=False, url_path='summary/by-tag')
    def summary_by_tag(self, request):
        year, month = self._period(request)
        return Response(reports.summary_by_tag(request.user, year, month))

    @schema.summary_range
    @action(detail=False, url_path='summary/range')
    def summary_range(self, request):
        # start/end 皆必填、鎖 YYYY-MM-DD、當前時區解讀；end 含當日（reports 端轉半開區間）。
        start = _date_param(request.query_params.get('start'), name='start')
        end = _date_param(request.query_params.get('end'), name='end')
        if start > end:
            raise ValidationError({'start': 'start 不可晚於 end'})
        return Response(reports.range_summary(request.user, start, end))

    @schema.balance_history
    @action(detail=False, url_path='balance-history', throttle_scope='reports-heavy')
    def balance_history(self, request):
        return Response(reports.balance_history_cached(request.user))

    @schema.savings_goal_status
    @action(detail=False, url_path='savings-goal-status')
    def savings_goal_status(self, request):
        # 與 _period 不同：month 選填（省略＝年度、不套當月預設）；year 省略＝當年。
        now = timezone.localtime()
        year = _int_param(
            request.query_params.get('year'), default=now.year, lo=1, hi=9999, name='year'
        )
        month = _int_param(
            request.query_params.get('month'), default=None, lo=1, hi=12, name='month'
        )
        return Response(reports.savings_goal_status(request.user, year, month))

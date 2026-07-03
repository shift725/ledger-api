from django.db import transaction
from django.db.models import ProtectedError
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import services
from .filters import TransactionFilter
from .models import Account, Category, SavingsGoal, Tag, Transaction
from .serializers import (
    AccountSerializer,
    CategorySerializer,
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
        # Transaction.account 是 PROTECT：刪有交易的帳戶會丟 ProtectedError，攔成 409 而非 500。
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response({'detail': '帳戶尚有交易，無法刪除'}, status=status.HTTP_409_CONFLICT)


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

    def perform_destroy(self, instance):
        with transaction.atomic():
            services.reverse_from_balance(instance.account_id, instance.type, instance.amount)
            instance.delete()


class SavingsGoalViewSet(OwnedModelViewSet):
    queryset = SavingsGoal.objects.all()
    serializer_class = SavingsGoalSerializer

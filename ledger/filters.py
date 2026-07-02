import django_filters

from .models import Transaction


class TransactionFilter(django_filters.FilterSet):
    """交易列表過濾。條件疊在 view 端 user 隔離之後，只縮小、不放大可見範圍。

    account/category/tag 用 UUIDFilter 做 pk 等值，不用預設的 ModelChoiceFilter——
    後者會先驗「id 存在於全表」：不存在回 400、存在但非本人回 200 空，等於洩漏
    id 存在性；UUIDFilter 對任何合法 UUID 一律 200 空清單，格式錯誤才 400。
    """

    occurred_after = django_filters.IsoDateTimeFilter(field_name='occurred_at', lookup_expr='gte')
    occurred_before = django_filters.IsoDateTimeFilter(field_name='occurred_at', lookup_expr='lte')
    amount_min = django_filters.NumberFilter(field_name='amount', lookup_expr='gte')
    amount_max = django_filters.NumberFilter(field_name='amount', lookup_expr='lte')
    account = django_filters.UUIDFilter()
    category = django_filters.UUIDFilter()
    # 單一 tag 的 M2M 等值一筆最多命中一次，免 distinct()；
    # 日後要多 tag（OR）換 BaseInFilter + distinct=True，?tag=<單值> 呼叫不變。
    tag = django_filters.UUIDFilter(field_name='tags')

    class Meta:
        model = Transaction
        fields = ['type']

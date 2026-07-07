import django_filters

from .models import Transaction


class UUIDInFilter(django_filters.BaseInFilter, django_filters.UUIDFilter):
    """逗號分隔多 UUID：BaseInFilter 拆值、UUIDFilter 逐值驗格式（含壞值 → 400）。"""


class TransactionFilter(django_filters.FilterSet):
    """交易列表過濾。條件疊在 view 端 user 隔離之後，只縮小、不放大可見範圍。

    account/category/tags 過濾一律 UUID 等值，不用 ModelChoiceFilter 系——
    後者會先驗「id 存在於全表」：不存在回 400、存在但非本人回 200 空，等於洩漏
    id 存在性；UUID 過濾對任何合法 UUID 一律 200 空清單，格式錯誤才 400。
    """

    occurred_after = django_filters.IsoDateTimeFilter(field_name='occurred_at', lookup_expr='gte')
    occurred_before = django_filters.IsoDateTimeFilter(field_name='occurred_at', lookup_expr='lte')
    amount_min = django_filters.NumberFilter(field_name='amount', lookup_expr='gte')
    amount_max = django_filters.NumberFilter(field_name='amount', lookup_expr='lte')
    account = django_filters.UUIDFilter()
    category = django_filters.UUIDFilter()
    # OR：tags__in 單次 JOIN，一筆交易掛多個命中 tag 會出多列 → 需 distinct 收斂
    # （分頁 count 同步正確）。
    tags_any = UUIDInFilter(field_name='tags', distinct=True)
    # AND：逐 tag 疊 .filter()，每個 .filter() 是獨立 JOIN、等值最多命中一次
    # （M2M through 表有唯一約束），天然不重複、免 distinct。
    tags_all = UUIDInFilter(field_name='tags', method='filter_tags_all')

    def filter_tags_all(self, queryset, name, value):
        for tag_id in set(value):
            queryset = queryset.filter(tags=tag_id)
        return queryset

    class Meta:
        model = Transaction
        fields = ['type']

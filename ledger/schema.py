"""報表端點的 OpenAPI 標註（drf-spectacular）。

報表回應是 reports.py 手組的 dict，AutoSchema 自動推導只吃 serializer、看不到形狀，
不標註就是「200 無 schema」的空殼文件。這裡用 inline_serializer 把實際信封逐鍵宣告——
只產文件、不參與序列化，回應行為零改動；欄位語意與 null 規則以 reports.py 為準，
兩邊不一致視為 bug。OpenAPI 型別產生器（如 TS client）吃的就是這份宣告。

金額一律 DecimalField：DRF 把 Decimal 序列化成字串（保精度與尾零），schema 對應
string(format=decimal)——client 不可當 number 解析。
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers

from .models import Account, SavingsGoal

# Account.Type 的 choices 出現在帳戶 CRUD 與報表信封兩個 component，enum 自動命名
# 會撞名並退化成雜湊尾名；settings 的 ENUM_NAME_OVERRIDES 釘名時需要一個
# 「模組層屬性」的 import 路徑（import_string 解不開 Account.Type.choices 這種巢狀路徑），
# 所以在這裡放一個常數給它指。
ACCOUNT_TYPE_CHOICES = Account.Type.choices


def _money(**kwargs):
    """金額欄位（12,2），JSON 為字串。"""
    return serializers.DecimalField(max_digits=12, decimal_places=2, **kwargs)


_YEAR = OpenApiParameter('year', int, description='西元年 1–9999；未帶＝當前時區的今年。')
_MONTH = OpenApiParameter('month', int, description='月 1–12；未帶＝當前時區的本月。')

balance = extend_schema(
    summary='總餘額與各帳戶餘額',
    responses=inline_serializer(
        name='BalanceOverview',
        fields={
            'total_balance': _money(),
            'accounts': inline_serializer(
                name='BalanceOverviewAccount',
                fields={
                    'id': serializers.UUIDField(),
                    'name': serializers.CharField(),
                    'type': serializers.ChoiceField(choices=ACCOUNT_TYPE_CHOICES),
                    'balance': _money(),
                },
                many=True,
            ),
        },
    ),
)

today = extend_schema(
    summary='今日（當前時區）收支',
    responses=inline_serializer(
        name='TodaySummary',
        fields={
            'date': serializers.DateField(),
            'expense': _money(),
            'income': _money(),
            'net': _money(),
        },
    ),
)

summary = extend_schema(
    summary='指定月收支',
    parameters=[_YEAR, _MONTH],
    responses=inline_serializer(
        name='MonthSummary',
        fields={
            'year': serializers.IntegerField(),
            'month': serializers.IntegerField(),
            'income': _money(),
            'expense': _money(),
            'net': _money(),
        },
    ),
)

summary_by_category = extend_schema(
    summary='指定月各分類收支（單值 FK，各桶加總＝當月總額）',
    parameters=[_YEAR, _MONTH],
    responses=inline_serializer(
        name='CategoryBreakdown',
        fields={
            'year': serializers.IntegerField(),
            'month': serializers.IntegerField(),
            'categories': inline_serializer(
                name='CategoryBreakdownItem',
                fields={
                    # 未分類交易自成一桶：兩欄皆 null。
                    'category_id': serializers.UUIDField(allow_null=True),
                    'category_name': serializers.CharField(allow_null=True),
                    'income': _money(),
                    'expense': _money(),
                },
                many=True,
            ),
        },
    ),
)

summary_by_tag = extend_schema(
    summary='指定月各標籤收支（M2M 可重疊維度，不可加總當總額）',
    parameters=[_YEAR, _MONTH],
    responses=inline_serializer(
        name='TagBreakdown',
        fields={
            'year': serializers.IntegerField(),
            'month': serializers.IntegerField(),
            'tags': inline_serializer(
                name='TagBreakdownItem',
                fields={
                    'tag_id': serializers.UUIDField(),
                    'tag_name': serializers.CharField(),
                    'income': _money(),
                    'expense': _money(),
                },
                many=True,
            ),
        },
    ),
)

summary_range = extend_schema(
    summary='任意日期區間收支',
    parameters=[
        OpenApiParameter(
            'start', OpenApiTypes.DATE, required=True, description='起日（含），YYYY-MM-DD。'
        ),
        OpenApiParameter(
            'end',
            OpenApiTypes.DATE,
            required=True,
            description='迄日（含當日），YYYY-MM-DD；須 start ≤ end。',
        ),
    ],
    responses=inline_serializer(
        name='RangeSummary',
        fields={
            'start': serializers.DateField(),
            'end': serializers.DateField(),
            'income': _money(),
            'expense': _money(),
            'net': _money(),
        },
    ),
)

balance_history = extend_schema(
    summary='每帳戶逐月餘額（連續月份、缺月沿用前值）',
    responses=inline_serializer(
        name='BalanceHistoryAccount',
        fields={
            'account_id': serializers.UUIDField(),
            'account_name': serializers.CharField(),
            'months': inline_serializer(
                name='BalanceHistoryMonth',
                fields={
                    'month': serializers.CharField(help_text='YYYY-MM'),
                    'balance': _money(),
                },
                many=True,
            ),
        },
        many=True,
    ),
)

savings_goal_status = extend_schema(
    summary='儲蓄目標達成狀態（帶 month＝月度、省略＝年度）',
    parameters=[
        _YEAR,
        OpenApiParameter(
            'month', int, description='月 1–12；帶＝查月度目標、省略＝查年度目標（非預設當月）。'
        ),
    ],
    responses=inline_serializer(
        name='SavingsGoalStatus',
        fields={
            'period_type': serializers.ChoiceField(choices=SavingsGoal.PeriodType.choices),
            'year': serializers.IntegerField(),
            'month': serializers.IntegerField(allow_null=True),
            # 該期未設目標：goal_amount／difference／achieved 皆 null，actual_net 照算。
            'goal_amount': _money(allow_null=True),
            'actual_net': _money(),
            'difference': _money(allow_null=True),
            'achieved': serializers.BooleanField(allow_null=True),
        },
    ),
)

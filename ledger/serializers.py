from django.utils import timezone
from rest_framework import serializers

from .models import Account, Category, RecurringRule, SavingsGoal, Tag, Transaction, next_due


# (user, name) 唯一約束的乾淨 400。三資源（Account/Category/Tag）都有
# UniqueConstraint(user, name)，但 user 不在 serializer fields（由 view 的 perform_create
# 設定）→ DRF 不自動掛 UniqueTogetherValidator，重名落到 DB 炸 IntegrityError→500。這裡先回
# 400，DB 約束仍是最後防線（並發競態）。同 SavingsGoalSerializer.validate 判準。
# 用註解不用 docstring：子類自身無 docstring 時 __doc__ 會沿 MRO 取到本 mixin 的，
# drf-spectacular 會把它當 component description → 汙染凍結契約（實測踩過）。
class UniqueNamePerUserMixin:
    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context.get('request')
        name = attrs.get('name', getattr(self.instance, 'name', None))
        if request is not None and name is not None:
            dup = self.Meta.model.objects.filter(user=request.user, name=name)
            if self.instance is not None:  # 編輯：排除自己，改成原名不算重複
                dup = dup.exclude(pk=self.instance.pk)
            if dup.exists():
                raise serializers.ValidationError({'name': '此名稱已使用'})
        return attrs


class AccountSerializer(UniqueNamePerUserMixin, serializers.ModelSerializer):
    # balance 唯讀：衍生快取，由交易維護、不接受 client 直接寫入。
    class Meta:
        model = Account
        fields = ['id', 'name', 'type', 'balance', 'is_default']
        read_only_fields = ['id', 'balance']


class CategorySerializer(UniqueNamePerUserMixin, serializers.ModelSerializer):
    # user 不在 fields：擁有者由 view 的 perform_create 設定，不信任 client。
    # created_at/updated_at 不列出：系統時戳，不對外顯示、也不可改。
    class Meta:
        model = Category
        fields = ['id', 'name', 'description']
        read_only_fields = ['id']


class TagSerializer(UniqueNamePerUserMixin, serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['id', 'name', 'description']
        read_only_fields = ['id']


class TransactionSerializer(serializers.ModelSerializer):
    # 寫入用 account/category/tags 的 PK；讀出另附可讀名稱，前端不必再查一次。
    account_name = serializers.CharField(source='account.name', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True, allow_null=True)
    tag_names = serializers.StringRelatedField(source='tags', many=True, read_only=True)

    class Meta:
        model = Transaction
        fields = [
            'id',
            'account',
            'category',
            'amount',
            'type',
            'name',
            'description',
            'occurred_at',
            'tags',
            'source_rule',
            'account_name',
            'category_name',
            'tag_names',
        ]
        # source_rule 唯讀：由自動記帳流程回填，client 不得宣稱某筆交易來自某規則。
        read_only_fields = ['id', 'source_rule']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 資安關鍵：把關聯欄位的可選 queryset 收斂到當前使用者。
        # 預設是 <Model>.objects.all()，否則 client 能引用別人的 account/category/tag
        # （掛到自己的交易，或用 id 探測別人的資料是否存在）。
        # 條件是「已認證」而非「有 request」：真實流量必經 view 的 IsAuthenticated，
        # 到得了這裡的一定是登入者；唯一的匿名來源是 OpenAPI 產生器的假 request
        # （user=AnonymousUser），拿它過濾 UUID 外鍵會炸，略過收斂讓 schema 推導用預設欄位。
        request = self.context.get('request')
        if request is not None and request.user.is_authenticated:
            user = request.user
            self.fields['account'].queryset = Account.objects.filter(user=user)
            self.fields['category'].queryset = Category.objects.filter(user=user)
            self.fields['tags'].child_relation.queryset = Tag.objects.filter(user=user)


class RecurringRuleSerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source='account.name', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True, allow_null=True)

    class Meta:
        model = RecurringRule
        fields = [
            'id',
            'account',
            'category',
            'amount',
            'type',
            'name',
            'description',
            'day_of_month',
            'is_active',
            'next_run_date',
            'account_name',
            'category_name',
        ]
        # next_run_date 唯讀：它是系統推進的游標，client 能改就能讓規則補跑或跳期。
        read_only_fields = ['id', 'next_run_date']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 與 TransactionSerializer 同一道第二層隔離：關聯欄位的可選 queryset 收斂到本人。
        # 條件用 is_authenticated 而非 is not None——OpenAPI 產生器的假 request 帶 AnonymousUser。
        request = self.context.get('request')
        if request is not None and request.user.is_authenticated:
            user = request.user
            self.fields['account'].queryset = Account.objects.filter(user=user)
            self.fields['category'].queryset = Category.objects.filter(user=user)

    def create(self, validated_data):
        validated_data['next_run_date'] = next_due(
            validated_data['day_of_month'], timezone.localdate()
        )
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # 改扣款日 → 重算；停用後重新啟用 → 從今天重算（停用期間不補帳：暫停是使用者的
        # 意思表示，不是服務停機）。只改金額/帳戶等不動游標，免得編輯一次就跳過一期。
        day = validated_data.get('day_of_month', instance.day_of_month)
        reactivated = validated_data.get('is_active') and not instance.is_active
        if day != instance.day_of_month or reactivated:
            validated_data['next_run_date'] = next_due(day, timezone.localdate())
        return super().update(instance, validated_data)


class SavingsGoalSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavingsGoal
        fields = ['id', 'period_type', 'year', 'month', 'amount']
        read_only_fields = ['id']

    def validate(self, attrs):
        # 判別式：月度必有 1–12 的 month；年度不可有 month。這裡先回乾淨的 400，
        # DB 的 CheckConstraint 仍是最後防線。PATCH 只帶部分欄位時，用 instance 補齊。
        period_type = attrs.get('period_type', getattr(self.instance, 'period_type', None))
        month = attrs.get('month', getattr(self.instance, 'month', None))
        if period_type == SavingsGoal.PeriodType.MONTHLY and month not in range(1, 13):
            raise serializers.ValidationError({'month': '月度目標的 month 需為 1–12'})
        if period_type == SavingsGoal.PeriodType.YEARLY and month is not None:
            raise serializers.ValidationError({'month': '年度目標不可指定 month'})

        # 同期間不可重複 → 回乾淨 400（DB 唯一約束是最後防線；並發競態的罕見重複
        # 由後續建立流程的 get_or_create 收斂）。user 不在 fields，DRF 不會自動驗這條約束。
        request = self.context.get('request')
        if request is not None:
            year = attrs.get('year', getattr(self.instance, 'year', None))
            dup = SavingsGoal.objects.filter(
                user=request.user, period_type=period_type, year=year, month=month
            )
            if self.instance is not None:
                dup = dup.exclude(pk=self.instance.pk)
            if dup.exists():
                raise serializers.ValidationError('此期間已有儲蓄目標')
        return attrs

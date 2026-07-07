from rest_framework import serializers

from .models import Account, Category, SavingsGoal, Tag, Transaction


class AccountSerializer(serializers.ModelSerializer):
    # balance 唯讀：衍生快取，由交易維護、不接受 client 直接寫入。
    class Meta:
        model = Account
        fields = ['id', 'name', 'type', 'balance', 'is_default']
        read_only_fields = ['id', 'balance']


class CategorySerializer(serializers.ModelSerializer):
    # user 不在 fields：擁有者由 view 的 perform_create 設定，不信任 client。
    # created_at/updated_at 不列出：系統時戳，不對外顯示、也不可改。
    class Meta:
        model = Category
        fields = ['id', 'name', 'description']
        read_only_fields = ['id']


class TagSerializer(serializers.ModelSerializer):
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
            'account_name',
            'category_name',
            'tag_names',
        ]
        read_only_fields = ['id']

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

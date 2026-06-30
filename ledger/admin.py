from django.contrib import admin

from .models import Account, Category, SavingsGoal, Tag, Transaction


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'balance', 'is_default', 'user')
    list_filter = ('type', 'is_default')
    search_fields = ('name',)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'user')
    search_fields = ('name',)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'user')
    search_fields = ('name',)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'amount', 'account', 'category', 'occurred_at')
    list_filter = ('type', 'account')
    search_fields = ('name', 'description')
    date_hierarchy = 'occurred_at'
    filter_horizontal = ('tags',)


@admin.register(SavingsGoal)
class SavingsGoalAdmin(admin.ModelAdmin):
    list_display = ('period_type', 'year', 'month', 'amount', 'user')
    list_filter = ('period_type', 'year')

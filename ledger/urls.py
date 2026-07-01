from rest_framework.routers import DefaultRouter

from .views import (
    AccountViewSet,
    CategoryViewSet,
    SavingsGoalViewSet,
    TagViewSet,
    TransactionViewSet,
)

# DefaultRouter 依每個 ViewSet 自動產生 list/detail 路由（/categories/、/categories/<pk>/…）。
router = DefaultRouter()
router.register('accounts', AccountViewSet, basename='account')
router.register('categories', CategoryViewSet, basename='category')
router.register('tags', TagViewSet, basename='tag')
router.register('transactions', TransactionViewSet, basename='transaction')
router.register('savings-goals', SavingsGoalViewSet, basename='savings-goal')

urlpatterns = router.urls

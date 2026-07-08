from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from .views import healthz

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('accounts.urls')),
    path('api/ledger/', include('ledger.urls')),
    # 機器可讀契約＋互動文件。兩者刻意公開（AllowAny）：schema 是對外契約、不含業務資料，
    # 實際打 API 仍要 JWT；匿名流量由全域 anon throttle 管。
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='docs'),
    # 基建探針（compose healthcheck／LB／CD smoke 復用）：刻意公開、無尾斜線
    # （orchestrator 生態慣例）；不進 OpenAPI schema——基建契約非業務契約。
    path('healthz', healthz, name='healthz'),
]

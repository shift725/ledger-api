from datetime import timedelta
from pathlib import Path

import dj_database_url
from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='', cast=Csv())

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',  # 登出黑名單
    'django_filters',
    'drf_spectacular',
    'accounts',
    'ledger',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {'default': dj_database_url.parse(config('DATABASE_URL'), conn_max_age=600)}

# throttle 計數與業務快取共用 default cache。設 REDIS_URL（容器由 compose 注入）→ 走 Redis、
# 計數跨 gunicorn worker 一致；未設（CI／本機 venv 測試）→ 不定義 CACHES，落 Django 預設
# LocMemCache：測邏輯不測基建，CI 不必起 Redis service。redis-py 由 RedisCache backend 驅動。
REDIS_URL = config('REDIS_URL', default=None)
if REDIS_URL:  # pragma: no cover — 環境閘設定；Redis 路徑走容器 smoke 驗，不進 LocMem 單元測試
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Taipei'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

# DEFAULT_PERMISSION_CLASSES = AllowAny → 需登入的 view 必須自行設 permission_classes。
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': ('rest_framework.permissions.AllowAny',),
    # OpenAPI 3 schema 由 drf-spectacular 從 view/serializer 推導（code-first，文件不另外手維護）。
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    # 匿名依 IP、登入依 user pk 兩級限流；計數走 default cache（見上 CACHES 區塊）。
    # 設 REDIS_URL 後計數存 Redis、跨 gunicorn worker 一致：原本 LocMemCache 的 per-process
    #   限制（實際上限 ≈ rate × worker 數、重啟歸零）已解。代價：Redis 斷線時 cache.get 拋錯
    #   → 請求 500（限流形同 fail-closed、非靜默放行）；healthz 的 cache check 讓 readiness
    #   如實回 503，交編排系統摘流量。
    # 天花板二：匿名以 IP 識別、DRF 預設信任 X-Forwarded-For → 無代理正規化（NUM_PROXIES）
    #   時可偽造 header 繞過；此限流為縱深防禦，非安全邊界。
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
        # 對未宣告 throttle_scope 的 view 是 no-op；只有標了 scope 的 action 受該桶限制。
        'rest_framework.throttling.ScopedRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/min',
        'user': '300/min',
        # 按成本配桶、非按 URL 前綴：只有 balance-history 是全歷史分組、讀取量隨終身交易數成長，
        # 掛這桶；首頁高頻的 balance/today 維持 user 級，不被連坐限死。
        'reports-heavy': '20/min',
    },
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'Ledger API',
    'DESCRIPTION': '記帳 REST API：JWT 認證、帳戶／分類／標籤／交易／儲蓄目標 CRUD 與報表聚合。',
    'VERSION': '0.9.0',  # 1.0.0 保留給對前端凍結契約的那一版
    'SERVE_INCLUDE_SCHEMA': False,  # /api/schema/ 自身不列為 API 操作
    'SCHEMA_PATH_PREFIX': '/api/',  # tag 分組剝掉共同前綴 → 依 auth／ledger 分組
    'ENUM_NAME_OVERRIDES': {
        # Account.Type 的 choices 同時出現在帳戶 CRUD 與報表信封兩處，自動命名解
        # 不開會產生雜湊尾名（Type346Enum）——釘死名稱，下游型別產生器才有穩定 enum 名。
        # 值必須是「模組層屬性」路徑（import_string 解不開巢狀的 Account.Type.choices）。
        'AccountTypeEnum': 'ledger.schema.ACCOUNT_TYPE_CHOICES',
    },
}

# 12-factor：log 一律進 stdout 由容器平台收（docker logs 直接可讀）。
# Django 預設 LOGGING 的 console handler 掛 require_debug_true，DEBUG=False 的
# 生產容器裡 app log 無處去——故自訂。JSON lines 格式（config/logging.py）：
# 機器可解析、為聚合系統鋪路；gunicorn 自身的 access/error log 不歸本設定管。
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {'()': 'config.logging.JsonFormatter'},
    },
    'handlers': {
        'console': {'class': 'logging.StreamHandler', 'formatter': 'json'},
    },
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {
        # 背景任務沒有 request/response 可看，log 是唯一觀測窗——顯式保 INFO，
        # 不受日後 root 調級影響。
        'ledger': {'level': 'INFO'},
    },
}

# 其餘採 simplejwt 預設（HS256、SIGNING_KEY=SECRET_KEY、Bearer、id/user_id）。
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
}

AUTH_USER_MODEL = 'accounts.CustomUser'

# 預設主鍵型別，跟齊 Django startproject 慣例。
# contrib 釘 AutoField、token_blacklist 釘 BigAutoField，各自 override 不受影響；
# 只作用在沒釘選又有 auto PK 的業務 app（如日後 M2M 中間表的隱式 PK）。
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

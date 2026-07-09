"""Celery app：背景任務與排程的入口。

config/__init__.py import 此模組，Django 一啟動就建好 app 並綁定 settings，
autodiscover 與 @app.task 才有 app 可掛。broker 走 Redis db 1（cache 用 db 0）。
"""

import logging
import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')
# 從 Django settings 讀 CELERY_ 前綴設定（broker／時區／排程…）；worker 與 beat 共用同一份。
app.config_from_object('django.conf:settings', namespace='CELERY')
# 掃 INSTALLED_APPS 各 app 的 tasks 模組（有就自動發現、現無則略過）。
app.autodiscover_tasks()

logger = logging.getLogger(__name__)


@app.task
def heartbeat():
    """基建煙霧任務：beat 每分鐘觸發、log 一筆，證 web→broker→worker→beat 鏈路全通。

    定期定額等業務任務改進 ledger/tasks.py；此煙霧任務隨業務排程上線後可撤。
    """
    logger.info('celery heartbeat')

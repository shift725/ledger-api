"""Celery app：背景任務與排程的入口。

config/__init__.py import 此模組，Django 一啟動就建好 app 並綁定 settings，
autodiscover 與 shared_task 才有 app 可掛。broker 走 Redis db 1（cache 用 db 0）。
"""

import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')
# 從 Django settings 讀 CELERY_ 前綴設定（broker／時區／排程…）；worker 與 beat 共用同一份。
app.config_from_object('django.conf:settings', namespace='CELERY')
# 掃 INSTALLED_APPS 各 app 的 tasks 模組（ledger/tasks.py 由此被發現）。
app.autodiscover_tasks()

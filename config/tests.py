"""config 層測試：healthz 探針與 JSON logging。

unittest 風格（非 pytest 專屬）——容器 runtime image 無 pytest，
`manage.py test` 也要能實跑本檔；本機 pytest 同樣收得到。
"""

import json
import logging
import sys
from datetime import datetime
from unittest import mock

from django.db import DatabaseError
from django.test import Client, SimpleTestCase, TestCase

from config.logging import JsonFormatter


def _record(msg='hello %s', args=('世界',), exc_info=None, level=logging.INFO):
    return logging.LogRecord('ledger.test', level, __file__, 1, msg, args, exc_info)


class JsonFormatterTests(SimpleTestCase):
    def test_output_is_single_line_json_with_required_keys(self):
        line = JsonFormatter().format(_record())
        entry = json.loads(line)
        self.assertNotIn('\n', line)
        self.assertEqual(entry['level'], 'INFO')
        self.assertEqual(entry['logger'], 'ledger.test')
        # getMessage()：args 已代入；ensure_ascii=False：中文原樣不轉 \uXXXX
        self.assertEqual(entry['message'], 'hello 世界')
        self.assertIn('世界', line)
        # timestamp = ISO 8601 帶 offset（可解析、無時區歧義）
        self.assertIsNotNone(datetime.fromisoformat(entry['timestamp']).tzinfo)

    def test_exc_info_appends_traceback_text(self):
        try:
            raise ValueError('boom')
        except ValueError:
            exc_info = sys.exc_info()
        entry = json.loads(JsonFormatter().format(_record(exc_info=exc_info)))
        self.assertIn('ValueError: boom', entry['exc_info'])

    def test_no_exc_info_key_when_absent(self):
        self.assertNotIn('exc_info', json.loads(JsonFormatter().format(_record())))


class HealthzTests(TestCase):
    """healthz 是刻意公開的探針（無業務資料、無副作用）——測試全程匿名打。"""

    def test_ok_when_db_and_cache_reachable(self):
        res = Client().get('/healthz')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {'status': 'ok', 'checks': {'db': 'ok', 'cache': 'ok'}})

    def test_db_failure_returns_503_and_logs_without_leaking_details(self):
        with mock.patch('config.views.connection') as conn:
            conn.cursor.side_effect = DatabaseError('connection refused at 10.0.0.5')
            with self.assertLogs('config.views', level='WARNING'):
                res = Client().get('/healthz')
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json(), {'status': 'unhealthy', 'checks': {'db': 'error'}})
        # 錯誤細節只進 log，不進回應
        self.assertNotIn('10.0.0.5', res.content.decode())

    def test_cache_failure_returns_503_and_logs(self):
        # Redis 斷線＝cache 操作拋錯；db 正常故先過（→ db:ok），cache check 才是不健康點。
        with mock.patch('config.views.cache') as c:
            c.get.side_effect = Exception('connection refused at 10.0.0.9')
            with self.assertLogs('config.views', level='WARNING'):
                res = Client().get('/healthz')
        self.assertEqual(res.status_code, 503)
        self.assertEqual(
            res.json(), {'status': 'unhealthy', 'checks': {'db': 'ok', 'cache': 'error'}}
        )
        self.assertNotIn('10.0.0.9', res.content.decode())

    def test_non_get_rejected(self):
        self.assertEqual(Client().post('/healthz').status_code, 405)


class CelerySmokeTests(SimpleTestCase):
    """Celery 基建煙霧：排程指到的任務真的存在、Django settings 橋到 celery conf。"""

    def test_daily_task_name_matches_schedule(self):
        # beat 只認任務名字串：打錯或改名不會報錯，只會每天安靜地什麼都不做。拿任務物件的
        # name 比對排程，重構改名時這裡會紅。
        # 不查 celery_app.tasks 註冊表：autodiscover 是延遲的（只在 worker 啟動時 import
        # 各 app 的 tasks 模組），web／test 行程裡那張表只有 celery 內建任務。
        from django.conf import settings

        from ledger.tasks import post_due_recurring_rules

        entry = settings.CELERY_BEAT_SCHEDULE['post-due-recurring-rules']
        self.assertEqual(entry['task'], post_due_recurring_rules.name)
        self.assertEqual((entry['schedule'].hour, entry['schedule'].minute), ({0}, {5}))

    def test_django_settings_bridged_to_celery_conf(self):
        # namespace='CELERY' 把 CELERY_ 前綴的 Django 設定讀進 celery conf。用環境無關的兩項驗橋接：
        # task_always_eager 隨有無 broker 變（容器測試吃生產 broker→非 eager），不可當普適斷言。
        from config import celery_app

        self.assertEqual(celery_app.conf.timezone, 'Asia/Taipei')
        self.assertFalse(celery_app.conf.worker_hijack_root_logger)

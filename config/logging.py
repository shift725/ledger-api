"""JSON lines log 格式（一行一個 JSON object，聚合系統可直接解析）。

package 內模組不會 shadow stdlib logging（Python 3 為絕對 import）。
"""

import json
import logging
from datetime import datetime


class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            # ISO 8601 帶 UTC offset：機器可解析且無時區歧義（gunicorn 自身的
            # log 是 UTC、Django 進程是 TIME_ZONE，同一條流不標 offset 會誤判）
            'timestamp': datetime.fromtimestamp(record.created)
            .astimezone()
            .isoformat(timespec='milliseconds'),
            'level': record.levelname,
            'logger': record.name,
            # getMessage() 才會把 args 代入模板；record.msg 是未格式化的原始字串
            'message': record.getMessage(),
        }
        if record.exc_info:
            entry['exc_info'] = self.formatException(record.exc_info)
        # ensure_ascii=False：中文訊息原樣輸出；換行與引號由 json.dumps 轉義，保單行
        return json.dumps(entry, ensure_ascii=False)

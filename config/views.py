"""服務級 view（非業務域）：健康檢查探針。"""

import logging

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


@require_GET
def healthz(request):
    """liveness＋readiness 合一的探針：能回應=進程活著，DB 通=可服務。

    純 Django view，不走 DRF——探針不需要認證/限流/schema，DRF 對它
    全是要顯式關掉的開關；高頻探測（compose healthcheck、LB）因此
    也不占用匿名 throttle 額度，避免 429 造成的假 unhealthy 重啟循環。
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
    except Exception:
        # 任何 DB 層錯誤都=unhealthy（探針不准 500）；細節只進 log，回應不洩內部資訊
        logger.warning('healthz DB check failed', exc_info=True)
        return JsonResponse({'status': 'unhealthy', 'checks': {'db': 'error'}}, status=503)
    return JsonResponse({'status': 'ok', 'checks': {'db': 'ok'}})

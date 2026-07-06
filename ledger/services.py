"""餘額算術與儲蓄目標帶入的服務層。

把「改 balance」這種跨 model 的副作用收斂在這一個檔，view 只負責開交易邊界
（transaction.atomic）並呼叫這裡的純函式；業務邏輯不散落在 view。
"""

from django.db.models import F
from django.utils import timezone

from .models import Account, SavingsGoal, Transaction


def _delta(txn_type, amount):
    """方向化金額：收入為 +amount、支出為 -amount。amount 恆正（model 已約束）。"""
    return amount if txn_type == Transaction.Type.INCOME else -amount


def apply_to_balance(account_id, txn_type, amount):
    """把一筆交易的影響「加」到帳戶餘額（建立交易時用）。

    用 F() 讓加法在 DB 端算：SQL 是 UPDATE ... SET balance = balance + delta，
    對同一列的並發 UPDATE 由 DB 排隊 → 先天無 lost update，不必先讀再寫。

    caveat：F() 更新後，記憶體中的 account.balance 仍是舊值；本次要讀新餘額需
    refresh_from_db()。交易端點回傳不含帳戶餘額、帳戶端點本就重讀 DB，故此處不需要。

    生產走 F()（允許負餘額，不驗）。日後若要「餘額不足擋支出」＝先讀再驗，必須改用
    select_for_update 鎖列後讀→驗→存（F() 無法在同一步驗餘額）。
    """
    Account.objects.filter(pk=account_id).update(balance=F('balance') + _delta(txn_type, amount))


def reverse_from_balance(account_id, txn_type, amount):
    """把一筆交易的影響「減」回去（刪除交易、或編輯時還原舊值用）。"""
    Account.objects.filter(pk=account_id).update(balance=F('balance') - _delta(txn_type, amount))


def carry_forward_savings_goal(user):
    """建交易的副作用：把上月的月度儲蓄目標帶入「真實當下月」（若當下月尚未有）。

    以 timezone.localtime(timezone.now()) 的當下年月為準（與交易的 occurred_at 無關）→
    補登/匯入過去月份的交易不會補建歷史月目標；歷史月若缺由使用者事後手動 CRUD。
    localtime 依 settings.TIME_ZONE 轉時區（目前 Asia/Taipei）→ 當下月綁專案時區、不寫死。

    冪等 + 並發安全：get_or_create 靠唯一約束 (user, period_type, year, month)，
    內部 savepoint 吞 IntegrityError 後重查 → 新月同時兩請求也只生一筆，在外層 atomic 內安全。
    """
    now = timezone.localtime(timezone.now())
    y, m = now.year, now.month
    monthly = SavingsGoal.PeriodType.MONTHLY
    if SavingsGoal.objects.filter(user=user, period_type=monthly, year=y, month=m).exists():
        return
    py, pm = (y - 1, 12) if m == 1 else (y, m - 1)  # 上月；一月跨年
    prev = SavingsGoal.objects.filter(user=user, period_type=monthly, year=py, month=pm).first()
    if prev is None:  # 上月從未設定 → 不建（只複製、不無中生有）
        return
    SavingsGoal.objects.get_or_create(
        user=user,
        period_type=monthly,
        year=y,
        month=m,
        defaults={'amount': prev.amount},
    )

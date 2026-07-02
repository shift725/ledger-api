"""餘額算術與儲蓄目標帶入的服務層。

把「改 balance」這種跨 model 的副作用收斂在這一個檔，view 只負責開交易邊界
（transaction.atomic）並呼叫這裡的純函式；業務邏輯不散落在 view。
"""

from django.db.models import F

from .models import Account, Transaction


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

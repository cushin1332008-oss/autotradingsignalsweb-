from datetime import datetime

from zoneinfo import ZoneInfo

VN=ZoneInfo("Asia/Ho_Chi_Minh")

def vn_now():

    return datetime.now(VN)

def vn_string():

    return vn_now().strftime("%H:%M:%S %d/%m/%Y")

# 測試期間封鎖上網（tests/run_all.py 將呢個 folder 加入 PYTHONPATH，Python 開機自動載入）。
# 測試應該全部用假數據、假 AI；有邊個步驟偷偷上網，就會即刻見到「測試唔准上網」。
import socket


def _blocked(*a, **k):
    raise OSError("測試唔准上網（tests/_guard/sitecustomize.py）")


socket.getaddrinfo = _blocked
socket.create_connection = _blocked
socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked

# -*- coding: utf-8 -*-
"""实时增量同步测试：模拟 author 发送新笔画/viewport/undo，应实时到达已连接的 viewer"""
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_ws as tw  # noqa: E402 复用 WsClient

# author 连接（模拟平板）
author = tw.WsClient()
assert '101' in author.handshake()
author.send({'t': 'hello', 'role': 'author'})
json.loads(author.recv_text())  # hello reply

# 发一条新笔画（绿色不常用，用红色）
author.send({'t': 'evt', 'e': {'t': 'stroke', 'id': 'live1', 'tool': 'pen',
                               'color': '#e53935', 'w': 3,
                               'pts': [[0, 0], [20, 30], [40, 60]], 'done': True}})
time.sleep(0.3)
# 发 viewport 变化（模拟双指平移缩放）
author.send({'t': 'evt', 'e': {'t': 'viewport', 'x': -500, 'y': -600, 's': 1.8,
                               'w': 800, 'h': 600}})
time.sleep(0.3)
# 撤销
author.send({'t': 'evt', 'e': {'t': 'undo'}})
time.sleep(0.3)
print('author events sent: stroke(live1), viewport, undo')
author.close()

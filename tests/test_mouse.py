# -*- coding: utf-8 -*-
"""直接向服务器发送 mouse 注入消息，验证 SendInput 注入链路
用法: python test_mouse.py [端口]   (默认 80)
"""
import ctypes
import json
import os
import sys
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_ws as tw

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 80

def get_cursor():
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y

m = tw.WsClient(PORT)
assert '101' in m.handshake()
m.send({'t': 'hello', 'role': 'mouse'})
print('hello:', m.recv_text()[:100])

# 移动到归一化 (0.1, 0.1)
m.send({'t': 'mouse', 'x': 0.1, 'y': 0.1, 'a': 'move'})
time.sleep(0.4)
print('after move 0.1,0.1 -> cursor', get_cursor())

# down
m.send({'t': 'mouse', 'x': 0.5, 'y': 0.5, 'a': 'down'})
time.sleep(0.4)
print('after down 0.5,0.5 -> cursor', get_cursor())

# up
m.send({'t': 'mouse', 'x': 0.5, 'y': 0.5, 'a': 'up'})
time.sleep(0.4)
print('after up -> cursor', get_cursor())

# 再移动到 0.9, 0.9 验证大范围
m.send({'t': 'mouse', 'x': 0.9, 'y': 0.9, 'a': 'move'})
time.sleep(0.4)
print('after move 0.9,0.9 -> cursor', get_cursor())

print('injection messages sent')
m.close()

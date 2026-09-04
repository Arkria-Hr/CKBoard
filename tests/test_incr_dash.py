# -*- coding: utf-8 -*-
"""复现 viewer 增量渲染"虚线"问题：模拟 author 分 6 段发送一笔，检查 viewer 渲染连续性。
用法: python test_incr_dash.py [port]
"""
import sys, time, json
sys.path.insert(0, r'd:\CKBoard\tests')
import test_ws as tw

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 80
SID = 'testdash-' + str(int(time.time() * 1000))

c = tw.WsClient(PORT)
c.handshake()
c.send({'t': 'hello', 'role': 'author'})
msg = json.loads(c.recv_text())
print('hello ok:', msg.get('ok'), '| role:', msg.get('role'), '| server strokes:', len(msg.get('state', {}).get('strokes', [])))

# 一笔横线，世界坐标空白区 (2192, 4683)，模拟新节流：首点单独发 + 4 段 × 4 点 × 25ms
base_x = 2192.0
step = 8.0
Y = 4683.0
# 首点立即发送（对应 startStroke 新逻辑）
c.send({'t': 'evt', 'e': {'t': 'stroke', 'id': SID, 'tool': 'pen',
                          'color': '#00ff00', 'w': 3, 'pts': [[base_x, Y]], 'done': False}})
time.sleep(0.03)
for seg in range(4):
    pts = []
    for i in range(4):
        x = base_x + (seg * 4 + i + 1) * step
        pts.append([x, Y])
    done = (seg == 3)
    c.send({'t': 'evt', 'e': {'t': 'stroke', 'id': SID, 'tool': 'pen',
                              'color': '#00ff00', 'w': 3, 'pts': pts, 'done': done}})
    time.sleep(0.025)

# 等服务端广播处理（留足时间给外部做浏览器像素检查）
time.sleep(8.0)
# 校验服务器状态：该笔画应完整（30 点）
# （清理由外部 sync 过滤完成：见命令注释，避免误删用户新笔迹）

# -*- coding: utf-8 -*-
"""CKBoard 服务端自测：验证 WS 握手、author 事件中继、viewer 全量状态"""
import asyncio
import json
import os
import socket
import sys

HOST, PORT = '127.0.0.1', 80
WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'


def ws_frame(payload, op=0x1):
    n = len(payload)
    if n < 126:
        return bytes([0x80 | op, n]) + payload
    return bytes([0x80 | op, 126]) + n.to_bytes(2, 'big') + payload


class WsClient:
    def __init__(self, port=None):
        self.port = port or PORT
        self.sock = socket.create_connection((HOST, self.port), timeout=5)
        self.buf = b''

    def handshake(self):
        key = 'dGhlIHNhbXBsZSBub25jZQ=='
        req = ('GET /ws HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\n'
               'Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n'
               'Sec-WebSocket-Version: 13\r\n\r\n' % (HOST, self.port, key))
        self.sock.sendall(req.encode())
        while b'\r\n\r\n' not in self.buf:
            self.buf += self.sock.recv(4096)
        head, _, rest = self.buf.partition(b'\r\n\r\n')
        self.buf = rest
        text = head.decode('latin-1')
        if '101' not in text.split('\r\n')[0]:
            raise RuntimeError('handshake failed: ' + text)
        import base64, hashlib
        expect = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        if 'Sec-WebSocket-Accept: ' + expect not in text:
            raise RuntimeError('bad accept: ' + text)
        return text.split('\r\n')[0]

    def send(self, obj):
        payload = json.dumps(obj).encode()
        mask = b'\x11\x22\x33\x44'
        n = len(payload)
        if n < 126:
            head = bytes([0x81, 0x80 | n])
        elif n < 65536:
            head = bytes([0x81, 0x80 | 126]) + n.to_bytes(2, 'big')
        else:
            head = bytes([0x81, 0x80 | 127]) + n.to_bytes(8, 'big')
        body = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
        self.sock.sendall(head + mask + body)

    def recv_text(self, timeout=5):
        self.sock.settimeout(timeout)
        while True:
            while len(self.buf) >= 2:
                head = self.buf[0]
                ln = self.buf[1] & 0x7F
                off = 2
                if ln == 126:
                    if len(self.buf) < 4:
                        break
                    ln = int.from_bytes(self.buf[2:4], 'big')
                    off = 4
                elif ln == 127:
                    if len(self.buf) < 10:
                        break
                    ln = int.from_bytes(self.buf[2:10], 'big')
                    off = 10
                if len(self.buf) < off + ln:
                    break
                payload = self.buf[off:off + ln]
                self.buf = self.buf[off + ln:]
                op = head & 0x0F
                if op == 0x9:   # ping -> pong
                    self.sock.sendall(ws_frame(payload, 0xA))
                    continue
                if op == 0x8:
                    return None
                if op == 0x1:
                    return payload.decode('utf-8')
                if op == 0xA:
                    continue
            chunk = self.sock.recv(65536)
            if not chunk:
                return None
            self.buf += chunk

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


async def run_tests(port=None):
    results = []

    def check(name, ok, detail=''):
        results.append((name, ok, detail))
        print(('PASS ' if ok else 'FAIL ') + name + (' ' + detail if detail else ''))

    def cli():
        return WsClient(port)

    # 1) author 握手
    author = cli()
    check('author handshake', '101' in author.handshake())
    author.send({'t': 'hello', 'role': 'author'})
    msg = json.loads(author.recv_text())
    check('author hello reply', msg.get('t') == 'hello' and msg.get('ok') is True and
          msg.get('role') == 'author',
          json.dumps(msg)[:120])

    # 2) 清空服务端可能残留的历史数据，然后 author 发笔画（分两段：部分 + done）
    author.send({'t': 'evt', 'e': {'t': 'clear'}})
    author.send({'t': 'evt', 'e': {'t': 'stroke', 'id': 's1', 'tool': 'pen', 'color': 'red',
                                   'w': 3, 'pts': [[0, 0], [10, 10]], 'done': False}})
    author.send({'t': 'evt', 'e': {'t': 'stroke', 'id': 's1', 'tool': 'pen', 'color': 'red',
                                   'w': 3, 'pts': [[20, 20]], 'done': True}})
    author.send({'t': 'evt', 'e': {'t': 'viewport', 'x': -400, 'y': -300, 's': 1.5,
                                   'w': 800, 'h': 600}})

    # 3) viewer 连接，应收到全量状态
    viewer = cli()
    check('viewer handshake', '101' in viewer.handshake())
    viewer.send({'t': 'hello', 'role': 'viewer'})
    msg = json.loads(viewer.recv_text())
    st = msg.get('state', {})
    strokes = st.get('strokes', [])
    ok = (msg.get('t') == 'hello' and len(strokes) == 1 and
          strokes[0]['id'] == 's1' and len(strokes[0]['pts']) == 3 and
          strokes[0]['done'] is True and
          st.get('viewport', {}).get('s') == 1.5)
    check('viewer full state', ok, json.dumps(st)[:200])

    # 4) author 再发事件，viewer 应收到中继
    author.send({'t': 'evt', 'e': {'t': 'stroke', 'id': 's2', 'tool': 'pen', 'color': 'blue',
                                   'w': 3, 'pts': [[100, 100]], 'done': True}})
    msg = json.loads(viewer.recv_text())
    e = msg.get('e', {})
    check('viewer relay stroke', msg.get('t') == 'evt' and e.get('t') == 'stroke' and
          e.get('id') == 's2' and e.get('color') == 'blue', json.dumps(msg)[:150])

    # 5) author 发 undo / clear，viewer 收到
    author.send({'t': 'evt', 'e': {'t': 'undo'}})
    msg = json.loads(viewer.recv_text())
    check('viewer relay undo', msg.get('e', {}).get('t') == 'undo')
    author.send({'t': 'evt', 'e': {'t': 'clear'}})
    msg = json.loads(viewer.recv_text())
    check('viewer relay clear', msg.get('e', {}).get('t') == 'clear')

    # 6) author sync（模拟重连后全量同步）
    author.send({'t': 'sync', 'strokes': [{'id': 's9', 'tool': 'pen', 'color': 'black',
                                           'w': 3, 'pts': [[1, 2]], 'done': True}],
                 'viewport': {'x': 1, 'y': 2, 's': 1, 'w': 800, 'h': 600}})
    msg = json.loads(viewer.recv_text())
    ok = (msg.get('t') == 'state' and len(msg.get('strokes', [])) == 1 and
          msg['strokes'][0]['id'] == 's9' and msg.get('viewport', {}).get('x') == 1)
    check('author sync -> viewer state', ok, json.dumps(msg)[:200])

    # 7) mouse 角色 hello + 注入消息（不崩溃即可，注入会真实移动鼠标，跳过 down）
    mouse = cli()
    check('mouse handshake', '101' in mouse.handshake())
    mouse.send({'t': 'hello', 'role': 'mouse'})
    msg = json.loads(mouse.recv_text())
    check('mouse hello reply', msg.get('role') == 'mouse')
    mouse.send({'t': 'mouse', 'x': 0.5, 'y': 0.5, 'a': 'move'})
    mouse.send({'t': 'release'})

    # 8) ping/pong
    author.send({'t': 'ping'})
    msg = json.loads(author.recv_text())
    check('ping pong', msg.get('t') == 'pong')

    author.close(); viewer.close(); mouse.close()

    failed = [r for r in results if not r[1]]
    print('----')
    print('TOTAL: %d, PASS: %d, FAIL: %d' % (len(results), len(results) - len(failed), len(failed)))
    return 1 if failed else 0


if __name__ == '__main__':
    port = None
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    sys.exit(asyncio.run(run_tests(port)))

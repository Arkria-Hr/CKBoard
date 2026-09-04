#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CKBoard 服务端
================
功能（两种模式，都走 WiFi，浏览器直连，无需装任何 App）：
  1. 白板镜像（高级方案）：平板浏览器书写 -> 电脑浏览器同步显示同一张纸
  2. 触控板（基础方案）  ：平板浏览器把触摸位置映射为电脑鼠标（可配合任意画图软件）

零第三方依赖，Python 3.7+ 标准库即可运行（含手写 WebSocket RFC6455 实现）。

用法：
    python server.py [--port 80] [--no-browser]

平板浏览器打开:  http://<本机局域网IP>          （书写白板，默认端口 80）
电脑镜像窗口:    http://127.0.0.1/?role=viewer （共享给腾讯会议）
触控板模式:      http://<IP>/tp
（80 端口被占用时自动回退 8180，回退后地址带端口号）
"""

import argparse
import asyncio
import base64
import ctypes
import hashlib
import json
import os
import socket
import sys
import time
import urllib.parse
import webbrowser
from ctypes import wintypes

WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
MAX_STROKES = 4000          # 服务端最多保留的笔画数
HEARTBEAT_INTERVAL = 20     # 心跳间隔（秒）
DEAD_AFTER = 45             # 超过该时长无任何消息即视为断线

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')

# ---------------------------------------------------------------------------
# 鼠标注入（Windows SendInput，触控板模式用）
# ---------------------------------------------------------------------------
_mouse_ready = False
_mouse_input = None


def _mouse_init():
    """初始化 ctypes SendInput（x64 下必须设置 argtypes，否则指针截断）"""
    global _mouse_ready, _mouse_input
    if _mouse_ready:
        return True
    try:
        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ('dx', wintypes.LONG),
                ('dy', wintypes.LONG),
                ('mouseData', wintypes.DWORD),
                ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD),
                ('dwExtraInfo', ctypes.POINTER(ctypes.c_ulong)),
            ]

        class INPUTUNION(ctypes.Union):
            _fields_ = [('mi', MOUSEINPUT)]

        class INPUT(ctypes.Structure):
            _anonymous_ = ('u',)
            _fields_ = [('type', wintypes.DWORD), ('u', INPUTUNION)]

        fn = ctypes.windll.user32.SendInput
        fn.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        fn.restype = wintypes.UINT
        _mouse_input = (fn, INPUT, MOUSEINPUT, INPUTUNION)
        _mouse_ready = True
        return True
    except Exception:
        return False


def _send_mouse(flags, nx=0.5, ny=0.5):
    if not _mouse_init():
        return
    fn, INPUT, MOUSEINPUT, INPUTUNION = _mouse_input
    nx = 0.0 if nx < 0 else (1.0 if nx > 1 else nx)
    ny = 0.0 if ny < 0 else (1.0 if ny > 1 else ny)
    mi = MOUSEINPUT(int(nx * 65535), int(ny * 65535), 0, flags, 0, None)
    inp = INPUT(type=0, u=INPUTUNION(mi=mi))
    try:
        fn(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    except Exception:
        pass


def mouse_move_abs(nx, ny):
    _send_mouse(0x0001 | 0x8000, nx, ny)   # MOVE | ABSOLUTE


def mouse_down():
    _send_mouse(0x0002)                    # LEFTDOWN


def mouse_up():
    _send_mouse(0x0004)                    # LEFTUP


# ---------------------------------------------------------------------------
# WebSocket 帧编解码（RFC6455，仅文本帧 + 控制帧）
# ---------------------------------------------------------------------------
def ws_frame(payload, op=0x1):
    """服务端发帧（不掩码）"""
    n = len(payload)
    if n < 126:
        head = bytes([0x80 | op, n])
    elif n < 65536:
        head = bytes([0x80 | op, 126]) + n.to_bytes(2, 'big')
    else:
        head = bytes([0x80 | op, 127]) + n.to_bytes(8, 'big')
    return head + payload


async def ws_recv(reader):
    """读一帧（自动拼接分片）。返回 (payload, kind)，kind 为 text/ping/pong/close/bad"""
    buf = bytearray()
    first_op = None
    while True:
        head = await reader.readexactly(2)
        fin = head[0] & 0x80
        op = head[0] & 0x0F
        masked = head[1] & 0x80
        ln = head[1] & 0x7F
        if ln == 126:
            ln = int.from_bytes(await reader.readexactly(2), 'big')
        elif ln == 127:
            ln = int.from_bytes(await reader.readexactly(8), 'big')
        key = None
        if masked:
            key = await reader.readexactly(4)
        payload = await reader.readexactly(ln) if ln else b''
        if masked:
            payload = bytes(b ^ key[i & 3] for i, b in enumerate(payload))
        if op == 0x0:                      # continuation
            buf += payload
            if fin:
                return bytes(buf), ('text' if first_op == 0x1 else 'bad')
        elif op == 0x1:                    # text
            buf += payload
            first_op = 0x1
            if fin:
                return bytes(buf), 'text'
        elif op == 0x8:                    # close
            return payload, 'close'
        elif op == 0x9:                    # ping
            return payload, 'ping'
        elif op == 0xA:                    # pong
            return payload, 'pong'
        else:
            return payload, 'bad'


# ---------------------------------------------------------------------------
# 白板状态
# ---------------------------------------------------------------------------
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
# 支持环境变量 CKBOARD_SAVE 指定数据文件（便于测试隔离，不影响线上数据）
SAVE_PATH = os.environ.get('CKBOARD_SAVE') or os.path.join(DATA_DIR, 'board.json')
SAVE_DELAY = 1.0    # 变更后延迟保存（秒），防抖避免频繁写盘


class Board:
    def __init__(self):
        self.strokes = []       # [{id, tool, color, w, pts:[[x,y],...], done}]
        self.viewport = None    # {x, y, s, w, h}（author 的视口）
        self._save_task = None
        self.load()

    def snapshot(self):
        return {'strokes': self.strokes, 'viewport': self.viewport}

    def apply(self, e):
        t = e.get('t')
        if t == 'stroke':
            st = None
            for s in reversed(self.strokes):
                if s['id'] == e['id']:
                    st = s
                    break
            if st is None:
                self.strokes.append(e)
                if len(self.strokes) > MAX_STROKES:
                    self.strokes = self.strokes[-MAX_STROKES:]
            else:
                st['pts'].extend(e.get('pts', []))
                if e.get('done'):
                    st['done'] = True
        elif t == 'undo':
            if self.strokes:
                self.strokes.pop()
        elif t == 'clear':
            self.strokes = []
        elif t == 'viewport':
            self.viewport = {k: e.get(k) for k in ('x', 'y', 's', 'w', 'h')}
        self._changed()

    def replace(self, strokes, viewport):
        self.strokes = strokes if isinstance(strokes, list) else []
        self.viewport = viewport
        self._changed()

    # ---- 磁盘持久化（服务重启后笔记不丢） ----
    def _changed(self):
        if self._save_task is not None:
            return

        async def _later():
            await asyncio.sleep(SAVE_DELAY)
            self._save_task = None
            self.save()

        try:
            self._save_task = asyncio.create_task(_later())
        except RuntimeError:
            pass   # 事件循环未运行（如仅做单元测试）

    def save(self):
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = SAVE_PATH + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({'strokes': self.strokes, 'viewport': self.viewport}, f)
            os.replace(tmp, SAVE_PATH)
        except Exception:
            pass

    def load(self):
        try:
            with open(SAVE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            st = data.get('strokes')
            if isinstance(st, list):
                self.strokes = st[-MAX_STROKES:]
            vp = data.get('viewport')
            if isinstance(vp, dict):
                self.viewport = vp
        except (OSError, ValueError):
            pass


# ---------------------------------------------------------------------------
# 连接与会话
# ---------------------------------------------------------------------------
class Client:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.role = None        # author / viewer / mouse
        self.last_recv = time.time()


clients = set()
board = Board()


def clamp01(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.5
    return 0.0 if v < 0 else (1.0 if v > 1 else v)


async def send_json(conn, obj):
    try:
        conn.writer.write(ws_frame(json.dumps(obj, ensure_ascii=False).encode('utf-8')))
        await conn.writer.drain()
    except Exception:
        pass


async def broadcast_viewers(msg, exclude=None):
    for c in list(clients):
        if c.role == 'viewer' and c is not exclude:
            await send_json(c, msg)


async def handle_text(conn, text):
    try:
        d = json.loads(text)
    except Exception:
        return
    t = d.get('t')
    if t == 'hello':
        conn.role = d.get('role') or 'viewer'
        await send_json(conn, {'t': 'hello', 'ok': True, 'role': conn.role,
                               'state': board.snapshot()})
    elif t == 'ping':
        await send_json(conn, {'t': 'pong'})
    elif t == 'evt':
        e = d.get('e')
        if not isinstance(e, dict):
            return
        if conn.role == 'author':
            board.apply(e)
            await broadcast_viewers({'t': 'evt', 'e': e})
    elif t == 'sync':
        if conn.role == 'author':
            board.replace(d.get('strokes'), d.get('viewport'))
            await broadcast_viewers({'t': 'state',
                                     'strokes': board.strokes,
                                     'viewport': board.viewport})
    elif t == 'mouse':
        if conn.role == 'mouse':
            x = clamp01(d.get('x'))
            y = clamp01(d.get('y'))
            a = d.get('a')
            if a == 'move':
                mouse_move_abs(x, y)
            elif a == 'down':
                mouse_move_abs(x, y)
                mouse_down()
            elif a == 'up':
                mouse_move_abs(x, y)
                mouse_up()
    elif t == 'release':
        if conn.role == 'mouse':
            mouse_up()


async def ws_loop(conn):
    hb = asyncio.create_task(heartbeat(conn))
    try:
        while True:
            payload, kind = await ws_recv(conn.reader)
            conn.last_recv = time.time()
            if kind == 'close':
                try:
                    conn.writer.write(ws_frame(b'', 0x8))
                    await conn.writer.drain()
                except Exception:
                    pass
                break
            if kind == 'ping':
                try:
                    conn.writer.write(ws_frame(payload, 0xA))
                    await conn.writer.drain()
                except Exception:
                    pass
                continue
            if kind == 'pong':
                continue
            if kind == 'text':
                await handle_text(conn, payload.decode('utf-8', 'replace'))
            else:
                break
    except (ConnectionError, asyncio.IncompleteReadError, OSError):
        pass
    finally:
        hb.cancel()
        try:
            conn.writer.close()
        except Exception:
            pass


async def heartbeat(conn):
    """定期 ping；长时间无任何消息则关闭（探测死连接）"""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        if time.time() - conn.last_recv > DEAD_AFTER:
            try:
                conn.writer.close()
            except Exception:
                pass
            return
        try:
            conn.writer.write(ws_frame(b'', 0x9))
            await conn.writer.drain()
        except Exception:
            return


# ---------------------------------------------------------------------------
# HTTP 部分（静态页面 + WebSocket 升级）
# ---------------------------------------------------------------------------
ROUTES = {'/': 'index.html', '/index.html': 'index.html', '/app.js': 'app.js',
          '/touchpad.html': 'touchpad.html', '/tp': 'touchpad.html'}
MIME = {'.html': 'text/html; charset=utf-8',
        '.js': 'application/javascript; charset=utf-8'}


async def respond(writer, code, body=b'', ctype='text/plain'):
    reason = {200: 'OK', 400: 'Bad Request', 404: 'Not Found',
              405: 'Method Not Allowed'}.get(code, '')
    head = ('HTTP/1.1 %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n'
            'Connection: close\r\nCache-Control: no-store\r\n\r\n'
            % (code, reason, ctype, len(body)))
    try:
        writer.write(head.encode('ascii') + body)
        await writer.drain()
        writer.close()
    except Exception:
        pass


async def serve_static(writer, path):
    name = ROUTES.get(path)
    if name is None:
        await respond(writer, 404, b'not found')
        return
    fp = os.path.join(ROOT, name)
    try:
        with open(fp, 'rb') as f:
            body = f.read()
    except OSError:
        await respond(writer, 404, b'not found')
        return
    ext = os.path.splitext(name)[1]
    await respond(writer, 200, body, MIME.get(ext, 'application/octet-stream'))


async def handle_http(reader, writer):
    try:
        raw = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), timeout=15)
    except Exception:
        try:
            writer.close()
        except Exception:
            pass
        return
    try:
        text = raw.decode('latin-1')
        lines = text.split('\r\n')
        req = lines[0].split(' ')
        if len(req) < 2:
            raise ValueError
        method, path = req[0], urllib.parse.urlsplit(req[1]).path
        headers = {}
        for ln in lines[1:]:
            if ':' in ln:
                k, v = ln.split(':', 1)
                headers[k.strip().lower()] = v.strip()
    except Exception:
        writer.close()
        return

    if method != 'GET':
        await respond(writer, 405, b'method not allowed')
        return

    if path == '/ws':
        key = headers.get('sec-websocket-key', '')
        if not key:
            await respond(writer, 400, b'bad request')
            return
        accept = base64.b64encode(
            hashlib.sha1((key + WS_GUID).encode('ascii')).digest()).decode('ascii')
        writer.write(('HTTP/1.1 101 Switching Protocols\r\n'
                      'Upgrade: websocket\r\n'
                      'Connection: Upgrade\r\n'
                      'Sec-WebSocket-Accept: ' + accept + '\r\n\r\n').encode('ascii'))
        await writer.drain()
        # 禁用 Nagle 算法：小包（WS JSON 帧）立即发送，避免最多 40ms 延迟等待
        try:
            sock = writer.get_extra_info('socket')
            if sock is not None:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        conn = Client(reader, writer)
        clients.add(conn)
        try:
            await ws_loop(conn)
        finally:
            clients.discard(conn)
        return

    await serve_static(writer, path)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def lan_ips():
    """尽力找出本机局域网 IP（供平板访问）"""
    ips = []
    for host in ('192.168.1.1', '192.168.0.1', '223.5.5.5'):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((host, 80))
            ip = s.getsockname()[0]
            s.close()
            if ip not in ips and not ip.startswith('127.'):
                ips.append(ip)
        except Exception:
            pass
    if not ips:
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ip = info[4][0]
                if not ip.startswith('127.') and ip not in ips:
                    ips.append(ip)
        except Exception:
            pass

    def key(ip):
        return (0 if ip.startswith('192.168.') else
                1 if ip.startswith('10.') else 2, ip)
    ips.sort(key=key)
    return ips


async def main():
    parser = argparse.ArgumentParser(description='CKBoard server')
    parser.add_argument('--port', type=int, default=80)
    parser.add_argument('--no-browser', action='store_true',
                        help='启动后不自动打开电脑镜像窗口')
    args = parser.parse_args()

    port = args.port
    try:
        server = await asyncio.start_server(handle_http, '0.0.0.0', port)
    except OSError:
        # 默认 80 被占用等情况下回退到 8180
        if port == 8180:
            raise
        print('端口 %d 不可用，回退到 8180' % port)
        port = 8180
        server = await asyncio.start_server(handle_http, '0.0.0.0', port)
    ips = lan_ips()
    port_str = '' if port == 80 else ':%d' % port

    print('=' * 56)
    print(' CKBoard 白板服务已启动')
    print('=' * 56)
    if ips:
        print(' 平板浏览器打开:  http://%s%s        (书写白板)' % (ips[0], port_str))
    print(' 电脑镜像窗口:    http://127.0.0.1:%d/?role=viewer' % port)
    print(' 触控板模式:      http://127.0.0.1:%d/tp' % port)
    if len(ips) > 1:
        print(' (候选局域网地址: %s)' % ', '.join(ips))
    print(' 按 Ctrl+C 停止服务')
    print('=' * 56)

    if not args.no_browser:
        async def _open_viewer():
            await asyncio.sleep(1.2)
            try:
                webbrowser.open('http://127.0.0.1:%d/?role=viewer' % port)
            except Exception:
                pass
        asyncio.create_task(_open_viewer())

    async with server:
        try:
            await server.serve_forever()
        finally:
            board.save()   # 退出前把最后状态落盘


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
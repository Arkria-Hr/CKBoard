/* CKBoard 白板 —— author/viewer 双角色，ES5 语法以兼容老平板浏览器 */
(function () {
'use strict';

/* ================= 常量 ================= */
var PEN_W = 3;              // 笔宽（世界坐标单位）
var ERASER_W = 26;          // 橡皮宽度
var MIN_S = 0.05, MAX_S = 10;
var SEND_STROKE_MS = 25;    // 笔画增量发送节流（25ms，降低书写延迟）
var SEND_STROKE_N = 4;      // 每攒够 N 点也发送
var SEND_VP_MS = 120;       // 视口发送节流
var RENDER_MS = 40;         // 视口重绘节流

/* ================= 工具 ================= */
function clamp(v, a, b) { return v < a ? a : (v > b ? b : v); }
function uid() {
    return 's' + Date.now().toString(36) + '-' + Math.floor(Math.random() * 1e9).toString(36);
}

/* ================= 角色 ================= */
var m = /[?&]role=(author|viewer)/.exec(location.search);
var ROLE = m ? m[1] : 'author';

/* ================= 画布 / 渲染 ================= */
var cv = document.getElementById('cv');
var ctx = cv.getContext('2d');
var vp = { x: 0, y: 0, s: 1, w: 1280, h: 800 };   // 视口：世界坐标原点 + 缩放
var cssW = 0, cssH = 0, dpr = 1;
var first = true;

/* 笔画库 */
var store = { list: [] };
store.find = function (id) {
    var l = store.list;
    for (var i = l.length - 1; i >= 0; i--) {
        if (l[i].id === id) return l[i];
    }
    return null;
};
store.applyEvent = function (e) {
    if (e.t === 'stroke') {
        var st = store.find(e.id);
        if (!st) {
            store.list.push({ id: e.id, tool: e.tool, color: e.color, w: e.w,
                              pts: e.pts.slice(), done: !!e.done, _drawn: 0 });
            return true;
        }
        for (var i = 0; i < e.pts.length; i++) st.pts.push(e.pts[i]);
        if (e.done) st.done = true;
        return true;
    }
    if (e.t === 'undo') { if (store.list.length) store.list.pop(); return true; }
    if (e.t === 'clear') { store.list = []; return true; }
    return false;
};

function resize() {
    cssW = window.innerWidth;
    cssH = window.innerHeight;
    dpr = window.devicePixelRatio || 1;
    cv.style.width = cssW + 'px';
    cv.style.height = cssH + 'px';
    cv.width = Math.round(cssW * dpr);
    cv.height = Math.round(cssH * dpr);
    if (ROLE === 'author') {
        if (first) { vp.x = -cssW / 2; vp.y = -cssH / 2; vp.s = 1; first = false; }
        vp.w = cssW; vp.h = cssH;
    }
    requestDraw();
}

/* 渲染变换（CSS 像素系）：screen = (world - vp.xy) * s + ox,oy */
function transform() {
    if (ROLE === 'viewer') {
        var pad = 20;
        /* fit 用 vp.w/vp.h（平板窗口 CSS 尺寸）作分母：
           平板矩形世界宽 = vp.w/vp.s，映射后屏幕宽 = vp.w*fit，需 ≤ 窗口宽 */
        var fit = Math.min(1, (cssW - 2 * pad) / Math.max(1, vp.w),
                           (cssH - 2 * pad) / Math.max(1, vp.h));
        var s = vp.s * fit;
        /* 平板矩形的屏幕尺寸 = vp.w*fit × vp.h*fit（居中显示） */
        var sw = vp.w * fit, sh = vp.h * fit;
        return { s: s, ox: (cssW - sw) / 2, oy: (cssH - sh) / 2 };
    }
    return { s: vp.s, ox: 0, oy: 0 };
}
function applyT(t) {
    ctx.setTransform(t.s * dpr, 0, 0, t.s * dpr,
                     t.ox * dpr - vp.x * t.s * dpr, t.oy * dpr - vp.y * t.s * dpr);
}

var rafId = 0;
function requestDraw() {
    if (rafId) return;
    rafId = requestAnimationFrame(function () { rafId = 0; draw(); });
}
function draw() {
    var t = transform();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, cssW, cssH);
    applyT(t);
    drawGrid();
    var list = store.list;
    for (var i = 0; i < list.length; i++) drawStroke(list[i]);
    if (ROLE === 'viewer') drawFrame();
}

function drawStroke(st) {
    var pts = st.pts, n = pts.length;
    if (!n) return;
    var er = st.tool === 'eraser';
    ctx.save();
    if (er) ctx.globalCompositeOperation = 'destination-out';
    ctx.strokeStyle = er ? '#000' : st.color;
    ctx.fillStyle = er ? '#000' : st.color;
    ctx.lineWidth = st.w;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (var i = 1; i < n; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    if (n === 1) {
        ctx.arc(pts[0][0], pts[0][1], st.w / 2, 0, Math.PI * 2);
        ctx.fill();
    } else {
        ctx.stroke();
    }
    ctx.restore();
}

function drawGrid() {
    var step = 40;
    if (vp.s * step < 12) step = 200;
    else if (vp.s * step < 36) step = 100;
    var x0 = Math.floor(vp.x / step) * step;
    var y0 = Math.floor(vp.y / step) * step;
    var x1 = vp.x + cssW / vp.s, y1 = vp.y + cssH / vp.s;
    ctx.fillStyle = 'rgba(0,0,0,0.10)';
    var r = Math.max(0.8, 1.6 / vp.s);
    for (var x = x0; x <= x1; x += step) {
        for (var y = y0; y <= y1; y += step) {
            ctx.fillRect(x - r / 2, y - r / 2, r, r);
        }
    }
}

function drawFrame() {
    ctx.save();
    ctx.strokeStyle = 'rgba(50,90,180,0.55)';
    ctx.lineWidth = 1.5 / vp.s;
    ctx.strokeRect(vp.x, vp.y, vp.w, vp.h);
    ctx.restore();
}

/* 增量绘制：线段 */
function drawSegment(st, p0, p1) {
    var t = transform();
    applyT(t);
    ctx.save();
    var er = st.tool === 'eraser';
    if (er) ctx.globalCompositeOperation = 'destination-out';
    ctx.strokeStyle = er ? '#000' : st.color;
    ctx.fillStyle = er ? '#000' : st.color;
    ctx.lineWidth = st.w;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.beginPath();
    ctx.moveTo(p0[0], p0[1]);
    ctx.lineTo(p1[0], p1[1]);
    ctx.stroke();
    ctx.restore();
}

/* 增量绘制：单点 */
function drawDot(st, p) {
    var t = transform();
    applyT(t);
    ctx.save();
    var er = st.tool === 'eraser';
    if (er) ctx.globalCompositeOperation = 'destination-out';
    ctx.fillStyle = er ? '#000' : st.color;
    ctx.beginPath();
    ctx.arc(p[0], p[1], st.w / 2, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
}

/* 增量绘制（viewer 收到笔画事件时用）：从上次已画位置连续画到末尾，
   避免多段增量只画最后一段而出现“虚线” */
function drawIncremental(e) {
    var st = store.find(e.id);
    if (!st || !st.pts.length) return;
    var pts = st.pts, n = pts.length;
    var from = st._drawn || 0;
    if (from >= n) { st._drawn = n; return; }
    if (n === 1) {
        drawDot(st, pts[0]);
    } else {
        if (from === 0) from = 1;
        for (var i = from; i < n; i++) drawSegment(st, pts[i - 1], pts[i]);
    }
    st._drawn = n;
}

/* ================= 网络 ================= */
var net = { ws: null, retry: 0, closed: false, role: ROLE };

net.connect = function () {
    if (net.closed) return;
    var proto = location.protocol === 'https:' ? 'wss' : 'ws';
    var ws = new WebSocket(proto + '://' + location.host + '/ws');
    net.ws = ws;
    ws.onopen = function () {
        net.retry = 0;
        setStatus(true);
        ws.send(JSON.stringify({ t: 'hello', role: net.role }));
    };
    ws.onmessage = function (ev) {
        var d;
        try { d = JSON.parse(ev.data); } catch (e) { return; }
        net.onMessage(d);
    };
    ws.onclose = function () { setStatus(false); net.schedule(); };
    ws.onerror = function () { try { ws.close(); } catch (e) {} };
};
net.schedule = function () {
    net.retry = Math.min(net.retry + 1, 8);
    setTimeout(net.connect, 1000 * net.retry);
};
net.send = function (obj) {
    if (net.ws && net.ws.readyState === 1) {
        try { net.ws.send(JSON.stringify(obj)); return true; } catch (e) { return false; }
    }
    return false;
};
net.onMessage = function (d) {
    if (d.t === 'hello') {
        if (net.role === 'author') {
            /* 若本地为空而服务器已有内容（如刷新页面），采用服务器内容；否则以本地为准全量同步 */
            var sv = d.state;
            if (!store.list.length && sv && sv.strokes && sv.strokes.length) {
                store.list = sv.strokes;
                if (sv.viewport) applyViewport(sv.viewport);
                fitToContent();
                requestDraw();
                sendViewport();
            } else {
                net.send({ t: 'sync', strokes: store.list, viewport: vp });
                sendViewport();
            }
        } else if (d.state) {
            if (d.state.strokes) store.list = d.state.strokes;
            if (d.state.viewport) applyViewport(d.state.viewport);
            requestDraw();
        }
    } else if (d.t === 'evt') {
        var e = d.e;
        if (!e) return;
        if (e.t === 'stroke') {
            if (store.applyEvent(e)) {
                drawIncremental(e);
                /* 笔画完成时全量重绘一次，兜底补齐任何增量遗漏 */
                if (e.done) requestDraw();
            }
        } else if (e.t === 'viewport') {
            applyViewport(e);
            requestDraw();
        } else if (e.t === 'undo' || e.t === 'clear') {
            if (store.applyEvent(e)) requestDraw();
        }
    } else if (d.t === 'state') {
        if (d.strokes) store.list = d.strokes;
        if (d.viewport) applyViewport(d.viewport);
        requestDraw();
    }
};
function applyViewport(v) {
    if (!v) return;
    vp.x = Number(v.x) || 0;
    vp.y = Number(v.y) || 0;
    vp.s = clamp(Number(v.s) || 1, MIN_S, MAX_S);
    if (v.w) vp.w = Number(v.w);
    if (v.h) vp.h = Number(v.h);
}
/* 笔记若完全不在当前视口内（如恢复的视口位置不对），自动把视口移到笔记处 */
function fitToContent() {
    var list = store.list;
    if (!list.length) return;
    var minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9, found = false;
    for (var i = 0; i < list.length; i++) {
        var s = list[i];
        if (s.tool === 'eraser') continue;   /* 橡皮笔画不参与包围盒 */
        var pts = s.pts;
        for (var j = 0; j < pts.length; j++) {
            var x = pts[j][0], y = pts[j][1];
            if (x < minX) minX = x;
            if (y < minY) minY = y;
            if (x > maxX) maxX = x;
            if (y > maxY) maxY = y;
            found = true;
        }
    }
    if (!found) return;
    /* 笔记中心距视口中心太远时，把视口对中到笔记 */
    var cxm = (minX + maxX) / 2, cym = (minY + maxY) / 2;
    var vcx = vp.x + vp.w / vp.s / 2, vcy = vp.y + vp.h / vp.s / 2;
    var dx = cxm - vcx, dy = cym - vcy;
    var far = Math.sqrt(dx * dx + dy * dy) > Math.max(vp.w, vp.h) / vp.s / 2;
    if (far) {
        vp.x = cxm - vp.w / vp.s / 2;
        vp.y = cym - vp.h / vp.s / 2;
    }
}
function sendViewport() {
    net.send({ t: 'evt', e: { t: 'viewport',
        x: Math.round(vp.x * 100) / 100, y: Math.round(vp.y * 100) / 100,
        s: Math.round(vp.s * 10000) / 10000, w: vp.w, h: vp.h } });
}

/* ================= 输入（author 用） ================= */
var input = {
    pointers: {}, stroke: null, gesture: null, pan: null,
    tool: 'pen', color: '#e53935', panMode: false,
    queued: [], lastFlush: 0, lastVp: 0, lastRender: 0
};

function toWorld(px, py) {
    return [px / vp.s + vp.x, py / vp.s + vp.y];
}

input.startStroke = function (w) {
    var st = { id: uid(), tool: input.tool, color: input.color,
               w: input.tool === 'eraser' ? ERASER_W : PEN_W, pts: [w], done: false };
    input.stroke = st;
    store.list.push(st);
    drawDot(st, w);
    /* 首点立即发送：落笔即出墨点，不等节流（断连时 send 失败也无碍，重连后 sync 补齐） */
    net.send({ t: 'evt', e: { t: 'stroke', id: st.id, tool: st.tool, color: st.color,
                              w: st.w, pts: [w], done: false } });
    input.queued = [];
    input.lastFlush = Date.now();
};
input.extendStroke = function (w) {
    var st = input.stroke;
    if (!st) return;
    var pts = st.pts;
    pts.push(w);
    input.queued.push(w);
    drawSegment(st, pts[pts.length - 2], w);
    if (Date.now() - input.lastFlush >= SEND_STROKE_MS ||
        input.queued.length >= SEND_STROKE_N) input.flush(false);
};
input.flush = function (done) {
    if (!input.stroke || !input.queued.length) {
        if (done) input.stroke = null;
        return;
    }
    var st = input.stroke;
    net.send({ t: 'evt', e: { t: 'stroke', id: st.id, tool: st.tool, color: st.color,
                              w: st.w, pts: input.queued, done: !!done } });
    if (done) { st.done = true; input.stroke = null; }
    input.queued = [];
    input.lastFlush = Date.now();
};
input.endStroke = function () { input.flush(true); };
input.cancelStroke = function () { input.stroke = null; input.queued = []; };

input.startGesture = function () {
    var keys = Object.keys(input.pointers);
    if (keys.length < 2) return;
    var a = input.pointers[keys[0]], b = input.pointers[keys[1]];
    input.gesture = {
        mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2,
        d: Math.max(1, Math.sqrt((a.x - b.x) * (a.x - b.x) + (a.y - b.y) * (a.y - b.y))),
        x: vp.x, y: vp.y, s: vp.s
    };
};
input.updateGesture = function () {
    var g = input.gesture;
    if (!g) return;
    var keys = Object.keys(input.pointers);
    if (keys.length < 2) return;
    var a = input.pointers[keys[0]], b = input.pointers[keys[1]];
    var mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    var d = Math.max(1, Math.sqrt((a.x - b.x) * (a.x - b.x) + (a.y - b.y) * (a.y - b.y)));
    var s = clamp(g.s * d / g.d, MIN_S, MAX_S);
    vp.x = mx - (g.mx - g.x) * (s / g.s);
    vp.y = my - (g.my - g.y) * (s / g.s);
    vp.s = s;
    var t = Date.now();
    if (t - input.lastRender >= RENDER_MS) { input.lastRender = t; requestDraw(); }
    if (t - input.lastVp >= SEND_VP_MS) { input.lastVp = t; sendViewport(); }
};
input.endGesture = function () { input.gesture = null; };

function onDown(id, x, y) {
    if (input.panMode) {          /* 漫游模式：单指拖动平移画布 */
        input.pan = { x: vp.x, y: vp.y, sx: x, sy: y };
        return;
    }
    input.pointers[id] = { x: x, y: y };
    var n = Object.keys(input.pointers).length;
    if (n === 1) {
        if (input.gesture) input.endGesture();
        input.startStroke(toWorld(x, y));
    } else if (n === 2) {
        input.endStroke();
        input.startGesture();
    }
}
function onMove(id, x, y) {
    if (input.pan) {
        vp.x = input.pan.x - (x - input.pan.sx) / vp.s;
        vp.y = input.pan.y - (y - input.pan.sy) / vp.s;
        requestDraw();
        var t1 = Date.now();
        if (t1 - input.lastVp >= SEND_VP_MS) { input.lastVp = t1; sendViewport(); }
        return;
    }
    if (!(id in input.pointers)) return;
    input.pointers[id] = { x: x, y: y };
    var n = Object.keys(input.pointers).length;
    if (n === 1 && input.stroke) input.extendStroke(toWorld(x, y));
    else if (n === 2) input.updateGesture();
}
function onUp(id) {
    if (input.pan) { input.pan = null; return; }   /* 漫游/右键平移结束 */
    if (!(id in input.pointers)) return;
    delete input.pointers[id];
    var n = Object.keys(input.pointers).length;
    if (n === 0) {
        input.endStroke();
        input.endGesture();
    } else if (n === 1) {
        input.endGesture();
    }
}

function bindInput() {
    if (window.PointerEvent) {
        cv.addEventListener('pointerdown', function (e) {
            e.preventDefault();
            onDown(e.pointerId, e.clientX, e.clientY);
        });
        cv.addEventListener('pointermove', function (e) {
            onMove(e.pointerId, e.clientX, e.clientY);
        });
        cv.addEventListener('pointerup', function (e) { onUp(e.pointerId); });
        cv.addEventListener('pointercancel', function (e) { onUp(e.pointerId); });
        cv.addEventListener('pointerleave', function (e) { onUp(e.pointerId); });
    } else {
        cv.addEventListener('touchstart', function (e) {
            e.preventDefault();
            var i, t;
            for (i = 0; i < e.changedTouches.length; i++) {
                t = e.changedTouches[i];
                onDown('t' + t.identifier, t.clientX, t.clientY);
            }
        }, { passive: false });
        cv.addEventListener('touchmove', function (e) {
            e.preventDefault();
            var i, t;
            for (i = 0; i < e.changedTouches.length; i++) {
                t = e.changedTouches[i];
                onMove('t' + t.identifier, t.clientX, t.clientY);
            }
        }, { passive: false });
        cv.addEventListener('touchend', function (e) {
            e.preventDefault();
            var i, t;
            for (i = 0; i < e.changedTouches.length; i++) {
                t = e.changedTouches[i];
                onUp('t' + t.identifier);
            }
        }, { passive: false });
        cv.addEventListener('touchcancel', function (e) {
            var i, t;
            for (i = 0; i < e.changedTouches.length; i++) {
                t = e.changedTouches[i];
                onUp('t' + t.identifier);
            }
        }, { passive: false });
        cv.addEventListener('mousedown', function (e) {
            if (e.button === 0) {
                onDown('m', e.clientX, e.clientY);
            } else {
                input.pan = { x: vp.x, y: vp.y, sx: e.clientX, sy: e.clientY };
                e.preventDefault();
            }
        });
        window.addEventListener('mousemove', function (e) {
            if (e.buttons === 0 && !input.stroke && !input.pan) return;
            onMove('m', e.clientX, e.clientY);
        });
        window.addEventListener('mouseup', function (e) {
            if (e.button === 0) onUp('m');
            else input.pan = null;
        });
    }
    cv.addEventListener('wheel', function (e) {
        e.preventDefault();
        var r = cv.getBoundingClientRect();
        var px = e.clientX - r.left, py = e.clientY - r.top;
        var f = Math.pow(1.15, -e.deltaY / 100);
        var s = clamp(vp.s * f, MIN_S, MAX_S);
        var wx = px / vp.s + vp.x, wy = py / vp.s + vp.y;
        vp.x = px / s - wx;
        vp.y = py / s - wy;
        vp.s = s;
        requestDraw();
        var t = Date.now();
        if (t - input.lastVp >= SEND_VP_MS) { input.lastVp = t; sendViewport(); }
    }, { passive: false });
}

/* ================= 界面 ================= */
var statusEl = document.getElementById('status');
function setStatus(ok) {
    statusEl.className = 'st' + (ok ? ' ok' : '');
    statusEl.textContent = ok ? '● 已连接' : '○ 未连接';
}

function toggleFull() {
    var el = document.documentElement;
    if (!document.fullscreenElement && !document.webkitFullscreenElement) {
        var f = el.requestFullscreen || el.webkitRequestFullscreen;
        if (f) f.call(el);
    } else {
        var x = document.exitFullscreen || document.webkitExitFullscreen;
        if (x) x.call(document);
    }
}

function bindUI() {
    var tools = document.getElementById('tools');
    var hint = document.getElementById('hint');
    if (ROLE === 'viewer') {
        tools.style.display = 'none';
        document.getElementById('reset').style.display = 'none';
        document.getElementById('viewerHint').style.display = 'block';
    } else {
        hint.style.display = 'block';
    }
    var btns = tools.querySelectorAll('button[data-tool]');
    for (var i = 0; i < btns.length; i++) {
        btns[i].addEventListener('click', function () {
            for (var j = 0; j < btns.length; j++) {
                btns[j].className = btns[j].className.replace(/\bon\b/g, '');
            }
            this.className += ' on';
            input.tool = this.getAttribute('data-tool');
            if (this.getAttribute('data-color')) input.color = this.getAttribute('data-color');
        });
    }
    document.getElementById('undo').addEventListener('click', function () {
        if (ROLE !== 'author') return;
        input.endStroke();
        if (!store.list.length) return;
        store.list.pop();
        net.send({ t: 'evt', e: { t: 'undo' } });
        requestDraw();
    });
    document.getElementById('clear').addEventListener('click', function () {
        if (ROLE !== 'author') return;
        if (!store.list.length) return;
        if (!window.confirm('确定清空整张白板？')) return;
        input.cancelStroke();
        store.list = [];
        net.send({ t: 'evt', e: { t: 'clear' } });
        requestDraw();
    });
    document.getElementById('reset').addEventListener('click', function () {
        vp.s = 1;
        vp.x = -cssW / 2;
        vp.y = -cssH / 2;
        requestDraw();
        sendViewport();
    });
    document.getElementById('full').addEventListener('click', toggleFull);
    /* 漫游模式开关：单指拖动平移画布（不写字） */
    var panBtn = document.getElementById('pan');
    if (panBtn) {
        panBtn.addEventListener('click', function () {
            input.panMode = !input.panMode;
            panBtn.className = input.panMode ? 'on' : '';
        });
    }
}

/* ================= 启动 ================= */
window.addEventListener('resize', resize);
window.addEventListener('orientationchange', resize);
resize();
bindInput();
bindUI();
setStatus(false);
net.connect();

/* 供自动化测试使用的钩子（不影响正常功能） */
window.__ck = {
    role: ROLE, store: store, vp: vp, net: net, input: input,
    drawStroke: drawStroke, requestDraw: requestDraw, draw: draw,
    applyT: applyT, transform: transform,
    drawIncremental: drawIncremental,
    setTool: function (tool, color) { input.tool = tool; if (color) input.color = color; },
    setPanMode: function (on) { input.panMode = !!on; }
};

})();

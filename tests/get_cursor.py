# -*- coding: utf-8 -*-
"""获取当前鼠标光标位置（测试触控板注入用）"""
import ctypes
from ctypes import wintypes

pt = wintypes.POINT()
ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
print('CURSOR %d %d' % (pt.x, pt.y))

# -*- coding: utf-8 -*-
"""调试 SendInput：打印返回值、结构体大小"""
import ctypes
from ctypes import wintypes


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


print('sizeof MOUSEINPUT:', ctypes.sizeof(MOUSEINPUT))
print('sizeof INPUT:', ctypes.sizeof(INPUT))
print('expected INPUT:', ctypes.sizeof(ctypes.c_ulong) + 0)

user32 = ctypes.windll.user32
fn = user32.SendInput
fn.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
fn.restype = wintypes.UINT

mi = MOUSEINPUT(5000, 5000, 0, 0x0001 | 0x8000, 0, None)
inp = INPUT(type=0, u=INPUTUNION(mi=mi))
ret = fn(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
print('SendInput ret (should be 1):', ret)
print('last error:', ctypes.get_last_error())

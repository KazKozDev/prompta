"""A dark graphite title bar on macOS.

The title bar is drawn by macOS, not by Qt or app.qss, and the app runs in the light Aqua appearance
(NSRequiresAquaSystemAppearance in build_standalone.sh). So the colour is set on the window's NSWindow:
a transparent title bar over a graphite window background, in the dark appearance so the title and the
traffic lights read on it. Plain ctypes calls into the Objective-C runtime: no extra dependency.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
from typing import Any

from PyQt6.QtWidgets import QWidget

GRAPHITE = (0x36, 0x37, 0x3A)  # dark graphite grey


def _runtime() -> Any:
    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc") or "libobjc.dylib")
    ctypes.cdll.LoadLibrary(ctypes.util.find_library("AppKit") or "/System/Library/Frameworks/AppKit.framework/AppKit")
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    return objc


def _send(
    objc: Any, receiver: Any, selector: str, *args: Any, argtypes: tuple = (), restype: Any = ctypes.c_void_p
) -> Any:
    # objc_msgSend must be called with the exact prototype of each method (arm64 has no variadic shortcut).
    send = ctypes.cast(objc.objc_msgSend, ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes))
    return send(receiver, objc.sel_registerName(selector.encode()), *args)


def paint_title_bar(window: QWidget, rgb: tuple[int, int, int] = GRAPHITE) -> bool:
    """Colour the window's title bar; False where there is nothing to do (not macOS, no native window)."""
    if sys.platform != "darwin":
        return False
    try:
        objc = _runtime()
        view = ctypes.c_void_p(int(window.winId()))  # creates the native window if needed
        nswindow = _send(objc, view, "window")
        if not nswindow:
            return False
        name = _send(
            objc,
            objc.objc_getClass(b"NSString"),
            "stringWithUTF8String:",
            b"NSAppearanceNameDarkAqua",
            argtypes=(ctypes.c_char_p,),
        )
        appearance = _send(
            objc, objc.objc_getClass(b"NSAppearance"), "appearanceNamed:", name, argtypes=(ctypes.c_void_p,)
        )
        red, green, blue = (channel / 255 for channel in rgb)
        color = _send(
            objc,
            objc.objc_getClass(b"NSColor"),
            "colorWithSRGBRed:green:blue:alpha:",
            red,
            green,
            blue,
            1.0,
            argtypes=(ctypes.c_double,) * 4,
        )
        _send(objc, nswindow, "setTitlebarAppearsTransparent:", True, argtypes=(ctypes.c_bool,), restype=None)
        _send(objc, nswindow, "setBackgroundColor:", color, argtypes=(ctypes.c_void_p,), restype=None)
        _send(objc, nswindow, "setAppearance:", appearance, argtypes=(ctypes.c_void_p,), restype=None)
        return True
    except (OSError, AttributeError, TypeError, ValueError):
        return False  # an older or unusual system keeps the standard title bar

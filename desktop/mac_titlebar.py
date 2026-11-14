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

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication, QWidget

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
    # winId() is an NSView only on Cocoa; offscreen (tests, screenshots.py) messaging it crashes the process.
    if sys.platform != "darwin" or QGuiApplication.platformName() != "cocoa":
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


class _TitleBarPainter(QObject):
    """Paints every ordinary window and dialog the moment it first shows: the main window, Settings,
    the sources list, confirmations. Popups, tooltips and sheets keep their own look."""

    def eventFilter(self, obj: QObject | None, event: QEvent | None) -> bool:
        if (
            event is not None
            and event.type() == QEvent.Type.Show
            and isinstance(obj, QWidget)
            and obj.isWindow()
            and obj.windowType() in (Qt.WindowType.Window, Qt.WindowType.Dialog)
            and not obj.property("graphiteTitleBar")
        ):
            obj.setProperty("graphiteTitleBar", paint_title_bar(obj))
        return False


def paint_all_title_bars(app: QApplication) -> None:
    """The graphite title bar for all of the app's windows, present and future."""
    painter = _TitleBarPainter(app)
    app.title_bar_painter = painter  # type: ignore[attr-defined]  # kept alive with the app
    app.installEventFilter(painter)

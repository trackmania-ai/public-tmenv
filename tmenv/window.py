# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/window.ipynb.

# %% auto 0
__all__ = ['MssCapture', 'Window', 'TmWindow']

# %% ../nbs/window.ipynb 1
import ctypes
import warnings
from ctypes import POINTER, c_ubyte
from functools import cache
from time import sleep

import easyocr
import numpy as np
import torch
from fastai.vision.core import to_image
from fastcore.foundation import L, Self
from matplotlib import pyplot as plt
from mss.linux import MSS, Display
from Xlib import XK, X, display, error, ext, protocol

# %% ../nbs/window.ipynb 3
class MssCapture(MSS):
    def __init__(self, window_id):
        super().__init__()
        self.d = self.xlib.XOpenDisplay(None)
        self.win_ptr = ctypes.cast(window_id, POINTER(Display))

    def capture(self, width, height):
        ximage = self.xlib.XGetImage(
            self.d,
            self.win_ptr,
            0,
            0,
            width,
            height,
            0x00FFFFFF,
            2,
        )

        try:
            return bytearray(
                ctypes.cast(
                    ximage.contents.data,
                    POINTER(c_ubyte * height * width * 4),
                ).contents
            )
        finally:
            self.xlib.XDestroyImage(ximage)

# %% ../nbs/window.ipynb 4
class Window:
    try:
        disp = display.Display()
        root = disp.screen().root
    except error.DisplayNameError:
        warnings.warn("No X Window display found. Does your system uses X Window ?")
        disp = root = None

    @classmethod
    def _find_xlib_window_inner(cls, title, parent=root):
        if not parent:
            return None
        try:
            for child in parent.query_tree().children:
                window = cls._find_xlib_window_inner(title, child)
                if window is None:
                    child_title = child.get_wm_name()
                    if child_title and title in child_title:
                        return child
                else:
                    return window
        except error.BadWindow:
            pass
        return None

    @classmethod
    def find_xlib_window(cls, title, sync):
        xlib_window = cls._find_xlib_window_inner(title)
        while sync and xlib_window is None:
            sleep(0.1)
            xlib_window = cls._find_xlib_window_inner(title)
        return xlib_window

    @classmethod
    @cache
    def key_to_code(cls, key):
        return cls.disp.keysym_to_keycode(XK.string_to_keysym(key))

    def __init__(self, title, sync=False):
        self.window = self.find_xlib_window(title, sync)
        self.mss = MssCapture(self.window.id)
        self.update_geometry()

    def update_geometry(self):
        self.geometry = self.window.get_geometry()

    def capture_numpy_array(self):
        raw = self.mss.capture(self.geometry.width, self.geometry.height)
        array = np.frombuffer(raw, dtype=np.uint8)
        return array.reshape([self.geometry.height, self.geometry.width, 4])[:, :, :3]

    def capture_tensor(self):
        raw = self.mss.capture(self.geometry.width, self.geometry.height)
        return (
            torch.frombuffer(raw, dtype=torch.uint8)
            .view(self.geometry.height, self.geometry.width, 4)[:, :, :3]
            .permute(2, 0, 1)
        )

    def capture_image(self):
        return to_image(self.capture_tensor().flip((0,)))

    def read_paragraphs(self):
        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        paragraphs = reader.readtext(self.capture_numpy_array(), paragraph=True)
        return L(paragraphs).map(Self[1])

    def has_texts(self, *texts, condition=any, case_sensitive=False, paragraphs=None):
        if paragraphs is None:
            paragraphs = self.read_paragraphs()
        if not case_sensitive:
            texts = L(texts).map(str.casefold)
            paragraphs = paragraphs.map(str.casefold)
        return condition(any(text in p for p in paragraphs) for text in texts)

    def send_key_event(self, key_event_cls, key):
        keys = L(key)
        for k in keys:
            event = key_event_cls(
                time=X.CurrentTime,
                root=self.root,
                window=self.window,
                same_screen=1,
                child=X.NONE,
                root_x=0,
                root_y=0,
                event_x=0,
                event_y=0,
                state=1,
                detail=self.key_to_code(k),
            )
            self.window.send_event(event, propagate=True)

    def key_press(self, key):
        self.send_key_event(protocol.event.KeyPress, key)

    def key_release(self, key):
        self.send_key_event(protocol.event.KeyRelease, key)

    def key_tap(self, key):
        self.key_press(key)
        self.sync()
        self.key_release(key)
        self.sync()

    def set_position(self, x, y):
        self.window.configure(x=x, y=y)
        self.sync()

    def sync(self):
        self.disp.sync()

# %% ../nbs/window.ipynb 5
class TmWindow(Window):
    keys = L("Up", "Down", "Left", "Right")

    def __init__(self, title, sync=False):
        super().__init__(title, sync)
        self.pressed_key_mask = np.zeros(len(self.keys), dtype=bool)

    def act(self, accelerate, brake, steer):
        key_mask = [accelerate, brake, steer < 0.0, 0.0 < steer]
        key_mask = np.array(key_mask, dtype=bool)
        release_keys = self.keys[self.pressed_key_mask & ~key_mask]
        press_keys = self.keys[~self.pressed_key_mask & key_mask]
        if release_keys or press_keys:
            self.key_release(release_keys)
            self.key_press(press_keys)
            self.sync()
        self.pressed_key_mask = key_mask

    def give_up(self):
        self.key_tap("Delete")

    def respawn(self, launched=True):
        self.key_tap("BackSpace")
        if not launched:
            sleep(0.01)
            self.key_tap("BackSpace")

    def toggle_interface(self):
        self.key_tap("KP_Multiply")

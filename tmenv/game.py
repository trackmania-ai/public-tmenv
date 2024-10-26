# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/game.ipynb.

# %% auto 0
__all__ = ['LoadMapTimeoutException', 'GiveUpTimeoutException', 'RespawnTimeoutException', 'Game']

# %% ../nbs/game.ipynb 1
import logging
from collections import OrderedDict
from copy import deepcopy
from itertools import repeat
from pathlib import Path
from time import sleep, time

import numpy as np
from fastcore.foundation import L
from .gamepad import TmGamepad
from .prefix import Prefix
from .socket import Socket
from .window import TmWindow

# %% ../nbs/game.ipynb 3
class LoadMapTimeoutException(Exception):
    pass


class GiveUpTimeoutException(Exception):
    pass


class RespawnTimeoutException(Exception):
    pass


class Game:
    def __init__(
        self,
        name,
        width,
        height,
        prefix_path,
        prefix_template_path,
        credential_path,
        window_x=0,
        window_y=0,
    ):
        self.name, self.width, self.height = name, width, height
        self.prefix_path = Path(prefix_path)
        self.prefix_template_path = Path(prefix_template_path)
        self.credential_path = Path(credential_path)
        self.window_x, self.window_y = window_x, window_y
        self.socket = Socket()
        self.prefix = Prefix(
            self.name,
            self.width,
            self.height,
            self.prefix_path,
            self.prefix_template_path,
            self.credential_path,
            self.socket.port,
        )
        self.gamepad = TmGamepad(name)
        self.start_and_connect_game()

    def recover(self):
        """Relaunch the game in the wine environment. To be used in the event of a crash."""
        self.act(False, False, False, False)
        self.socket = Socket()
        self.prefix.set_socket_port(self.socket.port)
        if self.prefix.running():
            self.prefix.kill()
            while self.prefix.running():
                sleep(1)
        self.start_and_connect_game()

    def start_and_connect_game(self):
        self.prefix.run(self.gamepad.path)
        self.window = TmWindow(f"{self.name} - Wine desktop", sync=True)
        self.window.set_position(self.window_x, self.window_y)
        while not self.socket.connected:
            sleep(1)
            paragraphs = self.window.read_paragraphs()
            if self.window.has_texts(
                "skip", condition=all, paragraphs=paragraphs
            ):
                self.gamepad.tap_b()
            if self.window.has_texts(
                "update", "available", "download", condition=all, paragraphs=paragraphs
            ):
                self.gamepad.tap_a()
        self.prefix.hide_taskbar()
        sleep(1)
        # Move window again (obs capture freeze workaround)
        self.window.set_position(self.window_x, self.window_y)
        sleep(2)
        self.prefix.save_credential(self.credential_path)

    def act(self, accelerate, brake, steer, check_socket=True):
        assert not check_socket or self.socket.connected
        # Hybrid method because gamepad has more latency
        self.window.act(accelerate, brake, 0)
        self.gamepad.act(False, False, steer)

    def give_up(self, wait_go=False, timeout=5, retry=5):
        if not wait_go:
            assert self.socket.connected
            self.window.give_up()
            return
        for _ in range(retry):
            assert self.socket.connected
            self.window.give_up()
            start_time = time()
            try:
                telemetry = self.telemetry
                while (
                    0 < telemetry["racetime"]
                    or telemetry["finished"]
                    or (0.05 < time() - telemetry["_updatetime"])
                ):
                    sleep(0.01)
                    if timeout < time() - start_time:
                        raise GiveUpTimeoutException()
                    telemetry = self.telemetry
            except GiveUpTimeoutException:
                continue
            wait = telemetry["_updatetime"] - time() - telemetry["racetime"] / 1000
            if 0 < wait:
                sleep(wait)
            return
        raise GiveUpTimeoutException(
            f"Game was unable to give_up in less than {timeout} seconds after {retry} attempts."
        )

    def respawn(
        self, launched=True, wait_go=False, timeout=2, retry=5, initial_wait=0.2
    ):
        if not wait_go:
            assert self.socket.connected
            self.window.respawn(launched)
            return
        for _ in range(retry):
            assert self.socket.connected
            self.window.respawn(launched)
            start_time = time()
            sleep(initial_wait)
            try:
                while (
                    initial_wait < time() - (telemetry := self.telemetry)["_updatetime"]
                ):
                    sleep(0.01)
                    if timeout < time() - start_time:
                        raise RespawnTimeoutException()
                while (
                    telemetry["distance"] == self.telemetry["distance"]
                    and telemetry["speed"] == self.telemetry["speed"]
                ):
                    sleep(0.001)
                    if timeout < time() - start_time:
                        raise RespawnTimeoutException()
                return
            except RespawnTimeoutException:
                continue
        raise RespawnTimeoutException(
            f"Game was unable to respawn in less than {timeout} seconds after {retry} attempts."
        )

    def toggle_interface(self):
        self.window.toggle_interface()

    @property
    def previous_telemetry(self):
        return self.socket.previous_telemetry

    @property
    def telemetry(self):
        return self.socket.telemetry

    def capture_tensor(self):
        return self.window.capture_tensor()

    def load_map(self, url, timeout=30):
        assert self.socket.connected
        self.socket.send_command("LoadMap", url)
        start_time = time()
        sleep(2)
        while "ui_sequence" not in self.telemetry or self.telemetry["ui_sequence"] != 2:
            sleep(0.1)
            if timeout < time() - start_time:
                raise LoadMapTimeoutException()
        while self.telemetry["ui_sequence"] != 1:
            self.window.key_tap("Up")
            sleep(0.1)
            if timeout < time() - start_time:
                raise LoadMapTimeoutException()
        sleep(2)

    def save_ghost(self, url, header):
        assert self.socket.connected
        self.socket.send_command("SendGhost", url, header)

    def close(self):
        if self.prefix.running():
            self.prefix.kill()

    def input_lag(self, sample_size=100):
        results = []
        for _ in range(sample_size):
            start_time = time()
            self.act(True, False, 0)
            while not self.telemetry["accelerate"]:
                sleep(0.00001)
            results.append(time() - start_time)
            start_time = time()
            self.act(False, False, 0)
            while self.telemetry["accelerate"]:
                sleep(0.00001)
            results.append(time() - start_time)
        input_lag = np.array(results).mean() * 1000
        logging.info(f"Input lag is {input_lag:.3f} ms (this include telemetry lag)")
        return input_lag

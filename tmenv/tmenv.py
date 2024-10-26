# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/tmenv.ipynb.

# %% auto 0
__all__ = ['ActionHandler', 'DiscreteActionHandler', 'ContinuousActionHandler', 'MixedActionHandler', 'MapNotLoadedException',
           'TelemetryTimeout', 'Tmenv']

# %% ../nbs/tmenv.ipynb 1
import logging
from copy import deepcopy
from functools import cached_property
from itertools import product
from time import sleep, time

import numpy as np
from fastcore.basics import store_attr
from fastcore.foundation import L
from fastcore.xtras import class2attr
from gym import Env
from gym.spaces import Box, Dict, Discrete, Tuple
from .game import Game, GiveUpTimeoutException
from .gbx import map_from_uid

# %% ../nbs/tmenv.ipynb 3
class ActionHandler:
    @property
    def name(self):
        return class2attr(self, "ActionHandler")

    @property
    def default_action_dict(self):
        return dict(steer=0, accelerate=False, brake=False)

    def action_dict(self, action):
        raise NotImplementedError()

    def mirror(self, action):
        raise NotImplementedError()


class DiscreteActionHandler(ActionHandler):
    def __init__(self, inter_steer=L()):
        store_attr()
        self.steer_values = (
            L(0.0, 1.0, -1.0) + L(inter_steer) + L(inter_steer).map(lambda x: -x)
        )
        self.actions = tuple(
            dict(accelerate=accelerate, brake=brake, steer=steer)
            for accelerate, brake, steer in product(
                [False, True], [False, True], self.steer_values
            )
        )
        self.action_space = Discrete(len(self.actions))
        self.mirror_map = dict()
        for i, action in enumerate(self.actions):
            action = action.copy()
            action["steer"] *= -1.0
            for j, target_action in enumerate(self.actions):
                if action == target_action:
                    self.mirror_map[i] = j
                    break

    def action_dict(self, action):
        return self.actions[action].copy()

    def mirror(self, action):
        return self.mirror_map[action]

    def print_actions(self):
        for index, action in enumerate(self.actions):
            print(f"{index}: {action}")


class ContinuousActionHandler(ActionHandler):
    def __init__(self):
        self.action_space = Box(-1.0, 1.0, (3,))

    def action_dict(self, action):
        return dict(steer=action[0], accelerate=0 < action[1], brake=0 < action[2])

    def mirror(self, action):
        return (-action[0], action[1], action[2])

    def print_actions(self):
        print(
            "{"
            "steer: -1.0<=steer<=1.0, "
            "accelerate: -1.0<=accelerate<=1.0, "
            "brake: -1.0<=brake<=1.0, "
            "}"
        )


class MixedActionHandler(ActionHandler):
    def __init__(self):
        self.discrete_actions = tuple(
            dict(accelerate=accelerate, brake=brake)
            for accelerate, brake in product([False, True], [False, True])
        )
        self.action_space = Tuple(
            (Box(-1.0, 1.0, (1,)), Discrete(len(self.discrete_actions)))
        )

    def action_dict(self, action):
        return dict(steer=action[0], **self.discrete_actions[action[1]])

    def mirror(self, action):
        return (-action[0], action[1])

    def print_actions(self):
        print("continuous_action:")
        print("{steer: -1.0<=steer<=1.0}")
        print("discrete_action:")
        for index, action in enumerate(self.discrete_actions):
            print(f"{index}: {action}")

# %% ../nbs/tmenv.ipynb 4
class MapNotLoadedException(Exception):
    pass


class TelemetryTimeout(Exception):
    pass


class Tmenv(Env):
    def __init__(
        self,
        name,
        width,
        height,
        prefix_path,
        prefix_template_path,
        credential_path,
        timestep=0.1,
        wait_telemetry=True,
        telemetry_time=0.001,
        telemetry_timeout=0.5,
        action_handler=DiscreteActionHandler(),
        device="cpu",
        window_x=0,
        window_y=0,
    ):
        self.name, self.width, self.height = name, width, height
        self.prefix_path = prefix_path
        self.prefix_template_path = prefix_template_path
        self.credential_path = credential_path
        self.timestep = timestep
        self.wait_telemetry = wait_telemetry
        self.telemetry_time = telemetry_time
        self.telemetry_timeout = telemetry_timeout
        self.action_handler = action_handler
        self.device = device
        self.window_x, self.window_y = window_x, window_y
        self.action_space = self.action_handler.action_space
        self.observation_space = Dict({"env": Dict()})

    @property
    def has_map(self):
        return hasattr(self, "map_data")

    @property
    def config(self):
        config = dict(
            name=self.name,
            width=self.width,
            height=self.height,
            timestep=self.timestep,
            action_handler=self.action_handler.name,
        )
        if self.has_map:
            config["map"] = {
                k: self.map_data[k] for k in self.map_data.keys() - ["ghosts"]
            }
        return config

    @cached_property
    def game(self):
        return Game(
            self.name,
            self.width,
            self.height,
            self.prefix_path,
            self.prefix_template_path,
            self.credential_path,
            self.window_x,
            self.window_y,
        )

    def recover(self):
        """Relaunch the game in the wine environment. To be used in the event of a crash."""
        logging.warning(f"Recovering Tmenv {self.name}")
        self.game.recover()
        self.game.load_map(self.map_data["url"])
        self.game.toggle_interface()

    def wait_telemetry_update(self):
        start_time = time()
        while self.telemetry_time < (time() - self.game.telemetry["_updatetime"]):
            sleep(self.telemetry_time / 2)
            if self.telemetry_timeout < time() - start_time:
                raise TelemetryTimeout()
        return (time() - start_time) * 1000

    def env_observation(self):
        if self.wait_telemetry:
            telemetry_lag = self.wait_telemetry_update()
        previous = deepcopy(self.game.previous_telemetry)
        env = deepcopy(self.game.telemetry)
        env["previous"] = previous
        if self.wait_telemetry:
            env["telemetry_lag"] = telemetry_lag
        else:
            env["telemetry_lag"] = (time() - env["_updatetime"]) * 1000
        env["velocity_norm"] = np.linalg.norm(env["velocity"]).item()
        env["crossed_checkpoint"] = False
        env["observation_start_time"] = time()
        return dict(env=env)

    def env_info(self, observation):
        # racetime from telemetry can be bugged at the end of a race
        # and have a negative value
        racetime = observation["env"]["racetime"]
        if 0 < racetime:
            self.last_positive_racetime = racetime
        elif self.last_positive_racetime is not None:
            racetime = self.last_positive_racetime

        return dict(
            checkpoints=self.checkpoints,
            finished=observation["env"]["finished"],
            racetime=racetime,
            must_respawn=False,
            telemetry_lag=observation["env"]["telemetry_lag"],
        )

    def step(self, action):
        self.game.act(**self.action_handler.action_dict(action))
        sleep(self.timestep)
        observation = self.env_observation()
        if self.current_landmark != observation["env"]["landmark_index"]:
            observation["env"]["crossed_checkpoint"] = True
            self.current_landmark = observation["env"]["landmark_index"]
            self.checkpoints.append(observation["env"]["racetime"])
            if observation["env"]["landmark_index"] == observation["env"]["standing_landmark_index"]:
                self.standing_cp_offset = 0
            else:
                self.standing_cp_offset -= 1
        done = observation["env"]["finished"]
        info = self.env_info(observation)
        return observation, 0.0, done, info

    def respawn(self, launched=True):
        self.game.act(**self.action_handler.default_action_dict)
        self.game.respawn(launched, wait_go=True)
        return self.env_observation()

    def reset(self, **kwargs):
        if not self.has_map:
            raise MapNotLoadedException("Call load_map method first")
        self.game.act(**self.action_handler.default_action_dict)
        self.game.give_up(wait_go=True)
        observation = self.env_observation()
        self.current_landmark = observation["env"]["landmark_index"]
        self.checkpoints = []
        self.standing_cp_offset = 0 # 0 for same as current cp, -2 if last standing cp was 2 cps ago
        self.last_positive_racetime = None
        return observation

    def load_map(self, map_uid="XJ_JEjWGoAexDWe8qfaOjEcq5l8"):  # Summer 2020 - 01
        if self.has_map and self.map_data["uid"] == map_uid:
            logging.debug(f"{self.name} has already loaded map uid {map_uid}")
            return
        logging.debug(f"{self.name} is loading map uid {map_uid}")
        self.map_data = map_from_uid(map_uid)
        self.game.load_map(self.map_data["url"])
        self.game.toggle_interface()

    def close(self):
        if "game" in self.__dict__:
            self.__dict__["game"].close()

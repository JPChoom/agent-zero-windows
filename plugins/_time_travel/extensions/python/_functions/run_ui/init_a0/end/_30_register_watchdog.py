from __future__ import annotations

from helpers.extension import Extension
from plugins._time_travel.helpers.time_travel import register_watchdogs


class RegisterTimeTravelWatchdog(Extension):
    def execute(self, **kwargs):
        register_watchdogs()

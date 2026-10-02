#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from ..log import logger
from .client import Client


class IOMode:
    """ Mode of an analog IO selected by a mode register

        `modes` maps the mode name to its definition from the HW definition,
        e.g. {'Voltage': {'value': 0, 'unit': 'V', 'range': [0, 10]}}.
        The 'value' key is the number written to the mode register.

        Without a mode register the IO has a fixed mode, which is known only
        when a single mode is defined.
    """

    def __init__(self, client: Client, regmode=None, modes=None, name=''):
        self.client = client
        self.regmode = regmode
        self.modes = modes or {}
        self.name = name
        self.mode_value = None
        if self.regmode is None and len(self.modes) == 1:
            self.mode = next(iter(self.modes))
        else:
            self.mode = None

    @property
    def data(self) -> dict:
        """ Definition of the current mode, empty for an unknown mode """
        return self.modes.get(self.mode, {})

    @property
    def unit(self):
        return self.data.get('unit', None)

    @property
    def range(self):
        return self.data.get('range', None)

    def find(self, mode_value: int):
        """ Return the name of the mode with the register value, None if not defined """
        return next((mode for mode, data in self.modes.items() if data.get('value') == mode_value), None)

    def update(self) -> bool:
        """ Read the mode register from the cache, return True if the mode has changed """
        if self.regmode is None:
            return False
        mode_value = self.client.read_u16(self.regmode)
        if mode_value == self.mode_value:
            return False
        self.mode_value = mode_value
        self.mode = self.find(mode_value)
        if self.mode is None:
            logger.warning(f'Undefined mode "{mode_value}" in mode setting for {self.name}')
        return True

    async def set(self, mode: str) -> dict:
        """ Write the mode to the mode register, return its definition

            The current mode is changed by update() after the next scan.
        """
        if mode not in self.modes:
            raise ValueError(f'{self.name}: unknown mode "{mode}"!')
        data = self.modes[mode]
        if 'value' not in data:
            raise ValueError(f"{self.name}: this device cant switch mode!")
        if self.regmode is not None:
            await self.client.mb_client.write_single_register(self.regmode, int(data['value']))
        return data


class WithIOMode:
    """ Mixin for the devices with an IOMode in `self.iomode`

        Keeps the mode attributes of the device used by full() and the API
    """

    iomode: IOMode

    @property
    def mode(self):
        return self.iomode.mode

    @property
    def modes(self):
        return self.iomode.modes

    @property
    def mode_value(self):
        return self.iomode.mode_value

    @property
    def regmode(self):
        return self.iomode.regmode

    @property
    def unit_name(self):
        return self.iomode.unit

    @property
    def range(self):
        return self.iomode.range

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


class DIMode:
    """ Mode of a digital input selected by its bit in shared mode registers

        `modes` lists the modes of the input, e.g. ['Simple', 'DirectSwitch'].
        In the 'DirectSwitch' mode the input drives an output directly, the
        behaviour is selected by `ds_mode` from `ds_modes`: 'Simple', 'Inverted'
        (bit in the polarity register) or 'Toggle' (bit in the toggle register).

        The registers are shared by all inputs of a group, each input owns
        the bit `bitmask` in them.
    """

    def __init__(self, client: Client, bitmask: int, regmode=None, regpolarity=None, regtoggle=None,
                 modes=None, ds_modes=None, name=''):
        self.client = client
        self.bitmask = bitmask
        self.regmode = regmode
        self.regpolarity = regpolarity
        self.regtoggle = regtoggle
        self.modes = modes if modes is not None else ['Simple']
        self.ds_modes = ds_modes if ds_modes is not None else ['Simple']
        self.name = name
        self.mode = 'Simple'
        self.ds_mode = 'Simple'

    @property
    def has_direct_switch(self) -> bool:
        return 'DirectSwitch' in self.modes and self.regmode is not None

    def _bit(self, reg) -> bool:
        return bool(self.client.read_u16(reg) & self.bitmask)

    def update(self) -> bool:
        """ Read the mode registers from the cache, return True if the mode has changed """
        if not self.has_direct_switch:
            return False
        old = (self.mode, self.ds_mode)
        if self._bit(self.regmode):
            self.mode = 'DirectSwitch'
            if self._bit(self.regpolarity):
                self.ds_mode = 'Inverted'
            elif self._bit(self.regtoggle):
                self.ds_mode = 'Toggle'
            else:
                self.ds_mode = 'Simple'
        else:
            self.mode = 'Simple'
        return old != (self.mode, self.ds_mode)

    async def _write_bit(self, reg, value: bool):
        """ Read-modify-write the bit of this input in a shared register """
        curr = (await self.client.cache.get_register_async(1, reg))[0]
        curr = curr | self.bitmask if value else curr & ~self.bitmask
        await self.client.write_u16(reg, curr)

    async def set(self, mode=None, ds_mode=None):
        """ Write the mode and the DirectSwitch mode, unknown values are ignored

            Decide by the requested values and always read-modify-write the registers:
            self.mode and self.ds_mode can be stale or rewritten by update()
            in the scan task while this coroutine awaits.
        """
        if mode in self.modes:
            self.mode = mode
            if self.regmode is not None:
                await self._write_bit(self.regmode, mode == 'DirectSwitch')
        else:
            mode = self.mode

        if mode == 'DirectSwitch' and ds_mode in self.ds_modes:
            self.ds_mode = ds_mode
            await self._write_bit(self.regpolarity, ds_mode == 'Inverted')
            await self._write_bit(self.regtoggle, ds_mode == 'Toggle')


class WithDIMode:
    """ Mixin for the devices with a DIMode in `self.dimode` """

    dimode: DIMode

    @property
    def mode(self):
        return self.dimode.mode

    @property
    def modes(self):
        return self.dimode.modes

    @property
    def ds_mode(self):
        return self.dimode.ds_mode

    @property
    def ds_modes(self):
        return self.dimode.ds_modes

    @property
    def regmode(self):
        return self.dimode.regmode

    @property
    def regpolarity(self):
        return self.dimode.regpolarity

    @property
    def regtoggle(self):
        return self.dimode.regtoggle

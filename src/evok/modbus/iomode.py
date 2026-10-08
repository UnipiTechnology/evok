#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from ..log import logger
from .client import Client, AccessorU16, AccessorBit, Accessor


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
        self.accessor = AccessorU16(regmode) if regmode is not None else Accessor(regmode)
        self.modes = modes or {}
        self.name = name
        self.mode_value = None
        if regmode is None and len(self.modes) == 1:
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
        mode_value = self.accessor.read(self.client)
        if mode_value == self.mode_value:
            return False
        self.mode_value = mode_value
        self.mode = self.find(mode_value)
        if self.mode is None:
            logger.warning(f'Undefined mode "{mode_value}" in mode setting for {self.name}')
        return True

    def check(self, mode: str) -> dict:
        """ Return the definition of the mode, raise ValueError if it cannot be set """
        if mode not in self.modes:
            raise ValueError(f'{self.name}: unknown mode "{mode}"!')
        data = self.modes[mode]
        if self.accessor.index is not None and data.get('value') is None:
            raise ValueError(f"{self.name}: this device cant switch mode!")
        return data

    async def set(self, mode: str, apply: bool = False) -> dict:
        """ Write the mode to the mode register, return its definition

            The write updates the cache, the current mode is changed by the next update(),
            with apply at once, the next update() still reports the change.
            Without a mode register nothing is written and any defined mode is accepted.
        """
        data = self.check(mode)
        if self.accessor.index is not None:
            await self.accessor.write(self.client, int(data['value']))
        if apply:
            self.mode = mode
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
        self.accessor_mode = self._accessor(regmode, bitmask)
        self.accessor_polarity = self._accessor(regpolarity, bitmask)
        self.accessor_toggle = self._accessor(regtoggle, bitmask)
        self.modes = modes if modes is not None else ['Simple']
        self.ds_modes = ds_modes if ds_modes is not None else ['Simple']
        self.name = name
        self.mode = 'Simple'
        self.ds_mode = 'Simple'

    @staticmethod
    def _accessor(reg, bitmask) -> Accessor:
        return AccessorBit(reg, bitmask) if reg is not None else Accessor(None)

    @property
    def has_direct_switch(self) -> bool:
        return 'DirectSwitch' in self.modes and self.accessor_mode.index is not None

    def update(self) -> bool:
        """ Read the mode registers from the cache, return True if the mode has changed """
        if not self.has_direct_switch:
            return False
        old = (self.mode, self.ds_mode)
        if self.accessor_mode.read(self.client):
            self.mode = 'DirectSwitch'
            if self.accessor_polarity.read(self.client):
                self.ds_mode = 'Inverted'
            elif self.accessor_toggle.read(self.client):
                self.ds_mode = 'Toggle'
            else:
                self.ds_mode = 'Simple'
        else:
            self.mode = 'Simple'
        return old != (self.mode, self.ds_mode)

    def check(self, mode=None, ds_mode=None):
        """ Raise ValueError for an unknown mode or ds_mode """
        if mode is not None and mode not in self.modes:
            raise ValueError(f'{self.name}: unknown mode "{mode}"')
        if ds_mode is not None and ds_mode not in self.ds_modes:
            raise ValueError(f'{self.name}: unknown ds_mode "{ds_mode}"')

    async def set(self, mode=None, ds_mode=None):
        """ Write the mode and the DirectSwitch mode, unknown values are rejected,
            ds_mode is written only in the DirectSwitch mode

            Decide by the requested values and always read-modify-write the registers:
            self.mode and self.ds_mode can be stale or rewritten by update()
            in the scan task while this coroutine awaits.
        """
        self.check(mode, ds_mode)
        if mode is not None:
            self.mode = mode
            if self.accessor_mode.index is not None:
                await self.accessor_mode.write(self.client, int(mode == 'DirectSwitch'))
        else:
            mode = self.mode

        if mode == 'DirectSwitch' and ds_mode in self.ds_modes:
            self.ds_mode = ds_mode
            await self.accessor_polarity.write(self.client, int(ds_mode == 'Inverted'))
            await self.accessor_toggle.write(self.client, int(ds_mode == 'Toggle'))


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

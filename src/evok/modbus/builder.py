#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Sep 25 16:10:02 2026

@author: bokula
"""
from .digital import DigitalInput, DigitalOutput, Relay, ULED
from .special import OwPower, NvSave, Watchdog
from .analog import AnalogInput, AnalogOutput, AnalogOutputBrain,\
    Register, DataPoint, OwTemperature
from ..devices import \
    DI, DO, RO, AI, AO, OWPOWER, LED, WATCHDOG, \
    REGISTER, DATA_POINT, NV_SAVE, Devices
from ..log import logger
from .client import Client
from .pwm import HardPwmFrequency, SoftPwmFrequency


class IOParser:

    def __init__(self, client: Client, hw_features: list[dict], circuit=None):
        self.hw_features = hw_features
        self.client = client
        self.circuit = circuit

    def _register(self, devtype, device):
        """ Register the device, a duplicate circuit raises ValueError, it replaced the registered device """
        if str(device.circuit) in Devices[devtype]:
            raise ValueError(f"Duplicate circuit {devtype} {device.circuit}, use start_index of the feature")
        if hasattr(device, 'check_new_data'):
            self.client.eventable_devices.append(device)
        Devices.register_device(devtype, device)

    def io_circuit(self, i, m_feature):
        """ Circuit of the IO, start_index numbers the IOs of a feature following another one """
        return "%s_%02d" % (self.circuit, i + 1 + m_feature.get('start_index', 0))

    @staticmethod
    def bit_reg(reg, i):
        """ Register of the IO with bits for 16 IOs in one register, the IOs 17-32 are in the next register """
        return reg + i // 16

    def parse_feature_di(self, max_count, m_feature):
        """ The value and the DirectSwitch registers have the bits of 16 inputs, the next 16 are in the next ones """
        has_direct_switch = all(key in m_feature for key in ('ds_modes', 'direct_reg', 'polar_reg', 'toggle_reg'))
        for i in range(max_count):
            direct_switch = dict(ds_modes=m_feature['ds_modes'],
                                 regmode=self.bit_reg(m_feature['direct_reg'], i),
                                 regtoggle=self.bit_reg(m_feature['toggle_reg'], i),
                                 regpolarity=self.bit_reg(m_feature['polar_reg'], i)) if has_direct_switch else {}
            _inp = DigitalInput(self.io_circuit(i, m_feature), self.client,
                                self.bit_reg(m_feature['val_reg'], i), 0x1 << (i % 16),
                                regdebounce=m_feature['deboun_reg'] + i,
                                major_group=self.circuit, regcounter=m_feature['counter_reg'] + (2 * i),
                                modes=m_feature['modes'], **direct_switch)
            self._register(DI, _inp)

    def parse_feature_ro(self, max_count, m_feature):
        for i in range(max_count):
            board_val_reg = self.bit_reg(m_feature['val_reg'], i)
            _r = Relay(self.io_circuit(i, m_feature), self.client, m_feature['val_coil'] + i,
                       board_val_reg, 0x1 << (i % 16), major_group=self.circuit)
            self._register(RO, _r)

    def parse_feature_do(self, max_count, m_feature):
        if m_feature.get('pwm_reg') and m_feature.get('pwm_ps_reg') and m_feature.get('pwm_c_reg'):
            pwm = HardPwmFrequency(self.client, m_feature['pwm_c_reg'], m_feature['pwm_ps_reg'])
        elif m_feature.get('pwm_reg') and m_feature.get('pwm_preset_reg') and m_feature.get('pwm_cpres_reg'):
            pwm = SoftPwmFrequency(self.client, m_feature['pwm_preset_reg'], m_feature['pwm_cpres_reg'])
        else:
            raise ValueError(f"Unexpected feature  {m_feature['type']}")
        for i in range(max_count):
            _r = DigitalOutput(self.io_circuit(i, m_feature), self.client,
                               m_feature['val_coil'] + i, self.bit_reg(m_feature['val_reg'], i),
                               0x1 << (i % 16),
                               major_group=self.circuit, pwm=pwm,
                               pwmdutyreg=m_feature['pwm_reg'] + i, modes=m_feature['modes'])
            self._register(DO, _r)

    def parse_feature_led(self, max_count, m_feature):
        for i in range(max_count):
            board_val_reg = self.bit_reg(m_feature['val_reg'], i)
            _led = ULED(self.io_circuit(i, m_feature), self.client, m_feature['val_coil'] + i,
                        board_val_reg, 0x1 << (i % 16), major_group=self.circuit)
            self._register(LED, _led)

    def parse_feature_owpower(self, m_feature):
        _owpower = OwPower(f"{self.circuit}", self.client, m_feature['val_coil'], major_group=self.circuit)
        self._register(OWPOWER, _owpower)

    def parse_feature_nv_save(self, m_feature):
        _nv_save = NvSave(f"{self.circuit}", self.client, m_feature['val_coil'], major_group=self.circuit)
        self._register(NV_SAVE, _nv_save)

    def parse_feature_wd(self, m_feature):
        _wd = Watchdog(self.circuit, self.client,
                       m_feature['val_reg'],
                       m_feature['timeout_reg'],
                       m_feature['reset_coil'],
                       major_group=self.circuit)
        self._register(WATCHDOG, _wd)

    def parse_feature_ao(self, max_count, m_feature):
        for i in range(max_count):
            circuit = "%s_%02d" % (self.circuit, i + 1)
            board_val_reg = m_feature['val_reg']
            modes = m_feature['modes']
            reg_mode = m_feature.get('mode_reg', None)
            _ao = AnalogOutput(circuit, self.client, board_val_reg + i,
                               major_group=self.circuit, modes=modes, regmode=reg_mode)
            self._register(AO, _ao)

    def parse_feature_bao(self, max_count, m_feature):
        """ The Brain AO is a single output, its mode and resistance registers are not per output """
        if max_count > 1:
            raise ValueError(f"BAO can have only one output, count is {max_count}")
        if max_count < 1:
            return
        circuit = "%s_%02d" % (self.circuit, 1)
        _ao = AnalogOutputBrain(circuit, self.client, m_feature['val_reg'],
                                regmode=m_feature.get('mode_reg'), reg_res=m_feature.get('res_val_reg'),
                                major_group=self.circuit)
        self._register(AO, _ao)

    def parse_feature_ai(self, max_count, m_feature):
        for i in range(max_count):
            circuit = "%s_%02d" % (self.circuit, i + 1)
            board_val_reg = m_feature['val_reg'] + i * 2
            modes = m_feature['modes']
            _ai = AnalogInput(circuit, self.client, board_val_reg,
                              regmode=(m_feature['mode_reg'] + i
                                       if m_feature.get('mode_reg', None) is not None else None),
                              major_group=self.circuit, modes=modes)

            self._register(AI, _ai)

    def parse_feature_register(self, max_count, m_feature):
        for i in range(max_count):
            board_val_reg = m_feature['start_reg']
            if 'reg_type' in m_feature and m_feature['reg_type'] == 'input':
                _reg = Register("%s_%d_inp" % (self.circuit, board_val_reg + i), self.client,
                                board_val_reg + i, reg_type='input',
                                major_group=self.circuit)
            else:
                _reg = Register("%s_%d" % (self.circuit, board_val_reg + i), self.client,
                                board_val_reg + i, major_group=self.circuit)
            self._register(REGISTER, _reg)

    def parse_feature_data_point(self, max_count, m_feature):
        """ The data points follow each other, a 32-bit one takes two registers """
        _kwargs = dict(reg_type=m_feature.get("reg_type"), datatype=m_feature.get('datatype'),
                       major_group=self.circuit, offset=m_feature.get("offset", 0),
                       factor=m_feature.get("factor", 1), unit=m_feature.get("unit"), name=m_feature.get("name"),
                       writable=m_feature.get("writable", False))
        _valid_mask_reg = m_feature.get('valid_mask_reg')
        reg = m_feature['value_reg']
        for i in range(max_count):
            _circuit = "{}_{}".format(self.circuit, reg)
            if _valid_mask_reg is not None:
                _xgt = OwTemperature(_circuit, self.client, reg, _valid_mask_reg, 1 << i, **_kwargs)
            else:
                _xgt = DataPoint(_circuit, self.client, reg, **_kwargs)

            self._register(DATA_POINT, _xgt)
            reg += _xgt.accessor.count

    def parse_feature(self, m_feature):
        max_count = m_feature.get('count', 1)
        if m_feature['type'] == 'DI':
            self.parse_feature_di(max_count, m_feature)
        elif m_feature['type'] == 'RO':
            self.parse_feature_ro(max_count, m_feature)
        elif m_feature['type'] == 'DO':
            self.parse_feature_do(max_count, m_feature)
        elif m_feature['type'] == 'LED':
            self.parse_feature_led(max_count, m_feature)
        elif m_feature['type'] == 'AO':
            self.parse_feature_ao(max_count, m_feature)
        elif m_feature['type'] == 'BAO':
            self.parse_feature_bao(max_count, m_feature)
        elif m_feature['type'] == 'AI':
            self.parse_feature_ai(max_count, m_feature)
        elif m_feature['type'] == 'REGISTER':
            self.parse_feature_register(max_count, m_feature)
        elif m_feature['type'] == 'DATA_POINT':
            self.parse_feature_data_point(max_count, m_feature)
        elif m_feature['type'] == 'WD':
            self.parse_feature_wd(m_feature)
        elif m_feature['type'] == 'OWPOWER':
            self.parse_feature_owpower(m_feature)
        elif m_feature['type'] == 'NV_SAVE':
            self.parse_feature_nv_save(m_feature)
        else:
            logger.warning(f"Unknown feature: {m_feature['type']} at board: {self.circuit}")

    def populate(self):
        """ An invalid feature is skipped, the other devices of the unit are created """
        for m_feature in self.hw_features:
            try:
                self.parse_feature(m_feature)
            except Exception as E:
                logger.error(f"Invalid feature {m_feature.get('type')} at board {self.circuit}: {E!r}")

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

    def __register_eventable_device(self, device):
        if hasattr(device, 'check_new_data'):
            self.client.eventable_devices.append(device)

    @staticmethod
    def bit_reg(reg, counter):
        """ Register of the IO with bits for 16 IOs in one register, the IOs 17-32 are in the next register """
        return reg + counter // 16

    def parse_feature_di(self, max_count, m_feature):
        counter = 0
        while counter < max_count:
            board_val_reg = m_feature['val_reg']
            board_counter_reg = m_feature['counter_reg']
            board_deboun_reg = m_feature['deboun_reg']
            start_index = 0
            if 'start_index' in m_feature:
                start_index = m_feature['start_index']
            if ('ds_modes' in m_feature) and ('direct_reg' in m_feature) and ('polar_reg' in m_feature) \
                    and ('toggle_reg' in m_feature):
                _inp = DigitalInput("%s_%02d" % (self.circuit, counter + 1 + start_index), self.client, board_val_reg,
                                    0x1 << (counter % 16), regdebounce=board_deboun_reg + counter,
                                    major_group=self.circuit, regcounter=board_counter_reg + (2 * counter),
                                    modes=m_feature['modes'], ds_modes=m_feature['ds_modes'],
                                    regmode=m_feature['direct_reg'], regtoggle=m_feature['toggle_reg'],
                                    regpolarity=m_feature['polar_reg'])
            else:
                _inp = DigitalInput("%s_%02d" % (self.circuit, counter + 1 + start_index), self.client, board_val_reg,
                                    0x1 << (counter % 16), regdebounce=board_deboun_reg + counter,
                                    major_group=self.circuit, regcounter=board_counter_reg + (2 * counter),
                                    modes=m_feature['modes'])
            self.__register_eventable_device(_inp)
            Devices.register_device(DI, _inp)
            counter += 1

    def parse_feature_ro(self, max_count, m_feature):
        counter = 0
        while counter < max_count:
            board_val_reg = self.bit_reg(m_feature['val_reg'], counter)
            _r = Relay("%s_%02d" % (self.circuit, counter + 1), self.client, m_feature['val_coil'] + counter,
                       board_val_reg, 0x1 << (counter % 16), major_group=self.circuit)
            self.__register_eventable_device(_r)
            Devices.register_device(RO, _r)
            counter += 1

    def parse_feature_do(self, max_count, m_feature):
        if m_feature.get('pwm_reg') and m_feature.get('pwm_ps_reg') and m_feature.get('pwm_c_reg'):
            pwm = HardPwmFrequency(self.client, m_feature['pwm_c_reg'], m_feature['pwm_ps_reg'])
        elif m_feature.get('pwm_reg') and m_feature.get('pwm_preset_reg') and m_feature.get('pwm_cpres_reg'):
            pwm = SoftPwmFrequency(self.client, m_feature['pwm_preset_reg'], m_feature['pwm_cpres_reg'])
        else:
            raise ValueError(f"Unexpected feature  {m_feature['type']}")
        counter = 0
        while counter < max_count:
            _r = DigitalOutput("%s_%02d" % (self.circuit, counter + 1), self.client,
                               m_feature['val_coil'] + counter, self.bit_reg(m_feature['val_reg'], counter),
                               0x1 << (counter % 16),
                               major_group=self.circuit, pwm=pwm,
                               pwmdutyreg=m_feature['pwm_reg'] + counter, modes=m_feature['modes'])
            self.__register_eventable_device(_r)
            Devices.register_device(DO, _r)
            counter += 1

    def parse_feature_led(self, max_count, m_feature):
        counter = 0
        while counter < max_count:
            board_val_reg = self.bit_reg(m_feature['val_reg'], counter)
            _led = ULED("%s_%02d" % (self.circuit, counter + 1), self.client, m_feature['val_coil'] + counter,
                        board_val_reg, 0x1 << (counter % 16), major_group=self.circuit)
            self.__register_eventable_device(_led)
            Devices.register_device(LED, _led)
            counter += 1

    def parse_feature_owpower(self, m_feature):
        _owpower = OwPower(f"{self.circuit}", self.client, m_feature['val_coil'], major_group=self.circuit)
        self.__register_eventable_device(_owpower)
        Devices.register_device(OWPOWER, _owpower)

    def parse_feature_nv_save(self, m_feature):
        _nv_save = NvSave(f"{self.circuit}", self.client, m_feature['val_coil'], major_group=self.circuit)
        self.__register_eventable_device(_nv_save)
        Devices.register_device(NV_SAVE, _nv_save)

    def parse_feature_wd(self, max_count, m_feature):
        counter = 0
        while counter < max_count:
            board_val_reg = m_feature['val_reg']
            board_timeout_reg = m_feature['timeout_reg']
            _wd = Watchdog("%s_%02d" % (self.circuit, counter + 1), self.client, counter, board_val_reg + counter,
                           board_timeout_reg + counter, major_group=self.circuit,
                           nv_save_coil=m_feature['nv_sav_coil'], reset_coil=m_feature['reset_coil'])
            self.__register_eventable_device(_wd)
            Devices.register_device(WATCHDOG, _wd)
            counter += 1

    def parse_feature_ao(self, max_count, m_feature):
        counter = 0
        while counter < max_count:
            board_val_reg = m_feature['val_reg']
            modes = m_feature['modes']
            reg_mode = m_feature.get('mode_reg', None)
            _ao = AnalogOutput("%s_%02d" % (self.circuit, counter + 1), self.client, board_val_reg + counter,
                               major_group=self.circuit, modes=modes, regmode=reg_mode)
            self.__register_eventable_device(_ao)
            Devices.register_device(AO, _ao)
            counter += 1

    def parse_feature_bao(self, max_count, m_feature):
        counter = 0
        while counter < max_count:
            board_val_reg = m_feature['val_reg']
            reg_mode = m_feature.get('mode_reg', None)
            _ao = AnalogOutputBrain("%s_%02d" % (self.circuit, counter + 1), self.client, board_val_reg + counter,
                                    regmode=reg_mode, reg_res=m_feature['res_val_reg'], major_group=self.circuit)
            self.__register_eventable_device(_ao)
            Devices.register_device(AO, _ao)
            counter += 1

    def parse_feature_ai(self, max_count, m_feature):
        counter = 0
        while counter < max_count:
            circuit = "%s_%02d" % (self.circuit, counter + 1)
            board_val_reg = m_feature['val_reg'] + counter * 2
            modes = m_feature['modes']
            _ai = AnalogInput(circuit, self.client, board_val_reg,
                              regmode=(m_feature['mode_reg'] + counter
                                       if m_feature.get('mode_reg', None) is not None else None),
                              major_group=self.circuit, modes=modes)

            self.__register_eventable_device(_ai)
            Devices.register_device(AI, _ai)
            counter += 1

    def parse_feature_register(self, max_count, m_feature):
        counter = 0
        while counter < max_count:
            board_val_reg = m_feature['start_reg']
            if 'reg_type' in m_feature and m_feature['reg_type'] == 'input':
                _reg = Register("%s_%d_inp" % (self.circuit, board_val_reg + counter), self.client,
                                board_val_reg + counter, reg_type='input',
                                major_group=self.circuit)
            else:
                _reg = Register("%s_%d" % (self.circuit, board_val_reg + counter), self.client,
                                board_val_reg + counter, major_group=self.circuit)
            self.__register_eventable_device(_reg)
            Devices.register_device(REGISTER, _reg)
            counter += 1

    def parse_feature_data_point(self, max_count, m_feature):
        counter = 0
        board_val_reg = m_feature['value_reg']
        while counter < max_count:

            _offset = m_feature.get("offset", 0)
            _factor = m_feature.get("factor", 1)
            _unit = m_feature.get("unit")
            _name = m_feature.get("name")
            _valid_mask_reg = m_feature.get('valid_mask_reg')
            _datatype = m_feature.get('datatype')
            _reg_type = m_feature.get("reg_type", None)
            _writable = m_feature.get("writable", False)

            _circuit = "{}_{}".format(self.circuit, board_val_reg + counter)
            _kwargs = dict(reg_type=_reg_type, datatype=_datatype, major_group=self.circuit,
                           offset=_offset, factor=_factor, unit=_unit, name=_name, writable=_writable)
            if _valid_mask_reg is not None:
                _xgt = OwTemperature(_circuit, self.client, board_val_reg + counter,
                                     _valid_mask_reg, 1 << counter, **_kwargs)
            else:
                _xgt = DataPoint(_circuit, self.client, board_val_reg + counter, **_kwargs)

            self.__register_eventable_device(_xgt)
            Devices.register_device(DATA_POINT, _xgt)
            counter += 1

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
        elif m_feature['type'] == 'WD':
            self.parse_feature_wd(max_count, m_feature)
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

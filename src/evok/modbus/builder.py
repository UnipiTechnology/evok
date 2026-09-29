#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Sep 25 16:10:02 2026

@author: bokula
"""
import logging

from .digital import DigitalInput, DigitalOutput, Relay, ULED, OwPower,\
                     NvSave, Watchdog
from .analog import  AnalogInput, AnalogOutput, AnalogOutputBrain,\
                     Register, DataPoint
from ..devices import \
                     DI, DO, RO, AI, AO, OWPOWER, LED, WATCHDOG, \
                     REGISTER, DATA_POINT, BOARD, NV_SAVE, Devices

from .cache import ModbusCacheMap, ENoCacheRegister
from ..errors import ModbusSlaveError

class IOParser:

    legacy_mode = True

    def __init__(self, modbus_slave, hw_features: list[dict], circuit=None):
        self.hw_features = hw_features
        self.modbus_slave = modbus_slave
        self.circuit = circuit

    @property
    def cache(self):
        """ Register cache used by the devices """
        return self.modbus_slave.cache

    @property
    def client(self):
        """ Modbus client used by the devices for writes """
        return self.modbus_slave.mb_client

    def __register_eventable_device(self, device):
        if hasattr(device, 'check_new_data'):
            self.modbus_slave.eventable_devices.append(device)

    def parse_feature_di(self, max_count, m_feature):
        counter = 0
        while counter < max_count:
            board_val_reg = m_feature['val_reg']
            board_counter_reg = m_feature['counter_reg']
            board_deboun_reg = m_feature['deboun_reg']
            start_index = 0
            if 'start_index' in m_feature:
                start_index = m_feature['start_index']
            if ('ds_modes' in m_feature) and ('direct_reg' in m_feature) and ('polar_reg' in m_feature) and ('toggle_reg' in m_feature):
                _inp = DigitalInput("%s_%02d" % (self.circuit, counter + 1 + start_index), self, board_val_reg, 0x1 << (counter % 16),
                                    regdebounce=board_deboun_reg + counter, major_group=self.circuit, regcounter=board_counter_reg + (2 * counter), modes=m_feature['modes'],
                                    ds_modes=m_feature['ds_modes'], regmode=m_feature['direct_reg'], regtoggle=m_feature['toggle_reg'],
                                    regpolarity=m_feature['polar_reg'], legacy_mode=self.legacy_mode)
            else:
                _inp = DigitalInput("%s_%02d" % (self.circuit, counter + 1 + start_index), self, board_val_reg, 0x1 << (counter % 16),
                                    regdebounce=board_deboun_reg + counter, major_group=self.circuit, regcounter=board_counter_reg + (2 * counter), modes=m_feature['modes'],
                                    legacy_mode=self.legacy_mode)
            self.__register_eventable_device(_inp)
            Devices.register_device(DI, _inp)
            counter+=1

    def parse_feature_ro(self, max_count, m_feature):
        counter = 0
        while counter < max_count:
            board_val_reg = m_feature['val_reg']
            _r = Relay("%s_%02d" % (self.circuit, counter + 1), self, m_feature['val_coil'] + counter, board_val_reg, 0x1 << (counter % 16),
                      major_group=self.circuit, legacy_mode=self.legacy_mode)
            self.__register_eventable_device(_r)
            Devices.register_device(RO, _r)
            counter += 1

    def parse_feature_do(self, max_count, m_feature):
        counter = 0
        while counter < max_count:
            board_val_reg = m_feature['val_reg']
            # Hard PWM
            if m_feature.get('pwm_reg') and m_feature.get('pwm_ps_reg') and m_feature.get('pwm_c_reg'):
                if not self.legacy_mode:
                    _r = DigitalOutput("%s_%02d" % (self.circuit, counter + 1), self, m_feature['val_coil'] + counter, board_val_reg, 0x1 << (counter % 16),
                                       major_group=self.circuit, pwmcyclereg=m_feature['pwm_c_reg'], pwmprescalereg=m_feature['pwm_ps_reg'], digital_only=True,
                                       pwmdutyreg=m_feature['pwm_reg'] + counter, modes=m_feature['modes'], legacy_mode=self.legacy_mode)
                else:
                    _r = DigitalOutput("%s_%02d" % (self.circuit, counter + 1), self, m_feature['val_coil'] + counter, board_val_reg, 0x1 << (counter % 16),
                                       major_group=self.circuit, pwmcyclereg=m_feature['pwm_c_reg'], pwmprescalereg=m_feature['pwm_ps_reg'], digital_only=True,
                                       pwmdutyreg=m_feature['pwm_reg'] + counter, modes=m_feature['modes'], legacy_mode=self.legacy_mode)
            # Soft PWM
            elif m_feature.get('pwm_reg') and m_feature.get('pwm_preset_reg') and m_feature.get('pwm_cpres_reg'):
                _r = DigitalOutput("%s_%02d" % (self.circuit, counter + 1), self, m_feature['val_coil'] + counter, board_val_reg, 0x1 << (counter % 16),
                                   major_group=self.circuit, pwmpresetreg=m_feature['pwm_preset_reg'],
                                   pwmcustompresc=m_feature['pwm_cpres_reg'], digital_only=True,
                                   pwmdutyreg=m_feature['pwm_reg'] + counter, modes=m_feature['modes'], legacy_mode=self.legacy_mode)
            else:
                raise ValueError(f"Unexpected feature  {m_feature['type']}")
            self.__register_eventable_device(_r)
            Devices.register_device(DO, _r)
            counter += 1

    def parse_feature_led(self, max_count, m_feature):
        counter = 0
        while counter < max_count:
            board_val_reg = m_feature['val_reg']
            _led = ULED("%s_%02d" % (self.circuit, counter + 1), self, counter, board_val_reg, 0x1 << (counter % 16),
                        m_feature['val_coil'] + counter, major_group=self.circuit, legacy_mode=self.legacy_mode)
            self.__register_eventable_device(_led)
            Devices.register_device(LED, _led)
            counter+=1

    def parse_feature_owpower(self, m_feature):
        _owpower = OwPower(f"{self.circuit}", self, m_feature['val_coil'], major_group=self.circuit)
        self.__register_eventable_device(_owpower)
        Devices.register_device(OWPOWER, _owpower)

    def parse_feature_nv_save(self, m_feature):
        _nv_save = NvSave(f"{self.circuit}", self, m_feature['val_coil'], major_group=self.circuit)
        self.__register_eventable_device(_nv_save)
        Devices.register_device(NV_SAVE, _nv_save)

    def parse_feature_wd(self, max_count, m_feature):
        counter = 0
        while counter < max_count:
            board_val_reg = m_feature['val_reg']
            board_timeout_reg = m_feature['timeout_reg']
            _wd = Watchdog("%s_%02d" % (self.circuit, counter + 1), self, counter, board_val_reg + counter, board_timeout_reg + counter,
                           major_group=self.circuit, nv_save_coil=m_feature['nv_sav_coil'], reset_coil=m_feature['reset_coil'],
                           legacy_mode=self.legacy_mode)
            self.__register_eventable_device(_wd)
            Devices.register_device(WATCHDOG, _wd)
            counter+=1

    def parse_feature_ao(self, max_count, m_feature):
        counter = 0
        while counter < max_count:
            board_val_reg = m_feature['val_reg']
            modes = m_feature['modes']
            reg_mode = m_feature.get('mode_reg', None)
            _ao = AnalogOutput("%s_%02d" % (self.circuit, counter + 1), self, board_val_reg + counter,
                               major_group=self.circuit, modes=modes, regmode=reg_mode)
            self.__register_eventable_device(_ao)
            Devices.register_device(AO, _ao)
            counter+=1

    def parse_feature_bao(self, max_count, m_feature):
        counter = 0
        while counter < max_count:
            board_val_reg = m_feature['val_reg']
            reg_mode = m_feature.get('mode_reg', None)
            _ao = AnalogOutputBrain("%s_%02d" % (self.circuit, counter + 1), self, board_val_reg + counter,
                                    regmode=reg_mode, reg_res=m_feature['res_val_reg'], major_group=self.circuit)
            self.__register_eventable_device(_ao)
            Devices.register_device(AO, _ao)
            counter+=1

    def parse_feature_ai(self, max_count, m_feature):
        counter = 0
        while counter < max_count:
            circuit = "%s_%02d" % (self.circuit, counter + 1)
            board_val_reg = m_feature['val_reg'] + counter * 2
            modes = m_feature['modes']
            _ai = AnalogInput(circuit, self, board_val_reg,
                              regmode=m_feature['mode_reg'] + counter if m_feature.get('mode_reg', None) is not None else None,
                              major_group=self.circuit, modes=modes, legacy_mode=self.legacy_mode)

            self.__register_eventable_device(_ai)
            Devices.register_device(AI, _ai)
            counter+=1

    def parse_feature_register(self, max_count, m_feature):
        counter = 0
        while counter < max_count:
            board_val_reg = m_feature['start_reg']
            if 'reg_type' in m_feature and m_feature['reg_type'] == 'input':
                _reg = Register("%s_%d_inp" % (self.circuit, board_val_reg + counter), self, counter,
                                board_val_reg + counter, reg_type='input',
                                major_group=self.circuit, legacy_mode=self.legacy_mode)
            else:
                _reg = Register("%s_%d" % (self.circuit, board_val_reg + counter), self, counter,
                                board_val_reg + counter, major_group=self.circuit, legacy_mode=self.legacy_mode)
            Devices.register_device(REGISTER, _reg)
            counter+=1

    def parse_feature_data_point(self, max_count, m_feature):
        counter = 0
        board_val_reg = m_feature['value_reg']
        while counter < max_count:

            #self, circuit, arm, post, reg, major_group=0

            _offset = m_feature.get("offset", 0)
            _factor = m_feature.get("factor", 1)
            _unit = m_feature.get("unit")
            _name = m_feature.get("name")
            _valid_mask_reg = m_feature.get('valid_mask_reg')
            _post_write_action = m_feature.get('post_write')
            _datatype = m_feature.get('datatype')
            _reg_type = m_feature.get("reg_type", None)

            _xgt = DataPoint("{}_{}".format(self.circuit, board_val_reg + counter), self,
                             board_val_reg + counter, reg_type=_reg_type, datatype=_datatype,
                             major_group=self.circuit, offset=_offset, factor=_factor, unit=_unit,
                             valid_mask=1 << counter, valid_mask_reg=_valid_mask_reg, name=_name,
                             post_write=_post_write_action)

            self.__register_eventable_device(_xgt)
            Devices.register_device(DATA_POINT, _xgt)
            counter+=1

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
            logging.warning("Unknown feature: " + str(m_feature['type']) + " at board: " + str(self.circuit))

    def populate(self):
        for m_feature in self.hw_features:
            self.parse_feature(m_feature)


class Board(IOParser):
    def __init__(self, evok_config, circuit, modbus_address, modbus_slave, hw_definition: dict, major_group=1):
        super().__init__(modbus_slave, hw_definition.get('modbus_features', []),
                         circuit=circuit)
        self.alias = ""
        self.devtype = BOARD
        self.evok_config = evok_config
        self.modbus_address = modbus_address
        self.hw_definition = hw_definition

    @property
    def cache(self):
        return self.modbus_slave.modbus_cache_map

    @property
    def client(self):
        return self.modbus_slave.client

    async def set(self, alias=None):
        if not alias is None:
            Devices.set_alias(alias, self)
        return await self.full()

    async def initialise_cache(self, cache_definition):
        if 'modbus_register_blocks' in cache_definition:
            if self.modbus_slave.modbus_cache_map is None:
                self.modbus_slave.modbus_cache_map = ModbusCacheMap(cache_definition['modbus_register_blocks'], self.modbus_slave)
                await self.modbus_slave.modbus_cache_map.do_scan(initial=True)
                await self.modbus_slave.modbus_cache_map.sem.acquire()
                self.modbus_slave.modbus_cache_map.sem.release()
            else:
                await self.modbus_slave.modbus_cache_map.sem.acquire()
                self.modbus_slave.modbus_cache_map.sem.release()
        else:
            raise Exception("HW Definition %s requires Modbus register blocks to be specified" % cache_definition['type'])

    async def parse_definition(self):
        try:
            await self.initialise_cache(self.hw_definition)
            self.populate()
        except ENoCacheRegister as E:
            raise ModbusSlaveError(f"Error while parsing HW definition. ({E}) \t Please check your configuration file.")

    def get(self):
        return self.full()

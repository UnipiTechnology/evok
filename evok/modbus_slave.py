"""
  Code specific to Modbus devices
------------------------------------------
"""
from copy import copy, deepcopy
import math
import datetime
from math import sqrt
from typing import Union

from tornado.ioloop import IOLoop
from pymodbus.client import AsyncModbusTcpClient, AsyncModbusSerialClient
from pymodbus.pdu import ExceptionResponse
from pymodbus.exceptions import ModbusIOException, ConnectionException
from pymodbus.payload import BinaryPayloadDecoder, BinaryPayloadBuilder
from pymodbus.constants import Endian
from tornado.locks import Semaphore

from .devices import *
from .errors import ENoCacheRegister, ModbusSlaveError
from .modbus_unipi import EvokModbusSerialClient, EvokModbusTcpClient
from .log import *
from . import config
import time

import subprocess


def raise_if_null(data, index):
    if index >= len(data) or data[index] is None:
        raise ENoCacheRegister(f"No cached value of register '{index}'")
    return data[index]


class ModbusCacheMap(object):
    def __init__(self, modbus_reg_map, modbus_slave):
        self.last_comm_time = 0
        self.modbus_reg_map = deepcopy(modbus_reg_map)
        self.modbus_slave: ModbusSlave = modbus_slave
        self.sem = Semaphore(1)
        self.frequency = {}
        self._initialized = False
        for m_reg_group in self.modbus_reg_map:
            self.frequency[m_reg_group['start_reg']] = 10000001  # frequency less than 1/10 million are not read on start
            m_reg_group['values'] = [None for i in range(m_reg_group['count'])]
            m_reg_group['initialised'] = False

    def __get_reg_group(self, index: int, is_input: bool):
        group = None
        _index = None
        for m_reg_group in self.modbus_reg_map:
            group_is_input = m_reg_group.get('type', None) == 'input'
            if group_is_input is is_input and \
                    ((m_reg_group['start_reg']) <= index < (m_reg_group['count'] + m_reg_group['start_reg'])):
                group = m_reg_group['values']
                _index = index - m_reg_group['start_reg']
                # print(f"index: '{index}' cont: '{count}'\tfind in: '{m_reg_group}'")
                break
        if group is None:
            raise ValueError(f"get_reg_group: Unknown register {index}!")
        return group, _index

    def get_register(self, count, index, is_input=False):
        try:
            group, _index = self.__get_reg_group(index=index, is_input=is_input)
            return [raise_if_null(group, _index + i) for i in range(count)]
        except (IndexError, KeyError) as E:
            raise ValueError(f"get_register: get register {index} error: {E}")

    async def get_register_async(self, count, index, slave=0, is_input=False):
        group, group_index = self.__get_reg_group(index=index, is_input=is_input)
        # ^^ raise exception if index not in cache map!

        # read values from modbus
        if is_input:
            val = await self.modbus_slave.client.read_input_registers(index, count, slave=slave)
        else:
            val = await self.modbus_slave.client.read_holding_registers(index, count, slave=slave)

        # update cache map
        for i in range(len(val.registers)):
            group[group_index + i] = val.registers[i]
        return val.registers

    async def do_scan(self, slave=0) -> bool:
        if not self._initialized:
            await self.sem.acquire()
        changeset = []

        scanned = False
        for m_reg_group in self.modbus_reg_map:
            m_reg_group: dict
            if (self.frequency[m_reg_group['start_reg']] >= m_reg_group['frequency']) or (self.frequency[m_reg_group['start_reg']] == 0):    # only read once for every [frequency] cycles
                vals = None
                try:
                    # read values from modbus
                    if 'type' in m_reg_group and m_reg_group['type'] == 'input':
                        vals = await self.modbus_slave.client.read_input_registers(m_reg_group['start_reg'], m_reg_group['count'], slave=slave)
                    else:
                        vals = await self.modbus_slave.client.read_holding_registers(m_reg_group['start_reg'], m_reg_group['count'], slave=slave)

                    # check modbus response
                    if not isinstance(vals, ExceptionResponse) and not isinstance(vals, ModbusIOException) and\
                       vals is not None and len(vals.registers) == m_reg_group['count']:
                        # update modbus cache
                        m_reg_group['values'] = vals.registers

                        # call force update callbacks in registered devices and check differences
                        if self._initialized:
                            for device in self.modbus_slave.eventable_devices:
                                try:
                                    if await device.check_new_data() is True:
                                        changeset.append(device)
                                except Exception as E:
                                    m = (f"Error while checking new data in device '{device.devtype}"
                                         f"_{device.circuit}': {E}")
                                    logger.error(m)
                                    if logger.level == logging.DEBUG:
                                        traceback.print_exc()
                        else:
                            m_reg_group['initialised'] = True

                        # reset communication flags
                        self.last_comm_time = time.time()
                        scanned = True
                finally:
                    self.frequency[m_reg_group['start_reg']] = 1
            else:
                self.frequency[m_reg_group['start_reg']] += 1
        if len(changeset) > 0:
            proxy = Proxy(set(changeset))
            # print(f"changeset: {changeset}")
            devents.status(proxy)
        if not self._initialized:
            self._initialized = all([m['initialised'] for m in self.modbus_reg_map])
            self.sem.release()
        return scanned


class ModbusSlave(object):

    def __init__(self, client: Union[EvokModbusTcpClient, EvokModbusSerialClient],
                 circuit, evok_config, scan_freq, scan_enabled, hw_dict, slave_id=1,
                 major_group=1, device_model='unspecified'):
        self.alias = ""
        self.devtype = MODBUS_SLAVE
        self.modbus_cache_map = None
        self.eventable_devices = list()
        self.boards = list()
        self.hw_dict = hw_dict
        self.modbus_address = slave_id
        self.device_model = device_model
        self.evok_config = evok_config
        self.do_scanning = False
        self.is_scanning = False
        self.major_group = major_group
        self.hw_board_dict = {}
        if scan_freq == 0:
            self.scan_interval = 0.0001
            # scan_interval cannot be zero!! (slowing down device)
        else:
            self.scan_interval = 1.0 / scan_freq
        self.scan_errors = 0
        self.scan_enabled = scan_enabled
        self.versions = []
        self.logfile = evok_config.logging.get("file", "./evok.log")
        self.client: Union[AsyncModbusTcpClient, EvokModbusSerialClient] = client
        self.loop: Union[None, IOLoop] = None
        self.circuit: Union[None, str] = circuit
        self.modbus_type = 'UNKNOWN'
        self.modbus_spec = 'UNKNOWN'
        if type(self.client) in [EvokModbusTcpClient]:
            self.client: EvokModbusTcpClient
            self.modbus_type = 'TCP'
            self.modbus_spec = self.client.host
        elif type(self.client) in [EvokModbusSerialClient]:
            self.client: EvokModbusSerialClient
            self.modbus_type = 'RTU'
            self.modbus_spec = self.client.port

    def get(self):
        return self.full()

    def switch_to_async(self, loop: IOLoop):
        self.loop = loop
        self.readboards()

    async def set(self, print_log=None):
        if print_log is not None and print_log != 0:
            log_tail = subprocess.check_output(["tail", "-n 255", self.logfile])
            return log_tail
        else:
            return ""

    def readboards(self):
        logger.info(f"Initialing Modbus board on Modbus address {self.modbus_address}\t({self.circuit})")
        self.boards = list()
        try:
            if self.device_model not in self.hw_dict.definitions:
                raise KeyError(f"readboards: Unsupported device model {self.device_model}! (check HW definitions)")
            self.hw_board_dict = self.hw_dict.definitions[self.device_model]
            board = Board(self.evok_config, self.circuit, self.modbus_address, self)
            board.parse_definition(self.hw_dict)
            self.boards.append(board)
        except ConnectionException as E:
            logger.error(f"No board detected on Modbus {self.modbus_address}\t({type(E).__name__}:{E})")
            if logger.level == logging.DEBUG:
                traceback.print_exc()
        except Exception as E:
            logger.exception(str(E))
            pass

    def start_scanning(self):
        self.do_scanning = True
        if not self.is_scanning:
            self.loop.call_later(self.scan_interval, self.scan_boards)
            self.is_scanning = True

    def stop_scanning(self):
        if not self.scan_enabled:
            self.do_scanning = False

    async def scan_boards(self, invoc=False):
        if self.is_scanning and invoc:
            return
        try:
            if self.modbus_cache_map is not None:
                if await self.modbus_cache_map.do_scan(slave=self.modbus_address) is True:
                    if self.scan_errors:
                        logger.info(f"Communication with device is back: '{self.circuit}'")
                    self.scan_errors = 0
        except Exception as E:
            if not self.scan_errors:
                logger.error(f"{self.circuit}: Error while scanning: {E}")
                if logger.level == logging.DEBUG:
                    traceback.print_exc()
                logger.warning(f"Slowing down device: '{self.circuit}'")
            self.scan_errors += 1

        if self.do_scanning and (self.scan_interval != 0):
            interval = min(self.scan_interval*(2**self.scan_errors), 120)  # exponential growth with limitation [s]
            self.loop.call_later(interval, self.scan_boards)
            self.is_scanning = True
        else:
            self.is_scanning = False

    def full(self):
        ret = {'dev': 'modbus_slave',
               'circuit': self.circuit,
               'last_comm': 0x7fffffff,
               'slave_id': self.modbus_address,
               'modbus_type': self.modbus_type,
               'modbus_spec': self.modbus_spec,
               'scan_interval': self.scan_interval,
               }
        if self.alias != '':
            ret['alias'] = self.alias
        if self.modbus_cache_map is not None:
            ret['last_comm'] = time.time() - self.modbus_cache_map.last_comm_time

        # TODO: zkontrolovat, jestli existruji v 'self.client'
        'modbus_server'
        'modbus_port'
        'uart_circuit'
        'uart_port'

        if self.alias != '':
            ret['alias'] = self.alias
        if self.modbus_cache_map is not None:
            ret['last_comm'] = time.time() - self.modbus_cache_map.last_comm_time
        return ret


class Proxy(object):
    def __init__(self, changeset):
        self.changeset = changeset

    def full(self):
        self.result = [c.full() for c in self.changeset]
        self.full = self.fullcache
        return self.result

    def fullcache(self):
        return self.result


class Board(object):
    def __init__(self, evok_config, circuit, modbus_address, modbus_slave: ModbusSlave, major_group=1):
        self.alias = ""
        self.devtype = BOARD
        self.evok_config = evok_config
        self.circuit = circuit
        self.legacy_mode = True
        self.modbus_slave: ModbusSlave = modbus_slave
        self.major_group = major_group
        self.modbus_address = modbus_address

    async def set(self, alias=None):
        if not alias is None:
            Devices.set_alias(alias, self)
        return await self.full()

    def initialise_cache(self, cache_definition):
        if 'modbus_register_blocks' in cache_definition:
            if self.modbus_slave.modbus_cache_map is None:
                self.modbus_slave.modbus_cache_map = ModbusCacheMap(cache_definition['modbus_register_blocks'], self.modbus_slave)
        else:
            raise Exception("HW Definition %s requires Modbus register blocks to be specified" % cache_definition['type'])

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
                                    regdebounce=board_deboun_reg + counter, major_group=self.major_group, regcounter=board_counter_reg + (2 * counter), modes=m_feature['modes'],
                                    ds_modes=m_feature['ds_modes'], regmode=m_feature['direct_reg'], regtoggle=m_feature['toggle_reg'],
                                    regpolarity=m_feature['polar_reg'], legacy_mode=self.legacy_mode)
            else:
                _inp = DigitalInput("%s_%02d" % (self.circuit, counter + 1 + start_index), self, board_val_reg, 0x1 << (counter % 16),
                                    regdebounce=board_deboun_reg + counter, major_group=self.major_group, regcounter=board_counter_reg + (2 * counter), modes=m_feature['modes'],
                                    legacy_mode=self.legacy_mode)
            self.__register_eventable_device(_inp)
            Devices.register_device(DI, _inp)
            counter+=1

    def parse_feature_ro(self, max_count, m_feature):
        counter = 0
        while counter < max_count:
            board_val_reg = m_feature['val_reg']
            _r = Relay("%s_%02d" % (self.circuit, counter + 1), self, m_feature['val_coil'] + counter, board_val_reg, 0x1 << (counter % 16),
                      major_group=self.major_group, legacy_mode=self.legacy_mode)
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
                                       major_group=self.major_group, pwmcyclereg=m_feature['pwm_c_reg'], pwmprescalereg=m_feature['pwm_ps_reg'], digital_only=True,
                                       pwmdutyreg=m_feature['pwm_reg'] + counter, modes=m_feature['modes'], legacy_mode=self.legacy_mode)
                else:
                    _r = DigitalOutput("%s_%02d" % (self.circuit, counter + 1), self, m_feature['val_coil'] + counter, board_val_reg, 0x1 << (counter % 16),
                                       major_group=self.major_group, pwmcyclereg=m_feature['pwm_c_reg'], pwmprescalereg=m_feature['pwm_ps_reg'], digital_only=True,
                                       pwmdutyreg=m_feature['pwm_reg'] + counter, modes=m_feature['modes'], legacy_mode=self.legacy_mode)
            # Soft PWM
            elif m_feature.get('pwm_reg') and m_feature.get('pwm_preset_reg') and m_feature.get('pwm_cpres_reg'):
                _r = DigitalOutput("%s_%02d" % (self.circuit, counter + 1), self, m_feature['val_coil'] + counter, board_val_reg, 0x1 << (counter % 16),
                                   major_group=self.major_group, pwmpresetreg=m_feature['pwm_preset_reg'],
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
                        m_feature['val_coil'] + counter, major_group=self.major_group, legacy_mode=self.legacy_mode)
            self.__register_eventable_device(_led)
            Devices.register_device(LED, _led)
            counter+=1

    def parse_feature_owpower(self, m_feature):
        _owpower = OwPower(f"{self.circuit}", self, m_feature['val_coil'], major_group=self.major_group)
        self.__register_eventable_device(_owpower)
        Devices.register_device(OWPOWER, _owpower)

    def parse_feature_nv_save(self, m_feature):
        _nv_save = NvSave(f"{self.circuit}", self, m_feature['val_coil'], major_group=self.major_group)
        self.__register_eventable_device(_nv_save)
        Devices.register_device(NV_SAVE, _nv_save)

    def parse_feature_wd(self, max_count, m_feature):
        counter = 0
        while counter < max_count:
            board_val_reg = m_feature['val_reg']
            board_timeout_reg = m_feature['timeout_reg']
            _wd = Watchdog("%s_%02d" % (self.circuit, counter + 1), self, counter, board_val_reg + counter, board_timeout_reg + counter,
                           major_group=self.major_group, nv_save_coil=m_feature['nv_sav_coil'], reset_coil=m_feature['reset_coil'],
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
                               major_group=self.major_group, modes=modes, regmode=reg_mode)
            self.__register_eventable_device(_ao)
            Devices.register_device(AO, _ao)
            counter+=1

    def parse_feature_bao(self, max_count, m_feature):
        counter = 0
        while counter < max_count:
            board_val_reg = m_feature['val_reg']
            reg_mode = m_feature.get('mode_reg', None)
            _ao = AnalogOutputBrain("%s_%02d" % (self.circuit, counter + 1), self, board_val_reg + counter,
                                    regmode=reg_mode, reg_res=m_feature['res_val_reg'], major_group=self.major_group)
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
                              major_group=self.major_group, modes=modes, legacy_mode=self.legacy_mode)

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
                                major_group=self.major_group, legacy_mode=self.legacy_mode)
            else:
                _reg = Register("%s_%d" % (self.circuit, board_val_reg + counter), self, counter,
                                board_val_reg + counter, major_group=self.major_group, legacy_mode=self.legacy_mode)
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
                             major_group=self.major_group, offset=_offset, factor=_factor, unit=_unit,
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
            logging.warning("Unknown feature: " + str(m_feature['type']) + " at board: " + str(self.major_group))

    def parse_definition(self, hw_dict):
        try:
            for defin_name, defin in hw_dict.definitions.items():
                if defin and (self.modbus_slave.device_model == defin_name):
                    for m_feature in defin['modbus_features']:
                        self.initialise_cache(defin)
                        self.parse_feature(m_feature)
                    return
            logging.error(f"Not found type '{self.modbus_slave.device_model}' in loaded hw-definitions.")
        except ENoCacheRegister as E:
            raise ModbusSlaveError(f"Error while parsing HW definition. ({E}) \t Please check your configuration file.")

    def get(self):
        return self.full()


class DigitalOutput:
    pending_id = 0
    def __init__(self, circuit, arm, coil, reg, mask, major_group=0,
                 pwmcyclereg=-1, pwmprescalereg=-1, pwmdutyreg=-1, pwmpresetreg=-1, pwmcustompresc=-1 ,
                 legacy_mode=True, digital_only=False, modes=None):
        self.alias = ""
        self.devtype = DO
        self.circuit = circuit
        self.arm = arm
        self.modes = modes if modes is not None else ['Simple']
        # Soft-pwm
        self.pwmpresetreg = pwmpresetreg
        self.pwmcustompresc = pwmcustompresc
        # Hard-pwm
        self.pwmcyclereg = pwmcyclereg
        self.pwmprescalereg = pwmprescalereg
        self.pwmdutyreg = pwmdutyreg
        self.pwm_duty = None
        self.pwm_duty_val = None
        self.pwm_freq = None
        self.pwm_cycle_val = None
        self.pwm_prescale_val = None
        self.pwm_delay_val = None
        self.mode = None
        self.major_group = major_group
        self.legacy_mode = legacy_mode
        self.digital_only = digital_only
        self.coil = coil
        self.valreg = reg
        self.bitmask = mask
        self.regvalue = lambda: self.arm.modbus_slave.modbus_cache_map.get_register(1, self.valreg)[0]
        self.value = None
        self.block_pwm = False

        self.preset_map = {0: 1000, 1:100, 2:0}

        self.forced_changes = False  # force_immediate_state_changes

    def full(self, forced_value=None):
        ret =  {'dev': 'do',
                'circuit': self.circuit,
                'value': self.value,
                'pending': self.pending_id != 0,
                'mode': self.mode,
                'modes': self.modes,
                }
        if self.digital_only:
            ret['pwm_freq'] = self.pwm_freq
            ret['pwm_duty'] = self.pwm_duty
        if self.alias != '':
            ret['alias'] = self.alias
        if forced_value is not None:
            ret['value'] = forced_value
        return ret

    def simple(self):
        return {'dev': 'do',
                'circuit': self.circuit,
                'value': self.value}

    def get_state(self):
        """ Returns ( status, is_pending )
              current on/off status is taken from last mcp value without reading it from hardware
              is_pending is Boolean
        """
        return (self.value, self.pending_id != 0)

    async def set_state(self, value):
        """ Sets new on/off status. Disable pending timeouts
        """
        if self.pending_id:
            IOLoop.instance().remove_timeout(self.pending_id)
            self.pending_id = None
        await self.arm.modbus_slave.client.write_coil(self.coil, 1 if value else 0, slave=self.arm.modbus_address)
        return 1 if value else 0

    async def check_new_data(self):
        is_change = False
        if self.pwmdutyreg >= 0:  # This instance supports PWM mode
            if not self.block_pwm:
                if self.pwmpresetreg >=0:
                    old_prescale_val = copy(self.pwm_prescale_val)
                    old_cycle_val = copy(self.pwm_cycle_val)
                    self.pwm_prescale_val = (self.arm.modbus_slave.modbus_cache_map.get_register(1, self.pwmpresetreg))[0]
                    self.pwm_cycle_val = (self.arm.modbus_slave.modbus_cache_map.get_register(1, self.pwmcustompresc))[0]
                    if old_prescale_val != self.pwm_prescale_val or old_cycle_val != self.pwm_cycle_val:
                        if (self.pwm_prescale_val in self.preset_map) and self.preset_map[self.pwm_prescale_val] != 0:
                            self.pwm_freq = self.preset_map[self.pwm_prescale_val]
                        else:
                            self.pwm_freq = round(1000 / (1 + self.pwm_cycle_val),1)
                        is_change = True

                else:
                    old_cycle_val = copy(self.pwm_cycle_val)
                    old_prescale_val = copy(self.pwm_prescale_val)

                    self.pwm_cycle_val = ((self.arm.modbus_slave.modbus_cache_map.get_register(1, self.pwmcyclereg))[0] + 1)
                    self.pwm_prescale_val = ((self.arm.modbus_slave.modbus_cache_map.get_register(1, self.pwmprescalereg))[0] + 1)

                    if (old_cycle_val != self.pwm_cycle_val) or (old_prescale_val != self.pwm_prescale_val):
                        is_change = True
                        if (self.pwm_cycle_val > 0) and (self.pwm_prescale_val > 0):
                            self.pwm_freq = 48000000 / (self.pwm_cycle_val * self.pwm_prescale_val)
                        else:
                            self.pwm_freq = 0

                # PWM duty_val handling is almost same for both soft and hard PWM
                old_duty_val = copy(self.pwm_duty_val)
                self.pwm_duty_val = (self.arm.modbus_slave.modbus_cache_map.get_register(1, self.pwmdutyreg))[0]
                if is_change or old_duty_val != self.pwm_duty_val:
                    is_change = True
                    if self.pwm_duty_val == 0:
                        self.pwm_duty = 0
                        self.mode = 'Simple'  # Mode field is for backward compatibility, will be deprecated soon
                    elif self.pwmpresetreg >=0:
                        self.pwm_duty = self.pwm_duty_val
                        self.mode = 'PWM'  # Mode field is for backward compatibility, will be deprecated soon
                    else:
                        self.pwm_duty = round((float(self.pwm_duty_val) / float(self.pwm_cycle_val)) * 100, 1)
                        self.mode = 'PWM'  # Mode field is for backward compatibility, will be deprecated soon

        else:  # This RELAY instance does not support PWM mode (no pwmdutyreg given)
            self.mode = 'Simple'

        old_value = copy(self.value)
        self.value = 1 if (self.regvalue() & self.bitmask) else 0
        return is_change or old_value != self.value

    async def set(self, value=None, timeout=None, mode=None, pwm_freq=None, pwm_duty=None, alias=None):
        """ Sets new on/off status. Disable pending timeouts """
        try:
            if self.pending_id:
                IOLoop.instance().remove_timeout(self.pending_id)
                self.pending_id = None

            if pwm_duty is not None:
                pwm_duty = float(pwm_duty)

            if pwm_freq is not None:
                pwm_freq = float(pwm_freq)

            #if pwm_duty is not None and self.mode == 'PWM' and float(pwm_duty) <= 0.01:
            #    mode = 'Simple'
            # New system - mode field will no longer be used

            # Set PWM Freq
            if (pwm_freq is not None) and (pwm_freq > 0):
                self.block_pwm = True

                # Soft PWM
                if self.pwmpresetreg >=0:
                    pwm_preset_val = 0
                    if pwm_freq in self.preset_map.values():
                        pwm_preset_val = [preset for preset, freq in self.preset_map.items() if freq == pwm_freq][0]
                        await self.arm.modbus_slave.client.write_register(self.pwmpresetreg, pwm_preset_val, slave=self.arm.modbus_address)
                    else:
                        pwm_prescaler = round((1000 / pwm_freq) - 1)
                        if pwm_prescaler < 0:
                            raise ValueError(f"Frequency out of range!")
                        self.pwm_freq = round(1000 / (1 + pwm_prescaler),1)
                        await self.arm.modbus_slave.client.write_register(self.pwmpresetreg, 2, slave=self.arm.modbus_address)
                        await self.arm.modbus_slave.client.write_register(self.pwmcustompresc, pwm_prescaler, slave=self.arm.modbus_address)

                    other_devs = {dev: dev.pwm_duty for dev in Devices.by_int(DO, major_group=self.major_group)}

                    for other_dev, other_pwm_duty in other_devs.items():
                        other_dev.pwm_freq = self.pwm_freq

                else:
                    tmp_pwm_delay_val = 48000000 / pwm_freq
                    if ((int(tmp_pwm_delay_val) % 50000) == 0) and ((tmp_pwm_delay_val / 50000) < 65535):
                        tmp_pwm_cycle_val = 50000
                        tmp_pwm_prescale_val = round(tmp_pwm_delay_val / 50000)
                    elif ((int(tmp_pwm_delay_val) % 10000) == 0) and ((tmp_pwm_delay_val / 10000) < 65535):
                        tmp_pwm_cycle_val = 10000
                        tmp_pwm_prescale_val = round(tmp_pwm_delay_val / 10000)
                    elif ((int(tmp_pwm_delay_val) % 5000) == 0) and ((tmp_pwm_delay_val / 5000) < 65535):
                        tmp_pwm_cycle_val = 5000
                        tmp_pwm_prescale_val = round(tmp_pwm_delay_val / 5000)
                    elif ((int(tmp_pwm_delay_val) % 1000) == 0) and ((tmp_pwm_delay_val / 1000) < 65535):
                        tmp_pwm_cycle_val = 1000
                        tmp_pwm_prescale_val = round(tmp_pwm_delay_val / 1000)
                    else:
                        tmp_pwm_prescale_val = round(sqrt(tmp_pwm_delay_val))
                        tmp_pwm_cycle_val = round(tmp_pwm_prescale_val)
                    other_devs = {dev: float(dev.pwm_duty) for dev in Devices.by_int(DO, major_group=self.major_group)}

                    await self.arm.modbus_slave.client.write_register(self.pwmcyclereg, tmp_pwm_cycle_val - 1, slave=self.arm.modbus_address)
                    await self.arm.modbus_slave.client.write_register(self.pwmprescalereg, tmp_pwm_prescale_val - 1, slave=self.arm.modbus_address)

                    for other_dev, other_pwm_duty in other_devs.items():
                        other_dev.pwm_freq = pwm_freq
                        other_dev.pwm_delay_val = tmp_pwm_delay_val
                        other_dev.pwm_cycle_val = tmp_pwm_cycle_val
                        other_dev.pwm_prescale_val = tmp_pwm_prescale_val
                        if other_dev.pwm_duty > 0 and other_dev is not self:
                            await other_dev.set(pwm_duty=other_pwm_duty)
                self.block_pwm = False

            # Set Binary value
            if value is not None:

                parsed_value = 1 if int(value) else 0

                if pwm_duty is not None:
                    if (pwm_duty == 100 and parsed_value == 1) or (pwm_duty == 0 and parsed_value == 0): # No conflict in this case
                        pass
                    else:
                        raise Exception('Set value conflict: Cannot set both value and pwm_duty at once.')

                if not (timeout is None):
                    timeout = float(timeout)

                self.mode = 'Simple'
                await self.arm.modbus_slave.client.write_coil(self.coil, parsed_value, slave=self.arm.modbus_address)
                if self.pwm_duty is not None and self.pwm_duty != 0:
                    self.pwm_duty = 0
                    await self.arm.modbus_slave.client.write_register(self.pwmdutyreg, round(self.pwm_duty), slave=self.arm.modbus_address) # Turn off PWM

            # Set PWM Duty
            elif pwm_duty is not None and 0.0 <= pwm_duty <= 100.0:
                if self.pwmpresetreg >= 0:
                    tmp_pwm_duty_val = round(pwm_duty)
                else:
                    tmp_pwm_duty_val = round(float(self.pwm_cycle_val) * pwm_duty / 100.0)
                if self.value != 0:
                    await self.arm.modbus_slave.client.write_coil(self.coil, 0, slave=self.arm.modbus_address)
                await self.arm.modbus_slave.client.write_register(self.pwmdutyreg, tmp_pwm_duty_val, slave=self.arm.modbus_address)
                self.mode = 'PWM'

            if alias is not None:
                Devices.set_alias(alias, self)

            if timeout is None:
                return self.full()

            async def timercallback():
                self.pending_id = None
                await self.arm.modbus_slave.client.write_coil(self.coil, 0 if value else 1, slave=self.arm.modbus_address)

            self.pending_id = IOLoop.instance().add_timeout(
                datetime.timedelta(seconds=float(timeout)), timercallback)

            return self.full()

        except Exception as E:
            logger.error(f"Error in set DO: {E}")
            raise E

    def get(self):
        return self.full()


class Relay:

    def __init__(self, circuit, arm, coil, reg, mask, major_group=0, legacy_mode=True):
        self.alias = ""
        self.devtype = RO
        self.circuit = circuit
        self.arm = arm
        self.major_group = major_group
        self.legacy_mode = legacy_mode
        self.coil = coil
        self.valreg = reg
        self.bitmask = mask
        self.regvalue = lambda: self.arm.modbus_slave.modbus_cache_map.get_register(1, self.valreg)[0]
        self.value = None
        self.block_pwm = False

        self.forced_changes = False  # force_immediate_state_changes

    def full(self, forced_value=None):
        ret = {'dev': 'ro',
               'circuit': self.circuit,
               'value': self.value,
               }
        if self.alias != '':
            ret['alias'] = self.alias
        if forced_value is not None:
            ret['value'] = forced_value
        return ret

    def simple(self):
        return {'dev': 'ro',
                'circuit': self.circuit,
                'value': self.value}

    def get_state(self):
        """ Returns ( status, is_pending )
              current on/off status is taken from last mcp value without reading it from hardware
              is_pending is Boolean
        """
        return self.value

    async def set_state(self, value):
        """ Sets new on/off status. Disable pending timeouts
        """
        await self.arm.modbus_slave.client.write_coil(self.coil, 1 if value else 0, slave=self.arm.modbus_address)
        return 1 if value else 0

    async def check_new_data(self):
        old_value = copy(self.value)
        self.value = 1 if (self.regvalue() & self.bitmask) else 0
        return old_value != self.value

    async def set(self, value=None, alias=None):
        """ Sets new on/off status. Disable pending timeouts """
        try:

            # Set Binary value
            if value is not None:
                parsed_value = 1 if int(value) else 0
                await self.arm.modbus_slave.client.write_coil(self.coil, parsed_value, slave=self.arm.modbus_address)

            if alias is not None:
                Devices.set_alias(alias, self)

            return self.full()

        except Exception as E:
            logger.error(f"Error in set RO: {E}")
            if logger.level == logging.DEBUG:
                traceback.print_exc()
            raise E

    def get(self):
        return self.full()


class OwPower(object):
    def __init__(self, circuit, arm, coil, major_group=0):
        self.alias = ""
        self.devtype = OWPOWER
        self.circuit = circuit
        self.arm = arm
        self.major_group = major_group
        self.coil = coil
        self.value = 0
        self.simple = self.full

    def full(self):
        ret = {'dev': 'owpower', 'circuit': self.circuit, 'value': self.value}
        if self.alias != '':
            ret['alias'] = self.alias
        return ret

    def simple(self):
        return {'dev': 'owpower', 'circuit': self.circuit, 'value': self.value}

    async def set(self, value=None, alias=None):
        """ Sets new on/off status. Disable pending timeouts
        """
        if alias is not None:
            Devices.set_alias(alias, self)
        if value is not None:
            value = bool(int(value))
            self.value = value
            await self.arm.modbus_slave.client.write_coil(self.coil, 1 if value else 0, slave=self.arm.modbus_address)
        return self.full()

    def get(self):
        return self.full()


class NvSave(object):
    def __init__(self, circuit, arm, coil, major_group=0):
        self.alias = ""
        self.devtype = NV_SAVE
        self.circuit = circuit
        self.arm = arm
        self.major_group = major_group
        self.coil = coil
        self.value = 0
        self.simple = self.full

    def full(self):
        ret = {'dev': 'nv_save', 'circuit': self.circuit, 'value': self.value}
        if self.alias != '':
            ret['alias'] = self.alias
        return ret

    async def set(self, value=None, alias=None):
        """ Sets new on/off status. Disable pending timeouts
        """
        if alias is not None:
            Devices.set_alias(alias, self)
        if value is not None:
            value = bool(int(value))
            self.value = value
            await self.arm.modbus_slave.client.write_coil(self.coil, 1 if value else 0, slave=self.arm.modbus_address)
        return self.full()

    def get(self):
        return self.full()


class ULED(object):
    def __init__(self, circuit, arm, post, reg, mask, coil, major_group=0, legacy_mode=True):
        self.alias = ""
        self.devtype = LED
        self.circuit = circuit
        self.arm = arm
        self.major_group = major_group
        self.legacy_mode = legacy_mode
        self.bitmask = mask
        self.valreg = reg
        self.regvalue = lambda: self.arm.modbus_slave.modbus_cache_map.get_register(1, self.valreg)[0]
        self.coil = coil
        self.value = None

    def full(self):
        ret = {'dev': 'led', 'circuit': self.circuit, 'value': self.value}
        if self.alias != '':
            ret['alias'] = self.alias
        return ret

    def simple(self):
        return {'dev': 'led', 'circuit': self.circuit, 'value': self.value}

    def value_delta(self, new_val):
        return (self.regvalue() ^ new_val) & self.bitmask

    async def check_new_data(self):
        old_value = copy(self.value)
        self.value = 1 if (self.regvalue() & self.bitmask) else 0
        return old_value != self.value

    def get_state(self):
        """ Returns ( status, is_pending )
              current on/off status is taken from last mcp value without reading it from hardware
              is_pending is Boolean
        """
        return self.value

    async def set_state(self, value):
        """ Sets new on/off status. Disable pending timeouts
        """
        await self.arm.modbus_slave.client.write_coil(self.coil, 1 if value else 0, slave=self.arm.modbus_address)
        return 1 if value else 0

    async def set(self, value=None, alias=None):
        """ Sets new on/off status. Disable pending timeouts
        """
        if alias is not None:
            Devices.set_alias(alias, self)
        if value is not None:
            value = int(value)
            await self.arm.modbus_slave.client.write_coil(self.coil, 1 if value else 0, slave=self.arm.modbus_address)
        return self.full()

    def get(self):
        return self.full()


class Watchdog(object):
    def __init__(self, circuit, arm, post, reg, timeout_reg, nv_save_coil=-1, reset_coil=-1, wd_reset_ro_coil=-1,
                 major_group=0, legacy_mode=True):
        self.alias = ""
        self.devtype = WATCHDOG
        self.circuit = circuit
        self.arm = arm
        self.major_group = major_group
        self.legacy_mode = legacy_mode
        self.timeoutvalue = lambda: self.arm.modbus_slave.modbus_cache_map.get_register(1, self.toreg)
        self.regvalue = lambda: self.arm.modbus_slave.modbus_cache_map.get_register(1, self.valreg)[0]
        self.nvsavvalue = 0
        self.resetvalue = 0
        self.nv_save_coil = nv_save_coil
        self.reset_coil = reset_coil
        self.wd_reset_ro_coil = wd_reset_ro_coil
        self.wdwasresetvalue = 0
        self.valreg = reg
        self.toreg = timeout_reg

        self.value = None
        self.timeout = None
        self.was_wd_boot_value = None

    def full(self):
        ret = {'dev': 'wd',
               'circuit': self.circuit,
               'value': self.value,
               'timeout': self.timeout,
               'was_wd_reset': self.was_wd_boot_value,
               'nv_save' :self.nvsavvalue,
               }
        if self.alias != '':
            ret['alias'] = self.alias
        return ret

    def get(self):
        return self.full()

    def simple(self):
        return {'dev': 'wd',
                'circuit': self.circuit,
                'value': self.value}

    async def check_new_data(self):
        old_value = copy(self.value)
        self.value = self.regvalue() & 0x03  # Only the two lowest bits contains watchdog status
        self.timeout = self.timeoutvalue()[0] if self.timeoutvalue() else 0
        self.was_wd_boot_value = 1 if self.regvalue() & 0b10 else 0
        return old_value != self.value

    def get_state(self):
        """ Returns ( status, is_pending )
              current on/off status is taken from last mcp value without reading it from hardware
              is_pending is Boolean
        """
        return (self.value, self.timeout)

    async def set_state(self, value):
        """ Sets new on/off status. Disable pending timeouts
        """
        await self.arm.modbus_slave.client.write_register(self.valreg, 1 if value else 0, slave=self.arm.modbus_address)
        return 1 if value else 0

    async def set(self, value=None, timeout=None, reset=None, nv_save=None, alias=None):
        """ Sets new on/off status. Disable pending timeouts
        """
        if alias is not None:
            Devices.set_alias(alias, self)

        if value is not None:
            value = int(value)
            await self.arm.modbus_slave.client.write_register(self.valreg, 1 if value else 0,
                                                              slave=self.arm.modbus_address)

        if not (timeout is None):
            timeout = int(timeout)
            if timeout > 65535:
                timeout = 65535
            await self.arm.modbus_slave.client.write_register(self.toreg, timeout, slave=self.arm.modbus_address)

        if self.nv_save_coil >= 0 and nv_save is not None and nv_save != self.nvsavvalue:
            if nv_save != 0:
                self.nvsavvalue = 1
            else:
                self.nvsavvalue = 0
            await self.arm.modbus_slave.client.write_coil(self.nv_save_coil, 1, slave=self.arm.modbus_address)

        if self.reset_coil >= 0 and reset is not None:
            if reset != 0:
                self.nvsavvalue = 0
                await self.arm.modbus_slave.client.write_coil(self.reset_coil, 1, slave=self.arm.modbus_address)
                logger.info("Performed reset of board %s" % self.circuit)

        return self.full()


class DataPoint:

    def __init__(self, circuit, arm, reg, reg_type=None, major_group=0, datatype=None, unit=None, offset=0, factor=1, valid_mask_reg=None, valid_mask=None, name=None, post_write=None):
        # TODO - valid mask reg
        self.alias = ""
        self.devtype = DATA_POINT
        self.circuit = circuit
        self.arm = arm
        self.major_group = major_group
        self.valreg = reg
        self.offset = offset
        self.factor = factor
        self.unit = unit
        self.name = name
        self.post_write = post_write
        self.datatype = datatype
        self.valid_mask_reg = valid_mask_reg
        self.valid_mask = valid_mask
        self.is_input = reg_type == "input"
        self.is_valid = None
        self.value = None

    async def check_new_data(self):
        old_value = copy(self.value)
        old_valid_mask = copy(self.is_valid)
        self.value = self.read_value()
        self.is_valid = self.read_is_valid()
        return old_value != self.value or old_valid_mask != self.is_valid

    def read_is_valid(self):
        if self.valid_mask_reg is None:
            return 0
        try:
            val = self.arm.modbus_slave.modbus_cache_map.get_register(1, self.valid_mask_reg, is_input=self.is_input)[0]
            return bool(val & self.valid_mask)
        except ENoCacheRegister:
            return 0

    def read_value(self):
        try:
            if self.datatype is None or self.datatype == "signed16":
                value = self.arm.modbus_slave.modbus_cache_map.get_register(1, self.valreg, is_input=self.is_input)[0]
            elif self.datatype == "float32":
                value = self.__parse_float32(self.arm.modbus_slave.modbus_cache_map.get_register(2, self.valreg, is_input=self.is_input))
            else:
                logger.warning(f"Data point: Unsupported datatype {self.datatype}")
                return None
            if self.factor == 1 and self.offset == 0:  # Reading RAW value - save some CPU time
                return value
            else:
                return (value * self.factor) + self.offset
        except ENoCacheRegister:
            return None

    def __parse_float32(self, raw_regs):
        ret = float(BinaryPayloadDecoder.fromRegisters(raw_regs, Endian.BIG, Endian.BIG).decode_32bit_float())
        return ret if not math.isnan(ret) else 'NaN'

    async def set(self, value=None, alias=None, **kwargs):
        """ Sets new on/off status. Disable pending timeouts """
        if alias is not None:
            Devices.set_alias(alias, self)

        raise Exception("Data point object is read-only")

    def full(self):

        ret = {'dev': 'data_point',
               'circuit': self.circuit,
               'value': self.value,
               }

        if self.name is not None:
            ret['name'] = self.name

        if self.valid_mask_reg is not None:
            ret['valid'] = self.is_valid

        if self.unit is not None:
            ret['unit'] = self.unit

        if self.alias != '':
            ret['alias'] = self.alias
        return ret

    def simple(self):
        return {'dev': 'data_point',
                'circuit': self.circuit,
                'value': self.read_value()}

    def get(self):
        return self.full()

    def get_state(self):
        """ Returns ( status, is_pending )
              current on/off status is taken from last mcp value without reading it from hardware
              is_pending is Boolean
        """
        return self.value


class Register:
    def __init__(self, circuit, arm, post, reg, reg_type="holding", major_group=0, legacy_mode=True):
        self.alias = ""
        self.devtype = REGISTER
        self.circuit = circuit
        self.arm = arm
        self.major_group = major_group
        self.legacy_mode = legacy_mode
        self.valreg = reg
        self.reg_type = reg_type

    def regvalue(self):
        try:
            if self.reg_type == "input":
                return self.arm.modbus_slave.modbus_cache_map.get_register(1, self.valreg, is_input=True)[0]
            else:
                return self.arm.modbus_slave.modbus_cache_map.get_register(1, self.valreg, is_input=False)[0]
        except ENoCacheRegister:
            return None

    def full(self):
        ret = {'dev': 'register',
               'circuit': self.circuit,
               'value': self.regvalue(),
               }
        if self.alias != '':
            ret['alias'] = self.alias
        return ret

    def simple(self):
        return {'dev': 'register',
                'circuit': self.circuit,
                'value': self.regvalue()}

    @property
    def value(self):
        try:
            if self.regvalue():
                return self.regvalue()
        except:
            pass
        return 0


    def get(self):
        return self.full()

    def get_state(self):
        """ Returns ( status, is_pending )
              current on/off status is taken from last mcp value without reading it from hardware
              is_pending is Boolean
        """
        return (self.value)

    async def set_state(self, value):
        """ Sets new on/off status. Disable pending timeouts
        """
        await self.arm.modbus_slave.client.write_register(self.valreg, value if value else 0, slave=self.arm.modbus_address)
        return value if value else 0

    async def set(self, value=None, alias=None):
        """ Sets new on/off status. Disable pending timeouts
        """
        if alias is not None:
            Devices.set_alias(alias, self)
        if value is not None:
            value = int(value)
            await self.arm.modbus_slave.client.write_register(self.valreg, value if value else 0, slave=self.arm.modbus_address)

        return self.full()


class DigitalInput:
    def __init__(self, circuit, arm, reg, mask, regcounter=None, regdebounce=None, regmode=None, regtoggle=None, regpolarity=None,
                 major_group=0, modes=['Simple'], ds_modes=['Simple'], counter_modes=['Enabled', 'Disabled'], legacy_mode=True):
        self.alias = ""
        self.devtype = DI
        self.circuit = circuit
        self.arm = arm
        self.modes = modes
        self.ds_modes = ds_modes
        self.counter_modes = counter_modes
        self.major_group = major_group
        self.legacy_mode = legacy_mode
        self.bitmask = mask
        self.regcounter = regcounter
        self.regdebounce = regdebounce
        self.regmode = regmode
        self.regtoggle = regtoggle
        self.regpolarity = regpolarity
        self.reg = reg
        self.regvalue = lambda: self.arm.modbus_slave.modbus_cache_map.get_register(1, self.reg)[0]
        self.regcountervalue = self.regdebouncevalue = lambda: None
        if not (regcounter is None): self.regcountervalue = lambda: self.arm.modbus_slave.modbus_cache_map.get_register(1, regcounter)[0] + (self.arm.modbus_slave.modbus_cache_map.get_register(1, regcounter + 1)[0] << 16)
        if not (regdebounce is None): self.regdebouncevalue = lambda: self.arm.modbus_slave.modbus_cache_map.get_register(1, regdebounce)[0]
        self.mode = 'Simple'
        self.ds_mode = 'Simple'
        self.counter_mode = "Enabled"
        self.value = None
        self.counter = None
        self.debounce = None

    async def check_new_data(self):
        if 'DirectSwitch' in self.modes:
            curr_ds = self.arm.modbus_slave.modbus_cache_map.get_register(1, self.regmode)[0]
            if (curr_ds & self.bitmask) > 0:
                self.mode = 'DirectSwitch'
                curr_ds_pol = self.arm.modbus_slave.modbus_cache_map.get_register(1, self.regpolarity)[0]
                curr_ds_tgl = self.arm.modbus_slave.modbus_cache_map.get_register(1, self.regtoggle)[0]
                if curr_ds_pol & self.bitmask:
                    self.ds_mode = 'Inverted'
                elif curr_ds_tgl & self.bitmask:
                    self.ds_mode = 'Toggle'
            else:
                self.mode = "Simple"

        old_value = copy(self.value)
        old_counter = copy(self.counter)
        self.value = 1 if (self.regvalue() & self.bitmask) else 0
        self.counter = self.regcountervalue()
        self.debounce = self.regdebouncevalue()
        return old_counter != self.counter or old_value != self.value

    def full(self):
        ret = {'dev': 'di',
               'circuit': self.circuit,
               'value': self.value,
               'debounce': self.debounce,
               'counter_modes': self.counter_modes,
               'counter_mode': self.counter_mode,
               'counter': self.counter if self.counter_mode == 'Enabled' else 0,
               'mode': self.mode,
               'modes': self.modes,
               }
        if self.mode == 'DirectSwitch':
            ret['ds_mode'] = self.ds_mode
            ret['ds_modes'] = self.ds_modes
        if self.alias != '':
            ret['alias'] = self.alias
        return ret

    def simple(self):
        if self.counter_mode == 'Enabled':
            return {'dev': 'di',
                    'circuit': self.circuit,
                    'value': self.value,
                    'counter': self.counter}
        else:
            return {'dev': 'di',
                    'circuit': self.circuit,
                    'value': self.value}

    async def set(self, debounce=None, mode=None, counter=None, counter_mode=None, ds_mode=None, alias=None):
        if alias is not None:
            Devices.set_alias(alias, self)

        if mode is not None and mode != self.mode and mode in self.modes:
            self.mode = mode
            if self.mode == 'DirectSwitch':
                curr_ds = await self.arm.modbus_slave.modbus_cache_map.get_register_async(1, self.regmode, slave=self.arm.modbus_address)
                curr_ds_val = curr_ds[0]
                curr_ds_val = curr_ds_val | int(self.bitmask)
                await self.arm.modbus_slave.client.write_register(self.regmode, curr_ds_val, slave=self.arm.modbus_address)
            else:
                curr_ds = await self.arm.modbus_slave.modbus_cache_map.get_register_async(1, self.regmode, slave=self.arm.modbus_address)
                curr_ds_val = curr_ds[0]
                curr_ds_val = curr_ds_val & (~int(self.bitmask))
                await self.arm.modbus_slave.client.write_register(self.regmode, curr_ds_val, slave=self.arm.modbus_address)

        if self.mode == 'DirectSwitch' and ds_mode is not None and ds_mode in self.ds_modes:
            self.ds_mode = ds_mode
            curr_ds_pol = await self.arm.modbus_slave.modbus_cache_map.get_register_async(1, self.regpolarity, slave=self.arm.modbus_address)
            curr_ds_tgl = await self.arm.modbus_slave.modbus_cache_map.get_register_async(1, self.regtoggle, slave=self.arm.modbus_address)
            curr_ds_pol_val = curr_ds_pol[0]
            curr_ds_tgl_val = curr_ds_tgl[0]
            if self.ds_mode == 'Inverted':
                curr_ds_pol_val = curr_ds_pol_val | self.bitmask
                curr_ds_tgl_val = curr_ds_tgl_val & (~self.bitmask)
            elif self.ds_mode == 'Toggle':
                curr_ds_pol_val = curr_ds_pol_val & (~self.bitmask)
                curr_ds_tgl_val = curr_ds_tgl_val | self.bitmask
            else:
                curr_ds_pol_val = curr_ds_pol_val & (~self.bitmask)
                curr_ds_tgl_val = curr_ds_tgl_val & (~self.bitmask)
            await self.arm.modbus_slave.client.write_register(self.regpolarity, curr_ds_pol_val, slave=self.arm.modbus_address)
            await self.arm.modbus_slave.client.write_register(self.regtoggle, curr_ds_tgl_val, slave=self.arm.modbus_address)

        if counter_mode is not None and counter_mode in self.counter_modes and counter_mode != self.counter_mode:
            self.counter_mode = counter_mode

        if debounce is not None:
            if self.regdebounce is not None:
                await self.arm.modbus_slave.client.write_register(self.regdebounce, int(float(debounce)), slave=self.arm.modbus_address)
        if counter is not None:
            if self.regcounter is not None:
                await self.arm.modbus_slave.client.write_registers(self.regcounter, ((int(float(counter)) & 0xFFFF), (int(float(counter)) >> 16) & 0xFFFF), slave=self.arm.modbus_address)
        return self.full()

    def get(self):
        """ Returns ( value, debounce )
              current on/off value is taken from last value without reading it from hardware
        """
        return self.value, self.debounce

    def get_value(self):
        """ Returns value
              current on/off value is taken from last value without reading it from hardware
        """
        return self.value


class AnalogOutputBrain:
    def __init__(self, circuit, arm, reg, regmode=None, reg_res=0, major_group=0):
        self.alias = ""
        self.devtype = AO
        self.circuit = circuit
        self.reg = reg
        self.regmode = regmode
        self.reg_res = reg_res
        self.modes = {
            'Voltage': {
                'value': 0,
                'unit': 'V',
                'range': [0, 10]
            },
            'Current': {
                'value': 1,
                'unit': 'mA',
                'range': [0, 20]
            },
            'Resistance':{
                'value': 2,
                'unit': 'Ohm',
                'range': [0, 2000]
            }
        }
        self.arm = arm
        self.major_group = major_group
        self.is_voltage = lambda: bool(self.arm.modbus_slave.modbus_cache_map.get_register(1, self.regmode)[0] == 0)
        self.value = None
        self.res_value = None
        self.mode = None
        self.unit = None

    async def check_new_data(self):
        if self.is_voltage():
            self.mode = 'Voltage'
        elif self.arm.modbus_slave.modbus_cache_map.get_register(1, self.regmode)[0] == 1:
            self.mode = 'Current'
        else:
            self.mode = 'Resistance'
        self.unit = self.modes[self.mode]['unit']

        old_value = copy(self.value)
        old_res_value = copy(self.res_value)
        self.value = self.regvalue()
        self.res_value = self.regres_value()
        return self.value != old_value or self.res_value != old_res_value

    def regvalue(self):
        try:
            ret = self.arm.modbus_slave.modbus_cache_map.get_register(2, self.reg)
            ret = BinaryPayloadDecoder.fromRegisters(ret, Endian.BIG, Endian.LITTLE).decode_32bit_float()
            return round(float(ret), 3)
        except:
            return 0

    def regres_value(self):
        try:
            ret = self.arm.modbus_slave.modbus_cache_map.get_register(2, self.reg_res)
            ret = BinaryPayloadDecoder.fromRegisters(ret, Endian.BIG, Endian.LITTLE).decode_32bit_float()
            return round(float(ret), 3)
        except:
            return 0

    def full(self):
        ret = {'dev': 'ao',
               'circuit': self.circuit,
               'mode': self.mode,
               'modes': self.modes,
               'unit': self.unit
        }

        if self.mode == 'Resistance':
            ret['value'] = self.res_value
        else:
            ret['value'] = self.value
        if self.alias != '':
            ret['alias'] = self.alias
        return ret

    def simple(self):
        if self.mode == 'Resistance':
            return {'dev': 'ao',
                    'circuit': self.circuit,
                    'value': self.res_value}
        else:
            return {'dev': 'ao',
                    'circuit': self.circuit,
                    'value': self.value}

    async def set_value(self, value):
        if value < 0:
            value = 0
        # TODO: omezenit horni hodnoty!!!

        builder = BinaryPayloadBuilder(byteorder=Endian.BIG, wordorder=Endian.LITTLE)
        builder.add_32bit_float(float(value))
        value_set = builder.to_registers()

        await self.arm.modbus_slave.client.write_registers(self.reg, values=value_set, slave=self.arm.modbus_address)
        return value

    async def set(self, value=None, mode=None, alias=None):
        if alias is not None:
            Devices.set_alias(alias, self)

        if mode is not None and mode in self.modes and self.regmode is not None:
            val = self.arm.modbus_slave.modbus_cache_map.get_register(1, self.regmode)[0]
            cur_val = self.value
            if mode == "Voltage":
                val = 0
            elif mode == "Current":
                val = 1
            elif mode == "Resistance":
                val = 3
            self.mode = mode
            await self.arm.modbus_slave.client.write_register(self.regmode, val, slave=self.arm.modbus_address)
            if mode == "Voltage" or mode == "Current":
                await self.set_value(cur_val)        # Restore original value (i.e. 1.5V becomes 1.5mA)
        if not (value is None):
            await self.set_value(float(value))  # Restore original value (i.e. 1.5V becomes 1.5mA)
        return self.full()

    def get(self):
        return self.full()


class AnalogOutput:
    def __init__(self, circuit, arm, reg, regmode=None, modes=None, major_group=0):
        self.alias = ""
        self.devtype = AO
        self.circuit = circuit
        self.reg = reg
        self.regvalue = lambda: self.arm.modbus_slave.modbus_cache_map.get_register(1, self.reg)[0]
        self.regmode = regmode
        self.modes = modes if modes is not None else {}
        self.arm = arm
        self.major_group = major_group
        self.offset = 0
        self.value = None
        self.res_value = None
        self.mode = list(modes.keys())[0] if len(modes) == 1 and self.regmode is None else None

    def get_mode_by_regvalue(self, regvalue: int):
        for mode, data in self.modes.items():
            if regvalue == data['value']:
                return mode
        return None

    @property
    def unit_name(self):
        if self.mode in self.modes:
            return self.modes[self.mode].get('unit', None)
        else:
            return None

    @property
    def range(self):
        if self.mode in self.modes:
            return self.modes[self.mode].get('range', None)
        else:
            return None

    async def check_new_data(self):
        if self.regmode is not None:
            mode_value = self.arm.modbus_slave.modbus_cache_map.get_register(1, self.regmode)[0]
            self.mode = self.get_mode_by_regvalue(mode_value)

        old_value = copy(self.value)
        old_res_value = copy(self.res_value)
        self.value = round(self.regvalue() * 0.0025, 3)
        self.res_value = round(float(self.regvalue()) * 0.0025, 3)
        return self.value != old_value or self.res_value != old_res_value

    def full(self):
        ret = {'dev': 'ao',
               'circuit': self.circuit,
               'mode': self.mode,
               'modes': self.modes,
               'value': self.value,
               'unit': self.unit_name,
               'range': self.range,
               }
        if self.alias != '':
            ret['alias'] = self.alias
        return ret

    def simple(self):
        return {'dev': 'ao',
                'circuit': self.circuit,
                'value': self.value}

    async def set_value(self, value):
        valuei = int((float(value) / 0.0025))
        if valuei < 0:
            valuei = 0
        elif valuei > 4095:
            valuei = 4095
        await self.arm.modbus_slave.client.write_register(self.reg, valuei, slave=self.arm.modbus_address)
        return float(valuei) * 0.0025

    async def set(self, value=None, mode=None, alias=None):
        if alias is not None:
            Devices.set_alias(alias, self)

        if mode is not None and mode in self.modes and self.regmode is not None:
            mdata = self.modes[mode]
            if 'value' not in mdata:
                raise ValueError(f"AnalogOutput: this device cant switch mode!")
            mvalue = int(mdata['value'])
            await self.arm.modbus_slave.client.write_register(self.regmode, mvalue, slave=self.arm.modbus_address)

        if not (value is None):
            await self.set_value(value)
        return self.full()

    def get(self):
        return self.full()


class AnalogInput:

    endian_map={"little" : Endian.LITTLE,
                "Little" : Endian.LITTLE,
                "big" : Endian.BIG,
                "Big" : Endian.BIG,}

    def __init__(self, circuit, arm, reg, regmode=None, major_group=0, legacy_mode=True, modes=None):
        self.alias = ""
        self.devtype = AI
        self.circuit = circuit
        self.valreg = reg
        self.arm = arm
        self.legacy_mode = legacy_mode
        self.regmode = regmode
        self.modes = modes if modes is not None else {}
        self.mode = list(modes.keys())[0] if len(modes) == 1 and self.regmode is None else None
        self.mode_value = None
        self.major_group = major_group
        self.is_voltage = lambda: True
        self.value = None
        self.transformation = lambda registers: round(BinaryPayloadDecoder.fromRegisters(registers, Endian.BIG,
                                                                                   Endian.LITTLE).decode_32bit_float(),3)

        #logger.debug(f"AnalogInput.__init__ called, instance content {vars(self)}")

    def get_mode_by_regvalue(self, regvalue: int):
        for mode, data in self.modes.items():
            if regvalue == data['value']:
                return mode
        return None

    def reload_mode(self, mode_value: int):
        for mode, data in self.modes.items():
            if mode_value == data['value']:
                if data.get("transformation"):
                    #logger.debug(f"Mode: {data['value']} -> {data['transformation']}")
                    byteorder = AnalogInput.endian_map[data["transformation"].get("byteorder", "big")]
                    wordorder = AnalogInput.endian_map[data["transformation"].get("wordorder", "little")]
                    datatype = data["transformation"].get("datatype", "float32")
                    decimals = data["transformation"].get("decimals", 3)
                    ratio = data["transformation"].get("ratio", 1)
                    logger.debug(f"Aplying transformation on analog input {self.circuit}: {datatype} {byteorder} {wordorder} {decimals}")
                    if datatype == "float32":
                        self.transformation = lambda registers : round(BinaryPayloadDecoder.fromRegisters(registers,
                                                                                                      byteorder=byteorder,
                                                                                                      wordorder=wordorder).decode_32bit_float() * ratio,decimals)
                    elif datatype == "int32":
                        self.transformation = lambda registers: int(BinaryPayloadDecoder.fromRegisters(registers,
                                                                                                         byteorder=byteorder,
                                                                                                         wordorder=wordorder).decode_32bit_int() * ratio)
                    elif datatype == "uint32" and (ratio, float) :
                        self.transformation = lambda registers: round(float(BinaryPayloadDecoder.fromRegisters(registers,
                                                                                                       byteorder=byteorder,
                                                                                                       wordorder=wordorder).decode_32bit_uint() * ratio),decimals)
                    elif datatype == "uint32":
                        self.transformation = lambda registers: int(BinaryPayloadDecoder.fromRegisters(registers,
                                                                                                       byteorder=byteorder,
                                                                                                       wordorder=wordorder).decode_32bit_uint() * ratio)
                return mode
        return None

    @property
    def unit_name(self):
        if self.mode in self.modes:
            return self.modes[self.mode].get('unit', None)
        else:
            return None

    @property
    def range(self):
        if self.mode in self.modes:
            return self.modes[self.mode].get('range', None)
        else:
            return None

    async def check_new_data(self):
        has_changed = False
        if self.regmode is not None:
            old_mode_value = copy(self.mode_value)
            self.mode_value = self.arm.modbus_slave.modbus_cache_map.get_register(1, self.regmode)[0]
            if old_mode_value != self.mode_value:
                self.mode = self.reload_mode(self.mode_value)
                has_changed = True

        old_value = copy(self.value)
        self.value = self.regvalue()
        return self.value != old_value or has_changed

    def regvalue(self):
        try:
            # TODO adaptive data length
            ret = self.arm.modbus_slave.modbus_cache_map.get_register(2, self.valreg)
            return self.transformation(ret)
        except ENoCacheRegister:
            return None

    async def set(self, mode=None, alias=None):
        if alias is not None:
            Devices.set_alias(alias, self)

        if mode is not None and mode in self.modes:
            mdata = self.modes[mode]
            if 'value' not in mdata:
                raise ValueError(f"AnalogInput: this device cant switch mode!")
            mvalue = int(mdata['value'])
            await self.arm.modbus_slave.client.write_register(self.regmode, mvalue, slave=self.arm.modbus_address)
        return self.full()

    def full(self):
        ret = {'dev': 'ai',
               'circuit': self.circuit,
               'value': self.value,
               'unit': self.unit_name,
               'mode': self.mode,
               'modes': self.modes,
               'range': self.range,
               }
        if self.alias != '':
            ret['alias'] = self.alias
        return ret

    def get(self):
        return self.full()

    def simple(self):
        return {'dev': 'ai',
                'circuit': self.circuit,
                'value': self.value}

    @property
    def voltage(self):
        return self.value


import asyncio
import time
from typing import Any, Callable, Type, Tuple

from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
from pymodbus.exceptions import ConnectionException, ModbusIOException
from pymodbus.pdu import ExceptionResponse
from pymodbus.framer import ModbusRtuFramer, ModbusFramer, ModbusSocketFramer

#---------------------------------------------------------------------------#
# Logging
#---------------------------------------------------------------------------#
from .log import *


class ModbusException(Exception):
    pass

exception_classes = [ExceptionResponse, ModbusIOException]


class EvokModbusSerialClient(AsyncModbusSerialClient):
    def __init__(self, port: str, framer: Type[ModbusFramer] = ModbusRtuFramer, baudrate: int = 19200,
                 bytesize: int = 8, parity: str = "N", stopbits: int = 1, timeout: float = 1, **kwargs: Any) -> None:
        super().__init__(port, framer, baudrate, bytesize, parity, stopbits, retries=0, **kwargs)
        for method_name in ['read_holding_registers', 'read_input_registers', 'write_register', 'write_registers',
                            'write_coil', 'connect']:
            setattr(self, method_name, self.__block(getattr(self, method_name)))
        self.port = port
        self.lock = asyncio.Lock()
        self.stime = time.time()
        self.block_count = 0
        self.__timeout = timeout

    def __runtime(self):
        return int((time.time()-self.stime)*1000)

    def __block(self, operation: Callable):
        async def ret(*args, **kwargs):
            async with self.lock:
                try:
                    aret = await operation(*args, **kwargs)
                    if type(aret) in exception_classes:
                        raise ModbusException(f"{type(aret)}: {aret}")
                    return aret
                except ConnectionException:
                    await asyncio.sleep(self.reconnect_delay_current)
                    while not self.connected:
                        await asyncio.sleep(0.001)  # TODO
        return ret


class EvokModbusTcpClient(AsyncModbusTcpClient):
    def __init__(self, host: str, port: int = 502, framer: Type[ModbusFramer] = ModbusSocketFramer,
                 source_address: Tuple[str, int] = None, timeout: float = 1, **kwargs: Any) -> None:
        super().__init__(host, port, framer, source_address, retries=0, **kwargs)
        for method_name in ['read_holding_registers', 'read_input_registers', 'write_register', 'write_registers',
                            'write_coil']:
            setattr(self, method_name, self.__block(getattr(self, method_name)))
        self.host = host
        self.lock = asyncio.Lock()
        self.stime = time.time()
        self.block_count = 0
        self.__timeout = timeout

    def __block(self, operation: Callable):
        async def ret(*args, **kwargs):
            start_stamp = time.time()
            while not self.connected and time.time() - start_stamp < self.__timeout:
                await asyncio.sleep(0.001)
            aret = await operation(*args, **kwargs)
            if type(aret) in exception_classes:
                raise ModbusException(f"{type(aret)}: {aret}")
            return aret
        return ret

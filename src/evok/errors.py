class ModbusSlaveError(Exception):
    pass

class ENoCacheRegister(ModbusSlaveError):
    pass


class DeviceNotFound(Exception):
    pass


class ModbusSlaveError(Exception):
    pass


class DeviceNotFound(Exception):
    pass


class UnitUnavailable(Exception):
    """ The Modbus unit failed its last scan, its devices are not changed """
    pass

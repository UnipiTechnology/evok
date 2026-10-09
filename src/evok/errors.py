class ModbusSlaveError(Exception):
    pass


class DeviceNotFound(Exception):
    pass


class UnitUnavailable(Exception):
    """ The Modbus unit failed its last scan, its devices are not changed """
    pass


class UnitCommunicationError(UnitUnavailable):
    """ A request of a change of the Modbus unit failed, the writes before it are done;
        reported as UnitUnavailable, it is not an error of the request nor of Evok
    """
    pass

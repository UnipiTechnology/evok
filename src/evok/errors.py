class ModbusSlaveError(Exception):
    pass


class DeviceNotFound(Exception):
    pass


class UnitUnavailable(Exception):
    """ The Modbus unit failed its last scan, its devices are not changed """
    pass


class ReadOnlyAccess(Exception):
    """ The request with the read_token of the configuration would change a device, HTTP 403 """
    pass


class UnitCommunicationError(UnitUnavailable):
    """ A request of a change of the Modbus unit failed, the writes before it are done;
        reported as UnitUnavailable, it is not an error of the request nor of Evok
    """
    pass


def error_chain(error: BaseException | None) -> list[BaseException]:
    """ The error and its causes, a tenacity.RetryError has the error of its last attempt, not a cause """
    chain = []
    while error is not None and len(chain) < 10:
        chain.append(error)
        last_attempt = getattr(error, 'last_attempt', None)
        error = last_attempt.exception() if last_attempt is not None else error.__cause__
    return chain


def root_cause(error: BaseException) -> BaseException:
    """ The innermost cause of the error, e.g. FileNotFoundError of a missing serial port under the errors
        of the retries of tmodbus; a CancelledError of asyncio.wait_for() is not a cause
    """
    causes = [cause for cause in error_chain(error) if isinstance(cause, Exception)]
    return causes[-1] if causes else error


def describe_error(error: BaseException) -> str:
    """ 'Type: text' of the error with its root cause, if the text does not say it """
    text = f"{type(error).__name__}: {error}"
    cause = root_cause(error)
    if cause is not error and str(cause) and str(cause) not in text:
        text += f" ({type(cause).__name__}: {cause})"
    return text

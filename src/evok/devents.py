import logging

logger = logging.getLogger(__name__)


def _status(device, **kwarg):
    # print device.full()
    pass


def _config(device, **kwarg):
    # print device.full()
    pass


# function variables holding current callbacks


status = _status
config = _config


def register_status_cb(callback):
    global status
    if callback:

        def newstatus(device, **kwarg):
            try:
                callback(device, kwarg)
            except Exception:
                # an error of a client must not stop the change of the device which sent the event
                logger.exception("Error in the status callback")

        status = newstatus
    else:
        status = _status


def register_config_cb(callback):
    global config
    if callback:

        def newconfig(device, **kwarg):
            try:
                callback(device, kwarg)
            except Exception:
                # an error of a client must not stop the change of the device which sent the event
                logger.exception("Error in the config callback")

        config = newconfig
    else:
        config = _config

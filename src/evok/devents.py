#!/usr/bin/python


def _status(device, **kwarg):
    #print device.full()
    pass


def _config(device, **kwarg):
    #print device.full()
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
            except:
                pass

        status = newstatus
    else:
        status = _status


def register_config_cb(callback):
    global config
    if callback:
        def newconfig(device, **kwarg):
            try:
                callback(device, kwarg)
            except:
                pass

        config = newconfig
    else:
        config = _config


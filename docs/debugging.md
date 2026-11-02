# Debugging

Debugging allows you to see what is done internally in Evok, in case you face any troubles.

## Single start in debug mode

If you wish to debug a single event and then run Evok in normal mode, you can launch Evok in debug mode.
You need to stop the running Evok service first.

```bash title="Stopping Evok service"
sudo systemctl stop evok
```

Now, you can manually run Evok in debug mode, the output will be printed to the terminal.

```bash title="Running Evok manually"
/opt/evok/bin/evok -d
```

The debug messages of the Modbus library `tmodbus` are logged only with `-dd`: the raw Modbus traffic (every sent
and received frame) and the traceback of every failed attempt to connect a unit. They add many lines to every scan:

```bash title="Running Evok manually with the debug messages of tmodbus"
/opt/evok/bin/evok -dd
```

With `-d` (as with the `DEBUG` level of the configuration) the other libraries log their debug messages too,
e.g. `tornado.access` a line for every request of the API; `tmodbus` logs its messages from `INFO` up.

Evok started manually uses the configuration in `/etc/evok` and the aliases in `/var/lib/evok/alias.yaml`, other ones
are set by `-c` / `--config-dir` and `-a` / `--alias-file` or by the variables `EVOK_CONFIG_DIR` and `EVOK_ALIAS_FILE`,
see [Configuration](configs/evok_configuration.md).

## Setting permanent debug mode

If you need to debug an issue that occurs rarely, you can set Evok to run in debug mode permanently.
You have to change `logging: level:` to `DEBUG` in `/etc/evok/config.yaml`.
Use text editor of your choice, we recommend using `nano` (do `sudo apt install nano` if not present on your system).

```bash title="Editing configuration file"
sudo nano /etc/evok/config.yaml
```

Find this section:

```yaml
#   +------------------+
#   | Logging settings |
#   +------------------+
logging:
  level: INFO
  # ^ Minimum severity of messages to be logged, where minimum is CRITICAL.
  # ^ Options: [CRITICAL, ERROR, WARNING, INFO, DEBUG]
```

And change the `level` value to `DEBUG`:

```yaml
#   +------------------+
#   | Logging settings |
#   +------------------+
logging:
  level: DEBUG
  # ^ Minimum severity of messages to be logged, where minimum is CRITICAL.
  # ^ Options: [CRITICAL, ERROR, WARNING, INFO, DEBUG]
```

The debug messages of `tmodbus` are not logged with the `DEBUG` level of the configuration, only with `-dd`.

Now, save via `CTRL+X`, then press `ENTER` and exit by `CTRL+X`.
The Evok service has to be restarted now.

```bash title="Restarting Evok service"
sudo systemctl restart evok
```

### Reading the logs

To read the logs from Evok in permanent debug mode, you can use following command. It also prints information about other related services.

```bash title="Viewing the Evok log"
journalctl -e -u evok
```

You can scroll in the outuput via arrow keys.
If you wish to copy the output (no scrolling), use following command:

```bash title="Copying the Evok log"
journalctl --no-pager -u evok -u unipi-one-modbus
```

This is more practical, as it's almost impossible to copy larger section of the log, when you have to scroll trough it.

With `file` in the [logging](configs/evok_configuration.md#logging) settings Evok also writes the log to a file
(rotated daily, 7 old files kept), its end is returned by the API: `GET /log?lines=N` (255 lines by default, at most 1000).

### Loggers of the modules

Each module of Evok logs by its own logger, e.g. `evok.modbus.client`, `evok.modbus.scanner` or `evok.w1.bus`,
the name is in each line of the log. They are children of the logger `evok`, which has the level
of the configuration and the file handler. The configuration sets one level for all of them, the level of one part
of Evok can be set by Python logging, e.g. `logging.getLogger('evok.w1').setLevel(logging.DEBUG)`.

!!! success

    You can examine or copy the output.

## Determining the version of Evok

You can obtain the version of Evok by executing following command:

```bash
/opt/evok/bin/evok -v
```

```bash title="Output"
v3.1.0
```

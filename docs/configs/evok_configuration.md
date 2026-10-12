# Evok configuration

Evok configuration is located in `/etc/evok/config.yaml`. The default configuration is installed by the debian package. To apply the configuration, it is necessary to restart Evok with the command `systemctl restart evok`.

The configuration directory (with `config.yaml`, `hw_definitions/` and optional `autogen.yaml`) can be changed with the command line option `--config-dir` or the environment variable `EVOK_CONFIG_DIR`, the aliases file with `--alias-file` or `EVOK_ALIAS_FILE`. Evok exits with an error if `config.yaml` is not found.

```
evok --config-dir ./my-config --alias-file ./alias.yaml
```

## API settings

In this section you can configure address and port for API listening. These settings will be applied to protocols [REST](../apis/rest.md), [JSON](../apis/json.md), [BULK](../apis/bulk.md), [RPC](../apis/rpc.md), [Webhook](../apis/webhook.md), [WebSocket](../apis/websocket.md). The [MQTT](../apis/mqtt.md) API connects to a broker, see its section.

- `port` - port for API listening, needs to be changed in `etc/nginx/sites-available/evok` too
- `address` - address of the interface for API listening, `127.0.0.1` if the parameter is missing,
  set it to an empty value to listen on all interfaces
- `token` - an optional token required by all APIs except `/version`, a long random string,
  e.g. made by `openssl rand -hex 32`. Without it the APIs are not authenticated, use it with an address
  of the network. See [Security](../security.md) for how the clients send it.
- `read_token` - an optional second token which allows only reading, it requires `token` and must differ from it.
  A change of a device with it is refused with the status `403`.
- `allowed_origins` - an optional list of the origins of the web applications on other addresses
  which use the API from a browser, e.g. `["http://192.168.1.10:1880"]`. Only they get the CORS headers
  and can connect to the WebSocket from a browser, a web page of the same address as the API needs no entry.
  Evok does not start with an invalid `token` or `allowed_origins`.

### RPC

- `enabled` - enables [RPC](../apis/rpc.md) API (`true` / `false`), enabled if the section is missing

### Websocket

- `enabled` - enables websocket API (`true` / `false`)
- `all_filtered` - all WebSocket requests will be subject to the filtering set by 'filter' (`true` / `false`)

### Webhook

- `enabled` - enables webhook notifications (`true` / `false`)
- `address` - address (with port) to which notifications should be sent
- `device_mask` - list of devices to notify on (written as a JSON list, same format as `address`)
- `complex_events` - Evok will send POST requests with the same data as WebSocket, rather than an empty GET request
- `min_interval` - minimum time between two requests in seconds (default `1.0`). The changes in the meantime are merged
  into one request with the last state of each device, only one request is sent at a time

### MQTT

The [MQTT](../apis/mqtt.md) API, a client of a broker. Evok does not start with an invalid option.

- `enabled` - enables the MQTT API (`true` / `false`, default `false`)
- `hostname` - hostname of the broker (default `127.0.0.1`)
- `port` - port of the broker (default `1883`, `8883` with TLS)
- `username`, `password` - an optional user of the broker
- `tls` - connects by TLS with the certificates of the system (`true` / `false`, default `false`)
- `ca_file` - an optional file of the certificate authority of the broker, it enables TLS
- `cert_file`, `key_file` - an optional certificate and key of the client, they enable TLS
- `client_id` - client identifier (default `evok-<hostname of the unit>`), it must be unique on the broker
- `prefix` - the first part of the topics (default `evok`), e.g. `evok/boiler-room` for more units on one broker
- `qos` - QoS of the published states and the commands (`0`, `1`, `2`, default `0`)
- `keepalive` - keepalive interval in seconds (default `60`), a lost connection is detected after 1.5 times it
- `device_mask` - list of the published device types (default all), e.g. `["di", "ro", "sensor"]`
- `read_only` - Evok does not receive the commands (`true` / `false`, default `false`)
- `ha_discovery` - announces the devices to Home Assistant by the MQTT discovery (`true` / `false`, default `false`),
  see [Home Assistant](../apis/mqtt.md#home-assistant)
- `ha_prefix` - the discovery prefix of Home Assistant (default `homeassistant`)

```yaml title="MQTT"
apis:
  mqtt:
    enabled: true
    hostname: 192.168.1.10
    username: evok
    password: secret
    prefix: evok/boiler-room
```

## Hardware configuration

The hardware configuration is represented by a device tree with this structure:

```yaml
comm_channels:
    <bus_name>:
        type: <bus_type>
        <bus specific settings>: <specific parameters>
        devices:
            <device_name>:
                slave-id: <slave_id>
                model: <model>
                scan_frequency: <scan_frequency>
```

### Bus configuration

- *<bus_name\>* - Your choice, but has to be unique
- `enabled` - an optional parameter, the bus is skipped if it is `false` (Default value is `true`)
- `device_info` - an optional parameter, describes the controller: `family`, `model`, `sn`, `board_count`
- `type` options:
    - `MODBUSTCP`
        - `hostname` - hostname of the Modbus server (Default value is `127.0.0.1`)
        - `port` - port of the Modbus server (Default value is `502`)
        - `timeout` - timeout of a response in seconds (Default value is `0.5`)
        - `connect_timeout` - timeout of connecting to the Modbus server in seconds (Default value is `1.0`)
        - `retries` - count of retries of a request after a lost connection or a busy unit, an integer `>= 0`
          (Default value is `1`). The bus waits for the retries, a unit which does not respond
          is scanned less often by Evok.
        - `probe_timeout` - timeout in seconds of a request to a unit which does not respond, it is sent once
          without the retries (Default value is `timeout`)
    - `MODBUSRTU`
        - `port` - path to the Modbus device, required. Only one bus can use a serial port (also by a symlink),
          the second bus is not created and the error is logged.
        - `baudrate` - baudrate of the Modbus device (Default value is `19200`)
        - `parity` - parity of the Modbus device (`N` / `E` / `O`, Default value is `N`)
        - `stopbits` - stop bits of the Modbus device (Default value is `1`)
        - `timeout` - timeout of a response in seconds (Default value is `0.5`)
        - `retries` - count of retries of a request after a failure of the port or a busy unit, an integer `>= 0`
          (Default value is `1`)
        - `probe_timeout` - timeout in seconds of a request to a unit which does not respond, it is sent once
          without the retries (Default value is `0.1`, at most `timeout`). The other units of the bus wait
          for it, before a missing unit locked the bus for `(retries + 1) * timeout` at every attempt.
          A longer value is needed if the response of the first register block takes longer at the baud rate,
          e.g. 125 registers take about 0.15 s at 19200 Bd.
    - `OWFS` (1-Wire bus, the former name `OWBUS` is not supported)
      The bus reads the sensors by the 1-Wire subsystem of the kernel (`/sys/bus/w1/devices`), owserver is not used.
      The 1-Wire master, e.g. the DS2482 on the I2C bus of the unit, is bound by the kernel (the device tree
      or `echo ds2482 0x18 > /sys/bus/i2c/devices/i2c-N/new_device`), the sensors by the modules `w1_therm`,
      `w1_ds2438`, `w1_ds2408`, `w1_ds2413` and `w1_ds2406`. Without the master Evok logs
      `cannot use the 1-Wire master, is its driver loaded (e.g. ds2482)?` once and tries again every 10 s.
        - `master` - the 1-Wire master of the kernel, e.g. `w1_bus_master1` (Default is the first one).
          Each OWFS bus needs its own master, the second bus with the same master is not created
          and the error is logged.
        - `interval` - interval of values updating in seconds, a positive number (Default value is `60`)
        - `scan_interval` - interval in seconds of taking the devices found by the kernel, which searches the bus
          every 10 s; `0` takes them only after the start and on request (`do_scan`) (Default value is `300`).
          A change by the API applies at once.

      With the write access to the master `do_scan` forces a search of the bus and the thermometers due
      at the same time (in the half of their interval) are converted at once, before each one took 750 ms.
      The attributes of the master are writable only by root, the udev rule
      [`60-evok-w1.rules`](https://github.com/UnipiTechnology/evok/blob/dev-3.1/etc/udev/rules.d/60-evok-w1.rules)
      gives the access to the group `evok`; copy it to `/etc/udev/rules.d/` and apply it by
      `udevadm trigger --subsystem-match=w1 --action=add`. Without it `do_scan` takes the devices of the last
      search of the kernel and each thermometer converts alone, Evok logs it once.
        - `owpower` - [Circuit](../circuit.md) of owpower device (for restarting bus; optional parameter)

### Device configuration

- *<device_name\>*: the device will be available in the API under this name. Has to be unique.
  The name of a Modbus device (`MODBUSTCP`, `MODBUSRTU`) has to be unique over all buses, it is the circuit
  of the device and of all its IOs, e.g. `1` and `'1'` are the same name. A device with the name of an already
  created Modbus device is not created and the error is logged.
  The name of a 1-Wire sensor has to be unique over all OWFS buses, also against the circuits of the found sensors
  (the address without the dots, e.g. `28A1B2C3D4E5F67B`). A configured sensor with the name of an already created
  sensor is not created and the error is logged, such a found sensor is skipped with a warning.
- `enabled` - an optional parameter, the device is skipped if it is `false` (Default value is `true`)

#### MODBUSTCP & MODBUSRTU

- `model` - assigns a Modbus register map (examples: `xS51`, `xS11`), see [hw_definitions](./hw_definitions.md), required.
- `slave-id` - slave address or unit-ID of the Modbus device, `1`..`247` on RTU, `0`..`255` on TCP (Default value is `1`).
  It has to be unique on a `MODBUSRTU` bus and on a Modbus TCP server (`hostname` and `port`), also when more
  `MODBUSTCP` buses connect to the same server. A device with the slave-id of an already created device is not created
  and the error is logged, e.g. after adding a device to a bus with autogenerated devices.
- `scan_frequency` - an optional parameter, determines how often values are read from the device per second,
  a positive number (Default value is 50).
- `scan_enabled` - an optional parameter, `true` or `false`, the device is not read periodically if it is `false` (Default value is `true`).
  Its devices are created after the first read, their values are then changed only by the writes of Evok.
  The scan can be enabled or disabled at runtime by `POST /json/modbus_slave/<device_name>` with `scan_enabled`.
- `device_info` - an optional parameter, describes the device: `family`, `model`, `sn`, `board_count`.

#### OWFS

- `type` - 1-Wire sensor type, options: [`DS18B20`, `DS18S20`, `DS2438`, `DS2408`, `DS2406`, `DS2413`].
  The `value` of a DS2406 is the state of its channel flip-flops, the kernel does not give the sensed levels.
- `address` - 1-Wire device address, the family and the serial number as listed by owserver, e.g. `28.4E2025090000`;
  the CRC (`28.4E2025090000.FF`), the dots and the case are not significant. The name of the device in sysfs
  (`28-00000925204e`, the serial number in the reverse order) is the same address. The sensor is read after
  the kernel finds it, a sensor which the search of the bus has not found is reported as `lost`.
- `interval` - an optional parameter, interval of values updating in seconds (Default value is 15).

!!! Note
    It is better to use automatic device search, rather than defining devices manually.

### Examples

Every definition must be in `comm_channels` section.

#### Modbus RTU device

```yaml title="xS51 on /dev/ttyNS0"
RS485_1:
  type: MODBUSRTU
  port: /dev/ttyNS0
  baudrate: 19200
  parity: 'N'
  devices:
    xS51:
      slave-id: 1
      model: xS51
```

#### Modbus TCP device

```yaml title="IAQ on TCP"
TCP_EXT:
  type: MODBUSTCP
  hostname: 192.168.0.54
  port: 502
  devices:
    myIAQ:
      slave-id: 1
      model: IAQ
```

#### 1-Wire device

```yaml title="1-Wire thermometer"
TEMPM:
  type: OWFS
  interval: 10
  scan_interval: 60
  owpower: 1
```

## Autogen

If the Debian package `unipi-os-configurator` is installed,
Evok can automatically create the hardware configuration for the running device,
but it works only for Unipi controllers.
You can enable this feature with `autogen: true` in config.
If this feature is enabled, Evok includes the file `autogen.yaml` from the configuration directory (`/etc/evok/autogen.yaml` by default).
This file contains the hardware configuration of the running device.
`unipi-os-configurator` generates this file if a hardware change has been detected.
You can force the creation of this file using this command:

```bash
/opt/unipi/tools/os-configurator -f
```

### Autogen rules
 - The Bus is always named `LOCAL_TCP`.
 - A device_info section is generated to describe the device. This information is based on `unipiid`.
 - The device name is generated based on the `slave-id`. In standard Unipi controllers it is the same as the section number.
 - The OWFS section is generated only if the device supports 1-Wire and the `owserver` package is installed
   (Evok 3.1 does not use owserver, the bus is read by the kernel).
   - The `owpower` parameter is defined only if Unipi controller supports this feature.

```yaml title="Autogen example"
comm_channels:
  LOCAL_TCP:
    type: MODBUSTCP
    hostname: 127.0.0.1
    port: 502
    device_info:
      family: Neuron
      model: L533
      sn: 0
      board_count: 3
    devices:
      1:
        slave-id: 1
        model: 00
      2:
        slave-id: 2
        model: 13
      3:
        slave-id: 3
        model: 13
  OWFS:
    type: OWFS
    interval: 10
    scan_interval: 60
    owpower: 1
```

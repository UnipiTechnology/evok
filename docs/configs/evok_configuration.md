# Evok configuration

Evok configuration is located in `/etc/evok/config.yaml`. The default configuration is installed by the debian package. To apply the configuration, it is necessary to restart Evok with the command `systemctl restart evok`.

## API settings

In this section you can configure address and port for API listening. These settings will be applied to protocols [REST](../apis/rest.md), [JSON](../apis/json.md), [BULK](../apis/bulk.md), [RPC](../apis/rpc.md), [Webhook](../apis/webhook.md), [WebSocket](../apis/websocket.md).

- `port` - port for API listening, needs to be changed in `etc/nginx/sites-available/evok` too
- `address` - adress of the interface for API listening, clear or remove the parameter to listen on all interfaces

### Websocket

- `enabled` - enables websocket API (`true` / `false`)
- `all_filtered` - all WebSocket requests will be subject to the filtering set by 'filter' (`true` / `false`)

### Webhook

- `enabled` - enables webhook notifications (`true` / `false`)
- `address` - address (with port) to which notifications should be sent
- `device_mask` - list of devices to notify on (written as a JSON list, same format as `address`)
- `complex_events` - Evok will send POST requests with the same data as WebSocket, rather than an empty GET request

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
                model: <model_id>
                scan_frequency: <scan_frequency>
```

### Bus configuration

- *<bus_name\>* - Your choice, but has to be unique
- `type` options:
    - `MODBUSTCP`
        - `hostname` - hostname of the Modbus server
        - `port` - port of the Modbus server
    - `MODBUSRTU`
        - `port` - path to the Modbus device
        - `boudrate` - baudrate of the Modbus device
        - `parity` - parity of the Modbus device (`N` / `E` / `O`)
    - `OWBUS`
        - `interval` - interval of values updating
        - `scan_interval` - new devices will be automatically assigned
        - `owpower` - [Circuit](../circuit.md) of owpower device (for restarting bus; optional parameter)

### Device configuration

- *<device_name\>*: the device will be available in the API under this name. Has to be unique.

#### MODBUSTCP & MODBUSRTU

- `model_id` - assigns a Modbus register map (examples: `xS51`, `xS11`), see [hw_definitions](./hw_definitions.md).
- `slave_id` - slave address or unit-ID of the Modbus device.
- `scan_frequency` - an optional parameter, determines how often values are read from the device (Default value is 50).

#### OWBUS

- `type` - 1-Wire sensor type, options: [`DS18B20`, `DS18S20`, `DS2438`, `DS2408`, `DS2406`, `DS2404`, `DS2413`]
- `address` - 1-Wire device address

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
  type: OWBUS
  interval: 10
  scan_interval: 60
  owpower: 1
```

## Autogen

If the Debian package `unipi-os-configurator` is installed,
Evok can automatically create the hardware configuration for the running device,
but it works only for Unipi controllers.
You can enable this feature with `autogen: true` in config.
If this feature is enabled, Evok includes the file `/etc/evok/autogen.yaml`.
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
 - The OWFS section is generated only if the device supports 1-Wire and the `owserver` package is installed.
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
    type: OWBUS
    interval: 10
    scan_interval: 60
    owpower: 1
```

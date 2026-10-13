# Device circuit

Circuit is a unique identifier of a particular entity (input, output, or function) of each device.
The circuit is created automatically during initialization of Evok according to the table below.

**Circuit creation table:**

| Device type name    | Key            | Circuit format                                    | Examples                   |
|---------------------|----------------|---------------------------------------------------|----------------------------|
| Relay               | *ro*           | <device_name\>_<number\>                          | `2_01`, `xS11_02`          |
| Digital Output      | *do*           | <device_name\>_<number\>                          | `1_01`, `1_02`             |
| Digital Input       | *di*           | <device_name\>_<number\>                          | `1_01`, `xS11_02`          |
| Analog Output       | *ao*           | <device_name\>_<number\>                          | `1_01`, `xS51_02`          |
| Analog Input        | *ai*           | <device_name\>_<number\>                          | `1_01`, `xS51_02`          |
| User LED            | *led*          | <device_name\>_<number\>                          | `1_01`, `2_02`             |
| Master Watchdog     | *wd*           | <device_name\>                                    | `1`, `2`, `xS51`           |
| 1-Wire bus          | *owbus*        | <bus_name\>                                       | `OWFS`                     |
| 1-Wire power        | *owpower*      | <device_name\>                                    | `1`                        |
| 1-Wire sensor       | *sensor*       | <1-Wire_address\> / <device_name\>               | `2895DCD509000035`, `room` |
| Non-volatile memory | *nv_save*      | <device_name\>                                    | `1`, `2`, `xS51`           |
| Modbus slave        | *modbus_slave* | <device_name\>                                    | `1`, `2`, `IAQ`            |
| Sequencer           | *sequencer*    | <output_type\>_<output_circuit\>                 | `do_1_01`, `led_xS51_02`   |
| Modbus RTU bus      | *serial_bus*   | <bus_name\>                                       | `RS485_1`                  |
| Modbus TCP bus      | *tcp_bus*      | <bus_name\>                                       | `LOCAL_TCP`                |
| Device info         | *device_info*  | <model_name\> (grouped) / <device_name\> (single) | `L533`, `S167`, `xS51`     |
| Data point          | *data_point*   | <device_name\>_<register_address\>                | `IAQ_0`, `IAQ_6`, `IAQ_10` |
| Modbus register     | *register*     | <device_name\>_<register_address\>[_inp]          | `1_0`, `1_1000`, `1_3_inp` |
| Aliases             | *run*          | `alias`                                           | `alias`                    |

- *<device_name\>*: Name defined in [Evok configuration].
    - examples: `1`, `2`, `3`, `IAQ`, `xS51`, `xS18`.
    - note: [autogen](./configs/evok_configuration.md#autogen) generates device_name as a section number.
- *<bus_name\>*: Name of the bus in `comm_channels` of [Evok configuration].
    - examples: `RS485_1`, `LOCAL_TCP`.
- *<model_name\>*: Name defined in device_info configuration section.
  - examples: `L523`, `S103`, `S167`.
- *<number\>*: Sequence number (is based on the 'count' parameter in the [HW definition]).
    - examples: `01`, `02`, `03`, `04`, `05`, `06`, `10`, `11`, `12`.
- *<1-Wire_address\>*: 1-Wire address of a sensor found on the bus.
    - Thermometers and DS2438: the address without dots, e.g. `2895DCD509000035` (from `28.95DCD5090000.35`).
    - DS2408, DS2406 and DS2413: the address with the dots, e.g. `29.F2FBE3010000.0F`.
    - A sensor configured in `devices` of the OWFS bus has the name of the configuration as its circuit.
    - The key *sensor* has the alternative names *temp* and *1wdevice*; `dev` in the state of a thermometer is `temp`,
      of the other sensors `1wdevice`.
- *<register_address\>*: Modbus register address (is based on the 'count' parameter in the [HW definition]).
    - examples: `0`, `1`, `12`, `1000`, `1100`.
    - an input register has the suffix `_inp`; the feature REGISTER is deprecated, use DATA_POINT.

[Evok configuration]:./configs/evok_configuration.md#device-configuration
[HW definition]:./configs/hw_definitions.md#modbus_features

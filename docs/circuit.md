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
| Master Watchdog     | *wd*           | <device_name\>_<number\>                          | `1_01`, `1_02`             |
| 1-Wire bus          | *owbus*        | <device_name\>                                    | `1`                        |
| 1-Wire power        | *owpower*      | <device_name\>                                    | `1`                        |
| Temp sensor         | *temp*         | <1-Wire_address\>                                 | `2895DCD509000035`         | 
| Non-volatile memory | *nvsave*       | <device_name\>                                    | `1`, `2`, `xS51`           |
| Modbus slave        | *modbus_slave* | <device_name\>                                    | `1`, `2`, `IAQ`            |
| Device info         | *device_info*  | <model_name\> (grouped) / <device_name\> (single) | `L533`, `S167`, `xS51`     |
| Data point          | *data_point*   | <device_name\>_<register_address\>                | `IAQ_0`, `IAQ_6`, `IAQ_10` |
| Modbus register     | *register*     | <device_name\>_<register_address\>                | `1_0`, `1_1`, `1_1000`     |

- *<device_name\>*: Name defined in [Evok configuration].
    - examples: `1`, `2`, `3`, `IAQ`, `xS51`, `xS18`.
    - note: [autogen](./configs/evok_configuration.md#autogen) generates device_name as a section number.
- *<model_name\>*: Name defined in device_info configuration section.
  - examples: `L523`, `S103`, `S167`.
- *<number\>*: Sequence number (is based on the 'count' parameter in the [HW definition]).
    - examples: `01`, `02`, `03`, `04`, `05`, `06`, `10`, `11`, `12`.
- *<1-Wire_address\>*: 1-Wire device address without dots.
    - examples: `2895DCD509000035` (from 1-Wire address: `28.95DCD5090000.35`),
- *<register_address\>*: Modbus register address (is based on the 'count' parameter in the [HW definition]).
    - examples: `0`, `1`, `12`, `1000`, `1100`.

[Evok configuration]:./configs/evok_configuration.md#device-configuration
[HW definition]:./configs/hw_definitions.md#modbus_features

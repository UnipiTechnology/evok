# HW definitions

Hardware definitions specify the communication with Modbus devices. They are located in `/etc/evok/hw_definitions/`, each file represents one Modbus device. The file name is the device code, which may be used to add the device in the Evok configuration. The file is divided into two main parts, `modbus_register_blocks` defines which registers will be used and how often will be read, `modbus_features` breaks them into individual devices.

## modbus_register_blocks

Contains a list that defines the Modbus register groups. These registers must be placed consecutively. Each block is read in a separate request. Parameters:

- `start_reg` - first Modbus register address of the block
- `count` - number of Modbus registers to read, at most `125` (one Modbus request), the registers must be at most `65535`;
  the blocks of one type must not overlap
- `scan_divider` - the block is read in every `scan_divider`-th scan of the unit, i.e. with the frequency
  [scan_frequency](./evok_configuration.md#modbustcp-modbusrtu)÷`scan_divider` Hz, each
  `scan_divider`÷`scan_frequency` seconds; `1` reads it in every scan. The old name `frequency` is a deprecated alias.
- `type` - Modbus register type, set to `holding` (default) or `input`

```yaml title="Example"
# This key defines which Modbus registers will be periodically read. Each block (also sometimes referred to as "group") is read once every ["scan_divider"] read cycles.
modbus_register_blocks:
    - start_reg   : 0
      count       : 10
      scan_divider: 1

    - start_reg   : 500
      count       : 8
      scan_divider: 10

    - start_reg   : 508
      count       : 8
      scan_divider: 50
      type        : input
```

## modbus_features

Contains a list that defines devices and their required parameters. Each element contains the following parameters:

- `type` - device type, supported devices are listed below.
- `count` - number of devices of the type, register addresses increment based on this number
- `reg_type`- Modbus register type, set to `holding` (default) or `input`
- `start_index` - an optional parameter of DI, DO, RO and LED, the number of the IOs of the previous features of the type,
  e.g. `16` for the second feature of the relays 17-28 (Default value is `0`). The circuits of the devices must be unique,
  a device with a duplicate circuit and the next devices of its feature are not created.

Other parameters depend on the specific type of device.

!!! note
    All registers addresses are just the starting ones, they get incremented depending on the type.

### DO (digital output)

Allows you to add a digital output for the Modbus device.

- `val_reg` - value register address, each bit will be treated as a separate device
- `pwm_reg` - PWM duty register address
- `pwm_ps_reg` - PWM prescale register address
- `pwm_c_reg` - PWM cycle register address
- `modes` - list of available DO modes
    - `Simple` - basic binary mode
    - `PWM` - output with PWM support

!!! tip
    More information about PWM can be found on [Unipi KB](https://kb.unipi.technology/en:sw:01-mervis:advanced-modes-of-digital-outputs-hidden).

```yaml title="Example"
  - type        : DO
    count       : 4
    modes       :
      - Simple
      - PWM
    val_reg     : 1
    val_coil    : 0
    pwm_reg     : 16
    pwm_ps_reg  : 1017
    pwm_c_reg   : 1018
```

### RO (relay output)

Allows you to add a relay output for the Modbus device.

- `val_coil` - coil register address
- `val_reg` - value register address, each bit will be treated as a separate device

```yaml title="Example"
  - type        : RO
    count       : 5
    val_reg     : 1
    val_coil    : 0
```

### LED (user LED)

Allows you to add the user LEDs of the Modbus device (ULED), their [circuits](../circuit.md) are
`<device_name>_<number>`. An LED is set as a relay output, by `value` and an optional `pulse_duration`.

- `val_coil` - coil address of the first LED, the next LEDs follow
- `val_reg` - value register address, each bit will be treated as a separate device,
  the LEDs 17-32 are in the next register

```yaml title="Example"
  - type        : LED
    count       : 4
    val_coil    : 8
    val_reg     : 20
```

### DI (digital input)

Allows you to add a digital input for the Modbus device.

- `val_reg` - value register address, each bit will be treated as a different device
- `counter_reg` - counter register address, two registers are used for each device
- `deboun_reg` - debounce register address
- `modes`- list of available DI modes
    - Simple - regular mode
    - DirectSwitch - DI switches RO directly in firmware
- `ds_modes` - list of available direct switch modes
    - Simple
    - Inverted
    - Toggle
- `direct_reg` - direct switch register address
- `polar_reg` - polarity register address
- `toggle_reg` - toggle register address

```yaml title="Example"
  - type        : DI
    count       : 4
    modes       :
      - Simple
      - DirectSwitch
    ds_modes    :
      - Simple
      - Inverted
      - Toggle
    val_reg     : 0
    counter_reg : 16
    direct_reg  : 1016
    deboun_reg  : 1010
    polar_reg   : 1017
    toggle_reg  : 1018
```

### AO (analog output)

Allows you to add an analog output for the Modbus device.

- `val_reg` - value register address
- `mode_reg` - mode register address
- `modes` - list of available modes (names will be available in API), each has to have specified all parameters
    - `value` - value for mode_reg, a unique integer; without `mode_reg` define one mode, it is fixed and cannot be switched
    - `unit` - value unit
    - `range` - min and max values defined in an array

```yaml title="Example"
  - type        : AO
    count       : 4
    modes       :
      Voltage:
        unit: 'V'
        range: [0, 10]
    min_v       : 0
    max_v       : 10
    val_reg     : 2
```

### AI (analog input)

Allows you to add an analog input for the Modbus device.

- `val_reg` - value register address, the inputs follow each other by two registers
- `mode_reg` - mode register address
- `modes` - list of available modes (names will be available in API), each has to have specified all parameters
    - `value` - value for mode_reg, a unique integer; without `mode_reg` define one mode, it is fixed and cannot be switched
    - `unit` - value unit
    - `range` - min and max values defined in an array
    - `transformation` - an optional conversion of the value in the mode:
        - `datatype` - `float32` (default), `uint32`, `int32`, `uint16`, `int16`, `signed16`, the 32-bit ones low word first;
          an unknown datatype is an error of the feature
        - `ratio`, `offset` - the value is `raw * ratio + offset` (Default values are `1` and `0`)
        - `decimals` - rounding of the value (Default value is `3` for `float32`, no rounding for the others)

The API reports only `unit` and `range` of the modes.

```yaml title="Example"
- type        : AI
  count       : 4
  val_reg     : 6
  mode_reg    : 1019
  modes       :
    Disabled:
      value: 0
    Voltage10:
      value: 1
      unit: 'V'
      range: [0, 10]
    Voltage2V5:
      value: 2
      unit: 'V'
      range: [0, 2.5]
    Current20m:
      value: 3
      unit: 'mA'
      range: [0, 20]
    Resistance3W:
      value: 4
      unit: 'Ohm'
      range: [0, 1960]
    Resistance2W:
      value: 5
      unit: 'Ohm'
      range: [0, 100000]
```

### WD (watchdog)

Allows you to add a watchdog for the Modbus device. A device has one watchdog, `count` is not used,
its circuit is the name of the device.

- `val_reg` - value register address
- `timeout_reg` - timeout register address
- `reset_coil` - reset coil address
- `nv_sav_coil` - not used, the settings are saved by the NV_SAVE feature

```yaml title="Example"
  - type        : WD
    val_reg     : 6
    timeout_reg : 1008
    reset_coil  : 1002
```

### OWPOWER (1-Wire power)

Switches the power of the 1-Wire bus of the device, the [OWFS bus](./evok_configuration.md#bus-configuration) restarts
the bus by it with its parameter `owpower`. A device has one 1-Wire power, `count` is not used,
its circuit is the name of the device.

- `val_coil` - coil address, `1` disables the power of the bus, `0` powers it

The state of the coil is not read from the device, the value is the last one written by Evok, `0` after the start.

```yaml title="Example"
  - type        : OWPOWER
    val_coil    : 1001
```

### NV_SAVE (non-volatile memory)

Saves the current settings of the device to its non-volatile memory, the device uses them after a restart.
Writing `1` writes the coil, the value is held at `1` for 0.5 s and another write is refused until then.
A device has one NV save, `count` is not used, its circuit is the name of the device.

- `val_coil` - coil address

```yaml title="Example"
  - type        : NV_SAVE
    val_coil    : 1003
```

### DATA_POINT (data point)

If no other type is viable, data point may be used.

- `name` - value name
- `unit` - value unit
- `value_reg` - value register address, with `count` greater than 1 the data points follow each other,
  a 32-bit one takes two registers
- `datatype` - value data type
    - null (`signed16`)
    - `uint16`, `int16`, `signed16`
    - `uint32`, `int32`, `float32` (high word first)
- `writable` - the value can be written through the API, `false` (default) or `true`,
  the register must be `holding`, a writable data point in an `input` register is not created

```yaml title="Example"
- type        : DATA_POINT
  name        : "temperature"
  count       : 1
  value_reg   : 0
  unit        : "°C"
  datatype    : float32
```

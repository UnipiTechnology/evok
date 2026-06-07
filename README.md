# Evok - the Unipi API

Evok is the primary API for accessing I/Os of [NEURON], [PATRON], [GATE] and [Unipi 1.1] devices including [Extension modules] by [Unipi technology].

It provides multiple ways to easily access the I/Os of the devices, including:

- RESTful WebForms API
- RESTful JSON API
- Bulk request JSON API
- WebSocket API
- JSON-RPC API

Besides that, Evok also supports sending notifications via webhook.

[evok-web] is a simple demo web application using Evok demonstrating its usage and allowing easy control of the devices configured in Evok.

## Documentation
Installation, basic usage examples, configuration and further information can be found on [https://evok.readthedocs.io/](https://evok.readthedocs.io/)

Complete API documentation (REST and JSON API) including syntax of all other APIs can be found on [https://unipitechnology.stoplight.io/docs/evok](https://unipitechnology.stoplight.io/docs/evok) and is also released in OpenAPI format [Evok_API_OAS.yaml](docs/apis/Evok_API_OAS.yaml?raw=1)

## Major changes between Evok v2 and v3

- Evok v3 is based on Python3.
- API breaking changes:
    - Relay entities are excluded from the `output` endpoint and have a separate endpoint `ro`.  Alternate access via `relay` is still available.
    - Digital output entities are excluded from the `output` endpoint and have a separate endpoint `do`. Alternate access via `output` is still available.
    - Digital input entities are excluded from the `input` endpoint and have a separate endpoint `di`. Alternate access via `input` is still available.
    - Modified methods of setting analog input `ai` and analog output `ao` modes - mode and range are unified into one parameter. For more information see Analog input and Analog output modes in [API documentation](https://unipitechnology.stoplight.io/docs/evok).
    - Renamed `unit_register` entity to `data_point`.
- Updating Evok from v2 to v3 is unsupported as well as migration from Debian 10 is unsupported - it's recommended to start from a fresh operating system.
- The configuration of Evok has been completely rewritten to yaml based on tree structure(old .conf structure is no longer supported). See more information in the [Evok configuration](https://evok.readthedocs.io/en/latest/configs/evok_configuration/).
- Dropped support of rarely used functions/entities (Eeprom,i2cbus,adchip,mcp,gpiobus,pca9685,unipi2,uart,wifi,light_channel,light_device,ext_config)
- Example website aka 'Unipi Control Panel' has been split into separate project [evok-web-jq](https://github.com/UniPiTechnology/evok-web-jq) and can be installed manually.
- Added option 'all' instead of circuit using API (/rest/relay/all).
- The device names in the API now match the name in the configuration. For more information see [evok configuration](https://evok.readthedocs.io/en/latest/configs/evok_configuration/#device-configuration).
- [Aliases](https://evok.readthedocs.io/en/latest/configs/aliases/) system has been rewritten. Aliases are automatically saved 5 mins after a change, not immediately. Saving of aliases can be forced via API.
- Aliases definition file structure has been changed. Evok automatically updates the aliases definition file if a version from Evok v2 is found.
- Modbus RTU durability has been improved. Loss of communication with one device will not affect the functionality of the entire bus.
- Added support to communicate with more Modbus TCP servers.

## Developer Note

Do you feel like contributing to Evok, or perhaps have a neat idea for an improvement to our system? Feel free to contribute to this repository.

## License

Apache License, Version 2.0

[NEURON]:https://www.unipi.technology/products/unipi-neuron-3?categoryId=2
[PATRON]:https://www.unipi.technology/products/unipi-patron-374
[GATE]:https://www.unipi.technology/products/unipi-gate-388
[Unipi 1.1]:https://www.unipi.technology/products/unipi-1-1-1-1-lite-19?categoryId=1
[Evok-web]:https://github.com/UniPiTechnology/evok-web-jq
[Extension modules]:https://www.unipi.technology/products?category=32
[Unipi technology]:https://www.unipi.technology/

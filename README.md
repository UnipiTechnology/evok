# Evok - the Unipi API

Evok is a bridge between the hardware manufactured by [Unipi technology] (controllers, extensions and 1-Wire sensors) and user applications.
It turns the Modbus registers of the hardware into named devices (digital input `di 1_01`) with known state (`On/Off`),
abstracting away Modbus communication and the register maps.

> **Warning:** Evok is **not suitable** for applications with any real-time guarantees.
> For users looking to implement those applications, please use the Modbus protocol directly or use [unipi-tools], which provide faster access to the controller hardware via a kernel interface.


## Main Features


### Software-Defined Hardware

Hardware exposed by Evok is defined in a YAML file, matching real physical I/O to sub-devices with defined operating modes, units and allowed ranges.


### Always Up-to-date State

Evok periodically reads the state of the underlying hardware and updates it so that no explicit reads from hardware are needed from the user side.
The state is also timestamped - the user can check for stale data (fields `comm` and `last_comm`).
Changes of the state can also be observed by subscribing to events.


### Deterministic and Rich Writes

Any change made through the bridge is validated, written to the underlying hardware without data races.
The bridge also supports output sequences, driven by its sequencer.


### One Definition, Multiple APIs

The same hardware definition is exposed using multiple APIs, including:

- RESTful WebForms API
- RESTful JSON API (OpenAPI spec available)
- Bulk request JSON API
- WebSocket API
- JSON-RPC API
- MQTT API with Home Assistant auto-discovery
- Webhook notifications


### (Optional) Web Interface

[evok-web] is a simple demo web application using the APIs exposed by Evok, demonstrating its usage and allowing easy control of the devices configured in Evok.


## Supported Hardware

- Unipi controllers - [Neuron], [Patron], [Gate] and [Unipi 1.1]
- Unipi [Extension Modules]
- Modbus RTU/TCP devices (need additional definitions)
- 1-Wire devices on the 1-Wire bus of the controller (read by the kernel):
    - thermometers DS18B20 and DS18S20
    - DS2438 (e.g. humidity sensors with HIH4000): temperature, VDD, VAD and humidity
    - DS2408, DS2406 and DS2413: the levels of the PIOs, read-only


## Documentation

Installation, basic usage examples, configuration and further information can be found in the [documentation].

[Evok_API_OAS.yaml] is the specification of evok's RESTful JSON API. It is automatically generated and published upon every release.
The other APIs are described in the [documentation].


## Major Changes Between Evok 3.0 and 3.1

- **Python 3.12 and Debian 13 Trixie**, `tmodbus` instead of `pymodbus`, `uv` package and project manager system, support for venv installation.
- **Enhanced security:** the API listens on `127.0.0.1` by default, an optional `token` and a read-only `read_token`
  for all APIs, CORS and the WebSocket from a browser only for `allowed_origins`.
- **Stricter checks:** invalid values and configurations are refused with an error instead of being processed
  silently; the errors have the HTTP statuses 400, 401, 403, 404, 409, 503 and 500.
- **MQTT API** with Home Assistant auto-discovery.
- **Timestamped state:** every state of a device of a Modbus unit and of a 1-Wire sensor has `comm`
  and `last_comm`; a unit which does not respond does not slow down the others on the bus.
- **Linux-native 1-Wire** instead of using owserver the OWFS bus is configured by its `master` provided by the Linux kernel.
- **Sequencer:** the pulses and sequences of RO, DO and LED are set by the output device `sequencer`,
  the outputs no longer have `pulse_duration`, `timeout` and `pending`.
- **OpenAPI spec** generated from the sources and published with every release.

For a complete changelog, see [docs/api-changes-dev-src.md](docs/api-changes-dev-src.md).


## Contributing

Do you feel like contributing to Evok, or perhaps have a neat idea for an improvement to our system? Feel free to contribute to this repository.


## License

Apache License, Version 2.0

[Neuron]: https://www.unipi.technology/products/unipi-neuron-3?categoryId=2
[Patron]: https://www.unipi.technology/products/unipi-patron-374
[Gate]: https://www.unipi.technology/products/unipi-gate-388
[Unipi 1.1]: https://www.unipi.technology/products/unipi-1-1-1-1-lite-19?categoryId=1
[evok-web]: https://github.com/UnipiTechnology/evok-web-jq
[Extension Modules]: https://www.unipi.technology/products?category=32
[Unipi technology]: https://www.unipi.technology/
[unipi-tools]: https://github.com/UnipiTechnology/unipi-tools
[Evok_API_OAS.yaml]: https://github.com/UnipiTechnology/evok/releases/latest/download/Evok_API_OAS.yaml
[documentation]: https://evok.readthedocs.io/

# Evok - the Unipi API

Evok is the primary API for accessing I/Os of [NEURON], [PATRON], [GATE] and [Unipi 1.1] devices including [Extension modules] by [Unipi technology].

It provides multiple ways to easily access the I/Os of the devices, including:

- RESTful WebForms API
- RESTful JSON API
- Bulk request JSON API
- WebSocket API
- JSON-RPC API
- MQTT API with Home Assistant discovery

Besides that, Evok also supports sending notifications via webhook.

[evok-web] is a simple demo web application using Evok demonstrating its usage and allowing easy control of the devices configured in Evok.

## Documentation
Installation, basic usage examples, configuration and further information can be found on [https://evok.readthedocs.io/](https://evok.readthedocs.io/)

The OpenAPI document of the REST and JSON API is generated from the sources (`python -m evok.openapi`) and published with every release: [Evok_API_OAS.yaml](https://github.com/UnipiTechnology/evok/releases/latest/download/Evok_API_OAS.yaml). The other APIs are described in the [documentation](https://evok.readthedocs.io/).

## Major changes between Evok 3.0 and 3.1

- **Python 3.12 and Debian 13 Trixie**, `tmodbus` instead of `pymodbus`; Evok can be installed also into a virtual
  environment by pip.
- **Security:** the API listens on `127.0.0.1` by default, an optional `token` and a read-only `read_token`
  for all APIs, CORS and the WebSocket from a browser only for `allowed_origins`.
- **MQTT API** with the Home Assistant discovery.
- **Sequencer:** the pulses and sequences of RO, DO and LED are set by the device `sequencer` of the output,
  the outputs have no `pulse_duration`, `timeout` and `pending`.
- **Communication of the devices:** every state of a device of a Modbus unit and of a 1-Wire sensor has `comm`
  and `last_comm`; a unit which does not respond does not slow down the others on the bus.
- **1-Wire by the kernel** instead of owserver, an OWFS bus is configured by its `master`.
- **Stricter checks:** invalid values and configurations are refused with an error instead of being processed
  silently; the errors have the HTTP statuses 400, 401, 403, 404, 409, 503 and 500.
- **OpenAPI document** generated from the sources and attached to every release.

The complete list, with the incompatible changes first and the commits of each change, is in
[docs/api-changes-dev-src.md](docs/api-changes-dev-src.md) (in Czech [docs/zmeny-api-dev-src.md](docs/zmeny-api-dev-src.md)).

## Developer Note

Do you feel like contributing to Evok, or perhaps have a neat idea for an improvement to our system? Feel free to contribute to this repository.

## License

Apache License, Version 2.0

[NEURON]:https://www.unipi.technology/products/unipi-neuron-3?categoryId=2
[PATRON]:https://www.unipi.technology/products/unipi-patron-374
[GATE]:https://www.unipi.technology/products/unipi-gate-388
[Unipi 1.1]:https://www.unipi.technology/products/unipi-1-1-1-1-lite-19?categoryId=1
[Evok-web]:https://github.com/UnipiTechnology/evok-web-jq
[Extension modules]:https://www.unipi.technology/products?category=32
[Unipi technology]:https://www.unipi.technology/

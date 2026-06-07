def test_devtype_names_exists():
    from evok.devices import devtype_names
    assert isinstance(devtype_names, dict)


def test_devtype_names_covers_standard_types():
    from evok.devices import devtype_names, num_to_devtype_name
    for name in num_to_devtype_name.values():
        assert name in devtype_names, f"'{name}' missing from devtype_names"
        assert devtype_names[name] == name


def test_devtype_names_used_in_mqtt_handler_import():
    # This will fail with ImportError until the fix is applied
    from evok.handler_mqtt import MqttHandler  # noqa — just checks the import resolves

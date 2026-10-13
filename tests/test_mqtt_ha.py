import json

import pytest

from evok.devices import Devices, AI, AO, DATA_POINT, DEVICE_INFO, DI, DO, LED, MODBUS_SLAVE, RO, SENSOR, WATCHDOG
from evok.mqtt_ha import discovery, ha_id
from evok.mqtt_handler import MqttSettings

from test_mqtt_handler import devices, mqtt, settle  # noqa: F401


class Unit:
    """ A device of a Modbus unit """
    def __init__(self, devtype, circuit, group='1'):
        self.devtype = devtype
        self.circuit = circuit
        self.major_group = group


def config(messages, component=None):
    assert len(messages) == 1
    topic, payload = messages[0]
    if component is not None:
        assert topic.split('/')[1] == component
    return topic, payload


def test_switch_of_a_relay():
    topic, payload = config(discovery('evok', 'homeassistant', RO, '1_01', {'dev': 'ro', 'circuit': '1_01', 'value': 0},
                                      device=Unit(RO, '1_01')), 'switch')
    assert topic == 'homeassistant/switch/evok/ro_1_01/config'
    assert payload == {
        'name': 'RO 1_01', 'unique_id': 'evok_ro_1_01', 'state_topic': 'evok/ro/1_01',
        'availability': [{'topic': 'evok/status', 'payload_available': 'online', 'payload_not_available': 'offline'}],
        'device': {'identifiers': ['evok_1'], 'name': 'evok 1', 'manufacturer': 'Unipi'},
        'command_topic': 'evok/ro/1_01/set', 'value_template': '{{ value_json.value }}',
        'state_on': '1', 'state_off': '0', 'payload_on': '1', 'payload_off': '0'}


@pytest.mark.parametrize('devtype', [RO, DO, LED])
def test_read_only_output_is_a_binary_sensor(devtype):
    _, payload = config(discovery('evok', 'homeassistant', devtype, '1_01', {'value': 0}, read_only=True,
                                  device=Unit(devtype, '1_01')), 'binary_sensor')
    assert 'command_topic' not in payload


def test_alias_is_the_name_and_ids_are_sanitized():
    _, payload = config(discovery('evok/boiler room', 'ha', DI, '29.3D2C1B000000.F1', {'value': 1, 'alias': 'door'},
                                  device=Unit(DI, '29.3D2C1B000000.F1', 'xS51')), 'binary_sensor')
    assert payload['name'] == 'door'
    assert payload['unique_id'] == 'evok_boiler_room_di_29_3D2C1B000000_F1'
    assert payload['state_topic'] == 'evok/boiler room/di/29.3D2C1B000000.F1'
    assert payload['device']['identifiers'] == ['evok_boiler_room_xS51']


def test_analog_input_and_output():
    _, ai = config(discovery('evok', 'ha', AI, '1_01', {'value': 2.5, 'unit': 'V'}, device=Unit(AI, '1_01')),
                   'sensor')
    assert (ai['unit_of_measurement'], ai['state_class']) == ('V', 'measurement')
    _, ao = config(discovery('evok', 'ha', AO, '1_01', {'value': 2.5, 'unit': 'mA', 'range': [0, 20]},
                             device=Unit(AO, '1_01')), 'number')
    assert (ao['min'], ao['max'], ao['unit_of_measurement'], ao['command_topic']) == (0, 20, 'mA', 'evok/ao/1_01/set')


def test_data_point():
    _, read = config(discovery('evok', 'ha', DATA_POINT, 'IAQ_0', {'value': 21, 'name': 'temperature', 'unit': '°C'},
                               device=Unit(DATA_POINT, 'IAQ_0', 'IAQ')), 'sensor')
    assert (read['name'], read['unit_of_measurement']) == ('temperature', '°C')
    _, write = config(discovery('evok', 'ha', DATA_POINT, 'IAQ_10', {'value': 1, 'writable': True},
                                device=Unit(DATA_POINT, 'IAQ_10', 'IAQ')), 'number')
    assert write['command_topic'] == 'evok/data_point/IAQ_10/set'


class Sensor:
    def __init__(self, circuit, bus='OWBUS'):
        self.circuit = circuit
        self.bus = type('Bus', (), {'circuit': bus})()


def test_one_wire_sensors():
    _, temp = config(discovery('evok', 'ha', SENSOR, '284E2025090000FF', {'dev': 'temp', 'value': 21.5},
                               device=Sensor('284E2025090000FF')), 'sensor')
    assert (temp['device_class'], temp['unit_of_measurement'], temp['device']['name']) == \
        ('temperature', '°C', 'evok OWBUS')
    messages = discovery('evok', 'ha', SENSOR, 'hum', {'dev': '1wdevice', 'type': 'DS2438'}, device=Sensor('hum'))
    assert [(p['name'], p['value_template'], p['device_class']) for _, p in messages] == [
        ('SENSOR hum temperature', '{{ value_json.temp }}', 'temperature'),
        ('SENSOR hum humidity', '{{ value_json.humidity }}', 'humidity'),
        ('SENSOR hum VDD', '{{ value_json.vdd }}', 'voltage'),
        ('SENSOR hum VAD', '{{ value_json.vad }}', 'voltage')]
    assert len({p['unique_id'] for _, p in messages}) == 4


def test_communication_of_a_unit():
    _, payload = config(discovery('evok', 'ha', MODBUS_SLAVE, 'xS51', {'scan_error': None},
                                  device=object()), 'binary_sensor')
    assert (payload['device_class'], payload['name']) == ('connectivity', 'MODBUS_SLAVE xS51 communication')
    assert payload['device']['identifiers'] == ['evok_xS51']


def test_model_of_the_unit():
    Devices[DEVICE_INFO]['xS51'] = type('Info', (), {'model': 'xS51'})()
    _, payload = config(discovery('evok', 'ha', DI, 'xS51_01', {'value': 0}, device=Unit(DI, 'xS51_01', 'xS51')))
    assert payload['device']['model'] == 'xS51'


@pytest.mark.parametrize('devtype, state', [(WATCHDOG, {'value': 0}), (SENSOR, {'dev': '1wdevice', 'type': 'DS2408'})])
def test_unsupported_devices(devtype, state):
    assert discovery('evok', 'ha', devtype, '1', state, device=Unit(devtype, '1')) == []


def test_device_without_a_group():
    assert discovery('evok', 'ha', RO, '9_99', {'value': 0}) == []           # not registered


def test_ha_id():
    assert ha_id('evok/a.b c-d_e') == 'evok_a_b_c-d_e'


@pytest.mark.parametrize('conf, error', [
    ({'ha_discovery': 'yes'}, "'ha_discovery' must be true or false"),
    ({'ha_prefix': 'ha/#'}, "'ha_prefix' must be a topic"),
    ({'ha_prefix': ''}, "'ha_prefix' must be a topic"),
])
def test_settings_invalid(conf, error):
    with pytest.raises(ValueError, match=error):
        MqttSettings(conf)


def configs(broker):
    return {topic: json.loads(payload) for topic, payload, retain in broker.client.published
            if topic.startswith('homeassistant/') and retain}


async def test_configs_are_published_before_the_states(mqtt):  # noqa: F811
    Devices[DI]['1_01'].major_group = Devices[RO]['1_01'].major_group = '1'
    handler, broker = await mqtt({'ha_discovery': True})
    topics = [topic for topic, _, _ in broker.client.published]
    assert topics.index('homeassistant/switch/evok/ro_1_01/config') < topics.index('evok/ro/1_01')
    assert topics.index('homeassistant/binary_sensor/evok/di_1_01/config') < topics.index('evok/di/1_01')
    assert configs(broker)['homeassistant/switch/evok/ro_1_01/config']['command_topic'] == 'evok/ro/1_01/set'


async def test_changed_config_is_published_again(mqtt):  # noqa: F811
    relay = Devices[RO]['1_01']
    relay.major_group = '1'
    handler, broker = await mqtt({'ha_discovery': True})
    count = len(broker.client.published)
    handler.on_event(relay)                             # the same config
    await settle()
    assert [t for t, _, _ in broker.client.published[count:]] == ['evok/ro/1_01']
    relay.full = lambda: {'dev': 'ro', 'circuit': '1_01', 'value': 0, 'alias': 'pump'}
    handler.on_event(relay)
    await settle()
    assert [t for t, _, _ in broker.client.published[-2:]] == ['homeassistant/switch/evok/ro_1_01/config',
                                                               'evok/ro/1_01']
    assert configs(broker)['homeassistant/switch/evok/ro_1_01/config']['name'] == 'pump'


async def test_no_configs_without_ha_discovery(mqtt):  # noqa: F811
    Devices[RO]['1_01'].major_group = '1'
    handler, broker = await mqtt()
    assert configs(broker) == {}


def test_availability_by_the_communication_of_the_unit():
    """ #201: an entity of a unit which does not respond is unavailable """
    _, payload = config(discovery('evok', 'ha', DI, '1_01', {'value': 1, 'comm': 'ok', 'last_comm': 0.02},
                                  device=Unit(DI, '1_01')))
    assert payload['availability_mode'] == 'all'
    assert payload['availability'][1] == {
        'topic': 'evok/di/1_01', 'value_template': "{{ 'online' if value_json.comm == 'ok' else 'offline' }}",
        'payload_available': 'online', 'payload_not_available': 'offline'}
    _, unit = config(discovery('evok', 'ha', MODBUS_SLAVE, 'xS51', {'scan_error': 'TimeoutError', 'comm': 'timeout'},
                               device=object()))
    assert len(unit['availability']) == 1 and 'availability_mode' not in unit     # it shows the outage

import inspect

import jsonschema
import pytest

from evok.devices import Aliases
from evok.modbus.analog import AnalogInput, AnalogOutput, AnalogOutputBrain, DataPoint, Register
from evok.modbus.digital import DigitalInput, DigitalOutput, Relay, ULED
from evok.modbus.special import NvSave, OwPower, Watchdog
from evok.owdevice import MySensor, OwBusDriver
from evok.schemas import schemas, bulk_post_inp_schema, bulk_post_inp_example

# the classes whose set() receives the validated request of each schema key
SET_CLASSES = {
    'input': [DigitalInput], 'di': [DigitalInput], 'digitalinput': [DigitalInput],
    'output': [DigitalOutput], 'do': [DigitalOutput], 'digitaloutput': [DigitalOutput],
    'ro': [Relay], 'relay': [Relay],
    'led': [ULED],
    'ai': [AnalogInput], 'analoginput': [AnalogInput],
    'ao': [AnalogOutput, AnalogOutputBrain], 'analogoutput': [AnalogOutput, AnalogOutputBrain],
    'register': [Register],
    'data_point': [DataPoint],
    'watchdog': [Watchdog], 'wd': [Watchdog],
    'nv_save': [NvSave],
    'owpower': [OwPower],
    '1wdevice': [MySensor], 'sensor': [MySensor], 'temp': [MySensor],
    'owbus': [OwBusDriver],
    'run': [Aliases],
}


def set_params(cls):
    """ Names of the keyword parameters of cls.set() without **kwargs """
    params = inspect.signature(cls.set).parameters.values()
    return {p.name for p in params
            if p.name != 'self' and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}


def test_every_schema_has_set_classes():
    assert set(schemas) == set(SET_CLASSES)


@pytest.mark.parametrize('dev', schemas)
def test_schema_matches_set_params(dev):
    properties = set(schemas[dev][0]['properties'])
    for cls in SET_CLASSES[dev]:
        assert properties == set_params(cls), cls.__name__


@pytest.mark.parametrize('kw', [
    {'value': 21.5}, {'value': '21.5'}, {'alias': 'setpoint'}, {},
])
def test_data_point_schema_accepts(kw):
    jsonschema.validate(instance=kw, schema=schemas['data_point'][0])


@pytest.mark.parametrize('kw', [
    {'value': True}, {'value': None}, {'mode': 'Voltage'},
])
def test_data_point_schema_rejects(kw):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=kw, schema=schemas['data_point'][0])


@pytest.mark.parametrize('dev', schemas)
def test_examples_match_schemas(dev):
    schema, example = schemas[dev]
    jsonschema.validate(instance=example, schema=schema)


@pytest.mark.parametrize('kw', [{'value': 5}, {'value': '5'}])
def test_register_schema_accepts(kw):
    jsonschema.validate(instance=kw, schema=schemas['register'][0])


@pytest.mark.parametrize('kw', [{'value': -1}, {'value': 65536}, {'value': True}])
def test_register_schema_rejects(kw):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=kw, schema=schemas['register'][0])


@pytest.mark.parametrize('request_body', [
    bulk_post_inp_example,
    {},
    {'group_queries': [{'device_types': ['di', 'do'], 'group': 1, 'device_circuits': ['1_01']}]},
    {'group_assignments': [{'device_type': 'do', 'assigned_values': {'value': 0}, 'group': '1'}]},
    {'individual_assignments': [{'device_type': 'ro', 'device_circuit': 1, 'assigned_values': {}}]},
])
def test_bulk_schema_accepts(request_body):
    jsonschema.validate(instance=request_body, schema=bulk_post_inp_schema)


@pytest.mark.parametrize('request_body', [
    [],
    {'unknown': []},
    {'group_queries': [{}]},
    {'group_assignments': [{'device_type': 'do'}]},
    {'individual_assignments': [{'device_type': 'do', 'assigned_values': {'value': 1}}]},
    {'individual_assignments': [{'device_type': 'do', 'device_circuit': '1_01', 'assigned_values': 1}]},
])
def test_bulk_schema_rejects(request_body):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=request_body, schema=bulk_post_inp_schema)


from evok.devices import to_bool, to_float
from evok.handlers_base import check_params


@pytest.mark.parametrize('dev, kw', [
    ('ao', {'value': float('nan')}), ('ao', {'value': 'nan'}), ('ao', {'value': 'inf'}),
    ('data_point', {'value': float('inf')}), ('data_point', {'value': '-Infinity'}),
    ('register', {'value': '70000'}), ('register', {'value': '-1'}),          # the range of strings
    ('do', {'pwm_duty': '150'}), ('do', {'pwm_freq': '-5'}),
    ('di', {'counter': '4294967296'}), ('wd', {'timeout': '-1'}),
    ('do', {'value': 1, 'pulse_duration': '-1'}), ('do', {'value': 1, 'timeout': 'inf'}),
    ('di', {'debounce': '65536'}), ('ro', {'value': 1, 'pulse_duration': '-1'}), ('led', {'value': 1, 'pulse_duration': '-1'}),
])
def test_check_params_rejects(dev, kw):
    with pytest.raises(ValueError):
        check_params(dev, kw)


@pytest.mark.parametrize('dev, kw', [
    ('ao', {'value': '5.5'}), ('ao', {'mode': 'Voltage2V5'}),                 # modes are checked by the device
    ('register', {'value': '65535'}), ('do', {'pwm_duty': '50', 'alias': 'nan'}),
    ('wd', {'value': True, 'reset': 'false', 'nv_save': 1}),
    ('do', {'value': 'on'}),                                                   # not a number, checked by the device
    ('do', {'value': 1, 'mode': 'PWM'}),                                       # mode is accepted for compatibility
])
def test_check_params_accepts(dev, kw):
    check_params(dev, kw)


@pytest.mark.parametrize('value', [float('nan'), 'nan', float('inf'), '-inf', 'x'])
def test_to_float_rejects(value):
    with pytest.raises(ValueError):
        to_float(value)


@pytest.mark.parametrize('value, expected', [('true', True), ('0', False), (1, True), (False, False)])
def test_to_bool(value, expected):
    assert to_bool(value) is expected


async def test_run_save_from_form():
    from evok.devices import Aliases
    saved = []
    aliases = Aliases({})
    aliases.register_save_cb(lambda: saved.append(True))
    await aliases.set(save='false')
    await aliases.set(save='true')
    assert saved == [True]


@pytest.mark.parametrize('dev, kw', [('do', {'alias': 'a' * 65}), ('di', {'counter_mode': 1})])
def test_schema_rejects_long_alias_and_counter_mode_type(dev, kw):
    with pytest.raises(jsonschema.ValidationError):
        check_params(dev, kw)

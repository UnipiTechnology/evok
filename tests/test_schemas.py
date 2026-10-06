import inspect

import jsonschema
import pytest

from evok.devices import Aliases
from evok.modbus.analog import AnalogInput, AnalogOutput, AnalogOutputBrain, DataPoint, Register
from evok.modbus.digital import DigitalInput, DigitalOutput, Relay, ULED
from evok.modbus.special import NvSave, OwPower, Watchdog
from evok.owdevice import MySensor, OwBusDriver
from evok.schemas import schemas

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

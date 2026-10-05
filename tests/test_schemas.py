import jsonschema
import pytest

from evok.schemas import schemas


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

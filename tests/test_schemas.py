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


def test_data_point_example_matches_schema():
    schema, example = schemas['data_point']
    jsonschema.validate(instance=example, schema=schema)

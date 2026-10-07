import asyncio

import pytest
import tornado.httpclient
import tornado.httpserver
import tornado.testing
import tornado.web
import yaml

from evok import config, evok
from evok.devices import Aliases


def test_save_aliases(tmp_path):
    path = tmp_path / 'alias.yaml'
    config.save_aliases({'kitchen': {'devtype': 'di', 'circuit': '1_01'}}, str(path))
    assert yaml.safe_load(path.read_text()) == {
        'version': '2.0', 'aliases': {'kitchen': {'devtype': 'di', 'circuit': '1_01'}}}
    assert not (tmp_path / 'alias.yaml.tmp').exists()


def test_failed_save_keeps_the_file(tmp_path, monkeypatch):
    path = tmp_path / 'alias.yaml'
    path.write_text('previous')

    def fail(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(config.yaml, 'dump', fail)
    with pytest.raises(OSError):
        config.save_aliases({}, str(path))
    assert path.read_text() == 'previous'


async def test_alias_task_retries_failed_save(tmp_path, monkeypatch):
    monkeypatch.setattr(evok.AliasTask, 'SAVE_TIME', 0.01)
    saved = []

    def save(alias_dict, path):
        if not saved:
            saved.append(None)
            raise OSError('disk full')
        saved.append(alias_dict)
    monkeypatch.setattr(evok.config, 'save_aliases', save)
    aliases = Aliases({'kitchen': {'devtype': 'di', 'circuit': '1_01'}})
    task = evok.AliasTask(aliases, str(tmp_path / 'alias.yaml'))
    aliases.set_dirty()
    for _ in range(100):
        if len(saved) > 1:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    assert saved[1:] == [{'kitchen': {'devtype': 'di', 'circuit': '1_01'}}]


@pytest.mark.parametrize('method, code', [('GET', 200), ('POST', 405)])
async def test_load_all_methods(method, code):
    sock, port = tornado.testing.bind_unused_port()
    server = tornado.httpserver.HTTPServer(tornado.web.Application([(r"/rest/all/?", evok.LoadAllHandler)]))
    server.add_sockets([sock])
    response = await tornado.httpclient.AsyncHTTPClient().fetch(
        f"http://127.0.0.1:{port}/rest/all", method=method, body='' if method == 'POST' else None, raise_error=False)
    server.stop()
    assert response.code == code


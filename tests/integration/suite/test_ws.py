"""WebSocket API functional tests."""

import pytest

pytestmark = pytest.mark.replay


async def test_ws_filter_command(ws):
    # open + send a filter; in record mode the harness captures the resulting stream.
    msgs = await ws.will_send({"cmd": "filter", "devices": ["do", "ao"]}).run(receive_for=1.0)
    # After a filter, subsequent server pushes should only contain filtered devs.
    # (Initial connection may also receive a default dump; assert no unfiltered dev.)
    for m in msgs:
        if isinstance(m, list):
            for entry in m:
                if isinstance(entry, dict) and "dev" in entry:
                    assert entry["dev"] in ("do", "ao"), f"filter leaked: {entry['dev']!r}"
        elif isinstance(m, dict) and "dev" in m:
            assert m["dev"] in ("do", "ao")


async def test_ws_all_command(ws, http, park_outputs):
    msgs = await ws.will_send({"cmd": "all"}).run(receive_for=1.0)
    # 'all' returns a single message that is itself a list (the device snapshot).
    assert len(msgs) >= 1
    first = msgs[0]
    assert isinstance(first, list)
    assert all("dev" in e and "circuit" in e for e in first if isinstance(e, dict))


async def test_ws_set_command_emits_change_event(ws, http, park_output):
    """A WS `set` command produces no direct reply; the change is observed as a
    server-pushed event on the next scan. Park DO 1_01 to 0, set it to 1 via WS,
    expect an event carrying value 1, then restore to 0.

    NOTE on the contract (inferred from evok.py WsHandler.on_message):
      - cmd=="set" -> getattr(device,"set")(value); a response is written ONLY
        for cmd=="full", so the ack comes solely via the event fan-out.
      - Events are only emitted on a detected transition (scan-cache diff), so
        the test forces a deterministic 0->1 change (park first).
    """
    next(park_output("do", "1_01", 0))  # deterministic start state

    events = await ws.will_send({"cmd": "set", "dev": "do", "circuit": "1_01", "value": 1}).run(
        receive_for=2.0
    )
    # restore to 0 via REST.
    http.post_form("/rest/do/1_01/", {"value": "0"})

    entries: list[dict] = []
    for m in events:
        if isinstance(m, list):
            entries.extend(e for e in m if isinstance(e, dict))
        elif isinstance(m, dict):
            entries.append(m)

    do_events = [e for e in entries if e.get("dev") == "do" and e.get("circuit") == "1_01"]
    assert do_events, "no DO 1_01 event received after WS set"
    values = {e.get("value") for e in do_events}
    assert 1 in values or True in values, f"set to 1 not observed in event values {values}"

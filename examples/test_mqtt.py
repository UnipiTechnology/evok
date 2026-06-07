#!/usr/bin/env python3
"""
Live end-to-end MQTT test for evok on a Unipi unit.

Tests the full MQTT datapath in both directions:
  Inbound  — external publish → broker → evok processes → device.set()
  Outbound — device state change → evok on_event() → broker → external subscribe

PREREQUISITES
  1. An MQTT broker reachable from this machine (e.g. mosquitto on the Unipi).

  2. Evok running with MQTT enabled.  Add/update /etc/evok/config.yaml:

       mqtt:
         address: localhost   # broker address as seen from the Unipi
         port: 1883
         client-id: evok      # must match the --client-id argument below

  3. At least one relay or digital output on the unit.
     Set --circuit to a real circuit (e.g. ro/1_01, do/1_01).
     The test will briefly toggle that output ON then OFF.

USAGE
  python examples/test_mqtt.py --broker 192.168.1.100
  python examples/test_mqtt.py --broker 192.168.1.100 --client-id evok --circuit ro/1_01

MANUAL HARDWARE TEST (not automated)
  To verify the outbound path triggered by real hardware input:
    1. Run:  mosquitto_sub -h <broker> -t '<client-id>/event/#' -v
    2. Manually toggle a digital input (DI) on the Unipi.
    3. Expect a message on <client-id>/event/di/<circuit>.

EXIT CODE  0 = all passed,  1 = one or more failures
"""

import asyncio
import argparse
import json
import sys

import aiomqtt

TIMEOUT = 5.0        # seconds to wait for expected messages
ERROR_TIMEOUT = 1.5  # seconds to confirm absence of a message (error-path tests)


class MqttE2ETest:
    def __init__(self, broker: str, port: int, client_id: str, circuit: str):
        self.broker = broker
        self.port = port
        self.client_id = client_id
        devtype, circuit_id = circuit.split("/", 1)
        self.devtype = devtype
        self.circuit_id = circuit_id
        self.passed = 0
        self.failed = 0

    def _ok(self, name: str, detail: str = ""):
        self.passed += 1
        suffix = f"  ({detail})" if detail else ""
        print(f"  PASS  {name}{suffix}")

    def _fail(self, name: str, detail: str = ""):
        self.failed += 1
        suffix = f"  ({detail})" if detail else ""
        print(f"  FAIL  {name}{suffix}")

    async def run(self) -> bool:
        print(f"\nConnecting  broker={self.broker}:{self.port}  client-id={self.client_id!r}")
        try:
            async with aiomqtt.Client(
                hostname=self.broker,
                port=self.port,
                identifier=f"{self.client_id}-e2etest",
            ) as client:
                print("  Connected\n")
                await client.subscribe(f"{self.client_id}/event/#")
                await client.subscribe(f"{self.client_id}/cmd/ALL")

                queue: asyncio.Queue = asyncio.Queue()

                async def drain():
                    async for msg in client.messages:
                        try:
                            payload = json.loads(msg.payload)
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            payload = msg.payload.decode(errors="replace")
                        await queue.put((str(msg.topic), payload))

                drainer = asyncio.create_task(drain())
                try:
                    await self._test_all(client, queue)
                    await self._test_set(client, queue, value=1)
                    await self._test_set(client, queue, value=0)
                    await self._test_state_consistency(client, queue)
                    await self._test_error_invalid_payload(client, queue)
                    await self._test_error_unknown_circuit(client, queue)
                finally:
                    drainer.cancel()
                    await asyncio.gather(drainer, return_exceptions=True)

        except aiomqtt.MqttError as exc:
            print(f"\nBroker connection error: {exc}")
            self.failed += 1

        print(f"\n{'─' * 50}")
        print(f"Results: {self.passed} passed, {self.failed} failed")
        return self.failed == 0

    # ── helpers ────────────────────────────────────────────────────────────────

    async def _recv(
        self, queue: asyncio.Queue, topic: str, timeout: float = TIMEOUT
    ) -> "dict | list | None":
        """Return first payload on `topic` within `timeout`, discarding others."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            try:
                recv_topic, payload = await asyncio.wait_for(
                    queue.get(), timeout=remaining
                )
                if recv_topic == topic:
                    return payload
            except asyncio.TimeoutError:
                return None

    def _circuit_str(self) -> str:
        return f"{self.devtype}/{self.circuit_id}"

    def _event_topic(self) -> str:
        return f"{self.client_id}/event/{self._circuit_str()}"

    def _cmd_topic(self) -> str:
        return f"{self.client_id}/cmd/{self._circuit_str()}"

    # ── tests ──────────────────────────────────────────────────────────────────

    async def _test_all(self, client: aiomqtt.Client, queue: asyncio.Queue):
        """Test 1: ALL command — query all devices via inbound command path."""
        print("Test 1: ALL command returns device list")
        all_topic = f"{self.client_id}/cmd/ALL"
        await client.publish(all_topic, json.dumps({}))
        result = await self._recv(queue, all_topic)
        if result is None:
            self._fail("ALL command", f"no response within {TIMEOUT}s")
        elif not isinstance(result, list):
            self._fail("ALL command", f"expected list, got: {str(result)[:80]}")
        elif len(result) == 0:
            self._fail("ALL command", "empty list — no devices configured in evok?")
        else:
            self._ok("ALL command", f"{len(result)} devices")

    async def _test_set(self, client: aiomqtt.Client, queue: asyncio.Queue, value: int):
        """Tests 2–3: Set output, verify outbound event (full round-trip)."""
        num = "2" if value else "3"
        circuit = self._circuit_str()
        print(f"Test {num}: Set {circuit} → {value}  (cmd → device → event)")
        await client.publish(self._cmd_topic(), json.dumps({"value": value}))
        result = await self._recv(queue, self._event_topic())
        if result is None:
            self._fail(
                f"set {circuit}={value}",
                f"no event on {self._event_topic()!r} within {TIMEOUT}s"
                " — is evok running and the circuit valid?",
            )
            return
        got = result.get("value")
        if got in (value, bool(value), str(value)):
            self._ok(f"set {circuit}={value}", f"event.value={got!r}")
        else:
            self._fail(f"set {circuit}={value}", f"expected {value!r}, got {got!r}")

    async def _test_state_consistency(self, client: aiomqtt.Client, queue: asyncio.Queue):
        """Test 4: ALL after toggle — verify state is reflected in device list."""
        print(f"Test 4: State consistency — ALL reflects {self._circuit_str()} value after set")
        # Set to 1 and capture event
        await client.publish(self._cmd_topic(), json.dumps({"value": 1}))
        event = await self._recv(queue, self._event_topic())
        if event is None:
            self._fail("state consistency", f"no event from set, cannot verify ALL")
            return

        # Query ALL and look for this circuit
        all_topic = f"{self.client_id}/cmd/ALL"
        await client.publish(all_topic, json.dumps({}))
        all_result = await self._recv(queue, all_topic)
        if all_result is None or not isinstance(all_result, list):
            self._fail("state consistency", "ALL returned no valid response")
            return

        matches = [
            d for d in all_result
            if d.get("dev") == self.devtype and d.get("circuit") == self.circuit_id
        ]
        if not matches:
            self._fail(
                "state consistency",
                f"circuit {self._circuit_str()} not found in ALL response",
            )
            return

        reported = matches[0].get("value")
        expected = event.get("value")
        if reported == expected:
            self._ok("state consistency", f"{self._circuit_str()} value={reported!r} in ALL matches event")
        else:
            self._fail(
                "state consistency",
                f"ALL reports value={reported!r} but event had value={expected!r}",
            )

        # Restore to 0
        await client.publish(self._cmd_topic(), json.dumps({"value": 0}))
        await self._recv(queue, self._event_topic(), timeout=TIMEOUT)

    async def _test_error_invalid_payload(self, client: aiomqtt.Client, queue: asyncio.Queue):
        """Test 5: Schema-invalid payload → evok logs error, no event published."""
        print(f"Test 5: Error path — invalid payload produces no event")
        await client.publish(self._cmd_topic(), json.dumps({"__no_such_field": True}))
        result = await self._recv(queue, self._event_topic(), timeout=ERROR_TIMEOUT)
        if result is None:
            self._ok("invalid payload → no event")
        else:
            self._fail("invalid payload → no event", f"unexpectedly got event: {result}")

    async def _test_error_unknown_circuit(self, client: aiomqtt.Client, queue: asyncio.Queue):
        """Test 6: Unknown circuit → evok logs error, no event published."""
        print(f"Test 6: Error path — unknown circuit produces no event")
        bad_topic = f"{self.client_id}/cmd/{self.devtype}/NONEXISTENT_99"
        bad_event = f"{self.client_id}/event/{self.devtype}/NONEXISTENT_99"
        await client.publish(bad_topic, json.dumps({"value": 1}))
        result = await self._recv(queue, bad_event, timeout=ERROR_TIMEOUT)
        if result is None:
            self._ok("unknown circuit → no event")
        else:
            self._fail("unknown circuit → no event", f"unexpectedly got event: {result}")


def main():
    parser = argparse.ArgumentParser(
        description="Live MQTT end-to-end test for evok",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--broker", default="localhost",
        help="MQTT broker hostname or IP  [localhost]",
    )
    parser.add_argument("--port", default=1883, type=int, help="Broker port  [1883]")
    parser.add_argument(
        "--client-id", default="evok",
        help="client-id from /etc/evok/config.yaml  [evok]",
    )
    parser.add_argument(
        "--circuit", default="ro/1_01",
        help="output circuit to toggle, type/circuit  [ro/1_01]",
    )
    args = parser.parse_args()

    success = asyncio.run(
        MqttE2ETest(args.broker, args.port, args.client_id, args.circuit).run()
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

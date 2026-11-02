"""The response times of the REST and JSON API: reads of a DI and an AI, writes of a user LED.

    EVOK_HOST=192.168.1.2 python benchmark.py <name of the device>

The results are printed and written to <name>.csv. The requests are sent with the periods
from 0 to 0.2 s, more of them run at once with the short periods.
"""

import asyncio
import csv
import math
import os
import statistics
import sys
import time

import aiohttp

HOST = os.environ.get("EVOK_HOST", "127.0.0.1")
PORT = os.environ.get("EVOK_PORT", "8080")
TOKEN = os.environ.get("EVOK_TOKEN")  # the token of 'apis' in the configuration, if it is set
HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}

PERIODS = [0, 0.001, 0.002, 0.006, 0.01, 0.1, 0.2]
value = 1  # the value of the next write, the LED blinks


async def timed(results: list, request) -> None:
    start = time.monotonic()
    async with request as response:
        await response.text()
    results.append(time.monotonic() - start)


async def rest_get(session, results, dev_type):
    await timed(results, session.get(f"http://{HOST}:{PORT}/rest/{dev_type}/1_01"))


async def json_get(session, results, dev_type):
    await timed(results, session.get(f"http://{HOST}:{PORT}/json/{dev_type}/1_01"))


async def rest_set(session, results, dev_type):
    global value
    value = 1 - value
    url = f"http://{HOST}:{PORT}/rest/{dev_type}/1_01"
    await timed(results, session.post(url, data={"value": str(value)}))


async def json_set(session, results, dev_type):
    global value
    value = 1 - value
    url = f"http://{HOST}:{PORT}/json/{dev_type}/1_01"
    await timed(results, session.post(url, json={"value": value}))


async def measure(session, fce, period: float, repeat: int, dev_type: str) -> dict:
    results = []
    async with asyncio.TaskGroup() as group:
        for _ in range(repeat):
            group.create_task(fce(session, results, dev_type))
            await asyncio.sleep(period)
    print(end=".", flush=True)
    await asyncio.sleep(1)
    return {"fce": fce.__name__, "period": period, "repeat": repeat, "dev_type": dev_type, **statistics_of(results)}


def statistics_of(results: list) -> dict:
    """The times in ms"""
    times = [t * 1000 for t in results]
    average = sum(times) / len(times)
    return {
        "average": round(average, 3),
        "std_dev": round(math.sqrt(sum((t - average) ** 2 for t in times) / len(times)), 3),
        "min": round(min(times), 3),
        "max": round(max(times), 3),
        "median": round(statistics.median(times), 3),
    }


async def measure_all() -> list[dict]:
    cases = [(fce, dev_type) for dev_type in ("di", "ai") for fce in (rest_get, json_get)]
    cases += [(fce, "led") for fce in (rest_set, json_set)]
    results = []
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        for fce, dev_type in cases:
            for period in PERIODS:
                repeat = 100 if period < 0.1 else 30
                results.append(await measure(session, fce, period, repeat, dev_type))
    return results


def main():
    device = (sys.argv[1] if len(sys.argv) > 1 else "").replace(" ", "").replace("#", "") or "dev"
    print(f"Benchmark of {HOST}:{PORT} for '{device}' ", end="")
    results = asyncio.run(measure_all())
    print()
    for row in results:
        print(f"{row['fce']}:\t{row}")
    with open(f"{device}.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)


if __name__ == "__main__":
    main()

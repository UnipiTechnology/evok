import asyncio
import math
import statistics
import sys
import time

import aiohttp

host = '127.0.0.1'

request_value = True


async def rest_request_get(session: aiohttp.ClientSession, results, dev_type: str):
    url = f'http://{host}/rest/{dev_type}/1_01'
    start_stamp = time.time()
    async with session.get(url) as response:
        await response.text()
    diff = time.time() - start_stamp
    results.append(diff)


async def json_request_get(session: aiohttp.ClientSession, results, dev_type: str):
    url = f'http://{host}/json/{dev_type}/1_01'
    start_stamp = time.time()
    async with session.get(url) as response:
        await response.text()
    diff = time.time() - start_stamp
    results.append(diff)


async def rest_request_set(session: aiohttp.ClientSession, results, dev_type: str):
    global request_value
    url = f'http://{host}/rest/{dev_type}/1_01'
    data = {'value': str(1 if request_value else 0)}
    request_value = not request_value
    start_stamp = time.time()
    async with session.post(url, data=data) as response:
        await response.text()
    diff = time.time() - start_stamp
    results.append(diff)


async def json_request_set(session: aiohttp.ClientSession, results, dev_type: str):
    global request_value
    url = f'http://{host}/rest/{dev_type}/1_01'
    data = {'value': str(1 if request_value else 0)}
    request_value = not request_value
    start_stamp = time.time()
    async with session.post(url, data=data) as response:
        await response.text()
    diff = time.time() - start_stamp
    results.append(diff)


async def request(fce, period: float, repeat: int, dev_type: str) -> dict:
    results = []
    async with aiohttp.ClientSession() as session, asyncio.TaskGroup() as group:
        for _ in range(repeat):
            group.create_task(fce(session, results, dev_type))
            await asyncio.sleep(period)
    ret = {'fce': fce.__name__, 'period': period, 'repeat': repeat, 'dev_type': dev_type}
    ret.update(get_result(results))
    print(end='.', flush=True)
    await asyncio.sleep(1)
    return ret


def get_result(results: list) -> dict:
    avg = round(sum(results) / len(results) * 1000, 3)
    variance = sum([(((x * 1000) - avg) ** 2) for x in results]) / len(results)
    stddev = round(math.sqrt(variance), 3)
    min_value = round(min(results) * 1000, 3)
    max_value = round(max(results) * 1000, 3)
    median_value = round(statistics.median(results) * 1000, 3)

    return {'average': avg, 'std_dev': stddev, 'min': min_value, 'max': max_value, 'median': median_value}


async def main():
    device_id = sys.argv[1] if len(sys.argv) > 1 else 'dev'
    device_id = device_id.replace(' ', '').replace('#', '')
    if len(device_id) == 0:
        device_id = 'dev'
    print(f"Benchmark started for device: '{device_id}' #", end='.')
    results = []

    for dev_type in ['do', 'ao']:
        for fce in [rest_request_get, json_request_get, rest_request_set, json_request_set]:
            for period in [0, 0.001, 0.002, 0.006, 0.01, 0.1, 0.2]:
                repeat = 100 if period < 0.1 else 30
                results.append(await request(fce=fce, period=period, repeat=repeat, dev_type=dev_type))

    print("#")
    for data in results:
        print(f"{data['fce']}:\t{data}")

    await asyncio.to_thread(write_csv, f"./{device_id}.csv", results)


def write_csv(path: str, results: list):
    with open(path, 'w') as f:
        head = results[0].keys()
        f.write(','.join(head))
        f.write('\n')
        for line in results:
            for key in head:
                f.write(f"{line[key]},")
            f.write('\n')


asyncio.run(main())

import asyncio
import math
import statistics
import sys
import time
from asyncio import events, tasks

import aiohttp

host = '127.0.0.1'

request_value = True


class TaskGroup:
    """Asynchronous context manager for managing groups of tasks.

    Example use:

        async with asyncio.TaskGroup() as group:
            task1 = group.create_task(some_coroutine(...))
            task2 = group.create_task(other_coroutine(...))
        print("Both tasks have completed now.")

    All tasks are awaited when the context manager exits.

    Any exceptions other than `asyncio.CancelledError` raised within
    a task will cancel all remaining tasks and wait for them to exit.
    The exceptions are then combined and raised as an `ExceptionGroup`.
    """
    def __init__(self):
        self._entered = False
        self._exiting = False
        self._aborting = False
        self._loop = None
        self._parent_task = None
        self._parent_cancel_requested = False
        self._tasks = set()
        self._errors = []
        self._base_error = None
        self._on_completed_fut = None

    def __repr__(self):
        info = ['']
        if self._tasks:
            info.append(f'tasks={len(self._tasks)}')
        if self._errors:
            info.append(f'errors={len(self._errors)}')
        if self._aborting:
            info.append('cancelling')
        elif self._entered:
            info.append('entered')

        info_str = ' '.join(info)
        return f'<TaskGroup{info_str}>'

    async def __aenter__(self):
        if self._entered:
            raise RuntimeError(
                f"TaskGroup {self!r} has already been entered")
        if self._loop is None:
            self._loop = events.get_running_loop()
        self._parent_task = tasks.current_task(self._loop)
        if self._parent_task is None:
            raise RuntimeError(
                f'TaskGroup {self!r} cannot determine the parent task')
        self._entered = True

        return self

    async def __aexit__(self, et, exc, tb):
        self._exiting = True

        if (exc is not None and
                self._is_base_error(exc) and
                self._base_error is None):
            self._base_error = exc

        if et is not None and issubclass(et, Exception):
            propagate_cancellation_error = exc
        else:
            propagate_cancellation_error = None
        if self._parent_cancel_requested:
            # If this flag is set we *must* call uncancel().
            if self._parent_task.uncancel() == 0:
                # If there are no pending cancellations left,
                # don't propagate CancelledError.
                propagate_cancellation_error = None

        if et is not None:
            if not self._aborting:
                # Our parent task is being cancelled:
                #
                #    async with TaskGroup() as g:
                #        g.create_task(...)
                #        await ...  # <- CancelledError
                #
                # or there's an exception in "async with":
                #
                #    async with TaskGroup() as g:
                #        g.create_task(...)
                #        1 / 0
                #
                self._abort()

        # We use while-loop here because "self._on_completed_fut"
        # can be cancelled multiple times if our parent task
        # is being cancelled repeatedly (or even once, when
        # our own cancellation is already in progress)
        while self._tasks:
            if self._on_completed_fut is None:
                self._on_completed_fut = self._loop.create_future()

            try:
                await self._on_completed_fut
            except Exception as ex:
                if not self._aborting:
                    # Our parent task is being cancelled:
                    #
                    #    async def wrapper():
                    #        async with TaskGroup() as g:
                    #            g.create_task(foo)
                    #
                    # "wrapper" is being cancelled while "foo" is
                    # still running.
                    propagate_cancellation_error = ex
                    self._abort()

            self._on_completed_fut = None

        assert not self._tasks

        if self._base_error is not None:
            raise self._base_error

        # Propagate CancelledError if there is one, except if there
        # are other errors -- those have priority.
        if propagate_cancellation_error and not self._errors:
            raise propagate_cancellation_error

        if et is not None and not issubclass(et, Exception):
            self._errors.append(exc)

        if self._errors:
            # Exceptions are heavy objects that can have object
            # cycles (bad for GC); let's not keep a reference to
            # a bunch of them.
            try:
                me = BaseExceptionGroup('unhandled errors in a TaskGroup', self._errors)
                raise me from None
            finally:
                self._errors = None

    def create_task(self, coro, *, name=None, context=None):
        """Create a new task in this group and return it.

        Similar to `asyncio.create_task`.
        """
        if not self._entered:
            raise RuntimeError(f"TaskGroup {self!r} has not been entered")
        if self._exiting and not self._tasks:
            raise RuntimeError(f"TaskGroup {self!r} is finished")
        if self._aborting:
            raise RuntimeError(f"TaskGroup {self!r} is shutting down")
        if context is None:
            task = self._loop.create_task(coro)
        else:
            task = self._loop.create_task(coro, context=context)

        # optimization: Immediately call the done callback if the task is
        # already done (e.g. if the coro was able to complete eagerly),
        # and skip scheduling a done callback
        if task.done():
            self._on_task_done(task)
        else:
            self._tasks.add(task)
            task.add_done_callback(self._on_task_done)
        return task

    # Since Python 3.8 Tasks propagate all exceptions correctly,
    # except for KeyboardInterrupt and SystemExit which are
    # still considered special.

    def _is_base_error(self, exc: BaseException) -> bool:
        assert isinstance(exc, BaseException)
        return isinstance(exc, (SystemExit, KeyboardInterrupt))

    def _abort(self):
        self._aborting = True

        for t in self._tasks:
            if not t.done():
                t.cancel()

    def _on_task_done(self, task):
        self._tasks.discard(task)

        if self._on_completed_fut is not None and not self._tasks:
            if not self._on_completed_fut.done():
                self._on_completed_fut.set_result(True)

        if task.cancelled():
            return

        exc = task.exception()
        if exc is None:
            return

        self._errors.append(exc)
        if self._is_base_error(exc) and self._base_error is None:
            self._base_error = exc

        if self._parent_task.done():
            # Not sure if this case is possible, but we want to handle
            # it anyways.
            self._loop.call_exception_handler({
                'message': f'Task {task!r} has errored out but its parent '
                           f'task {self._parent_task} is already completed',
                'exception': exc,
                'task': task,
            })
            return

        if not self._aborting and not self._parent_cancel_requested:
            # If parent task *is not* being cancelled, it means that we want
            # to manually cancel it to abort whatever is being run right now
            # in the TaskGroup.  But we want to mark parent task as
            # "not cancelled" later in __aexit__.  Example situation that
            # we need to handle:
            #
            #    async def foo():
            #        try:
            #            async with TaskGroup() as g:
            #                g.create_task(crash_soon())
            #                await something  # <- this needs to be canceled
            #                                 #    by the TaskGroup, e.g.
            #                                 #    foo() needs to be cancelled
            #        except Exception:
            #            # Ignore any exceptions raised in the TaskGroup
            #            pass
            #        await something_else     # this line has to be called
            #                                 # after TaskGroup is finished.
            self._abort()
            self._parent_cancel_requested = True
            self._parent_task.cancel()


async def rest_request_get(session: aiohttp.ClientSession, results, dev_type: str):
    url = f'http://{host}/rest/{dev_type}/1_01'
    start_stamp = time.time()
    async with session.get(url) as response:
        await response.text()
    diff = time.time() - start_stamp
    results.append(diff)


async def json_request_get(session: aiohttp.ClientSession, results ,dev_type: str):
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
    async with aiohttp.ClientSession() as session:
        async with TaskGroup() as group:
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

    with open(f"./{device_id}.csv", 'w') as f:
        head = results[0].keys()
        f.write(','.join(head))
        f.write('\n')
        for line in results:
            for key in head:
                f.write(f"{line[key]},")
            f.write('\n')


loop = asyncio.get_event_loop()
loop.run_until_complete(main())

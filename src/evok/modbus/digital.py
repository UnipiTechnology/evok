from ..devices import DI, DO, LED, RO, Devices, to_bool, to_float
from .base import IODevice
from .client import Accessor, AccessorBit, AccessorU16, AccessorU32, Client
from .iomode import DIMode, WithDIMode
from .pwm import PwmFrequency


class BinaryOutput(IODevice):
    """Base of the outputs with a bit in a status register: RO, DO and LED

    The value is written to the coil, an output without a coil writes the bit of its holding register
    (read-modify-write under the lock of the unit), e.g. a unit which has no coils.

    A pulse is a sequence of the sequencer of blocks, set by the sequencer device of the output.
    """

    def __init__(self, circuit, client: Client, coil: int | None, reg, mask, major_group=0):
        super().__init__(circuit, client, major_group)
        self.coil = coil
        self.accessor = AccessorBit(reg, mask)
        self.value = None

    def full(self):
        return self._with_common(self._state())

    def _state(self) -> dict:
        """The state without the alias, the alias is the last item of full()"""
        return {
            "dev": self.devtype,
            "circuit": self.circuit,
            "value": self.value,
        }

    async def check_new_data(self):
        old_value = self.value
        self.value = self.accessor.read(self.client)
        return old_value != self.value

    async def set(self, value=None, alias=None):
        """Sets new on/off status"""
        if value is not None:
            await self._write_value(int(to_bool(value)))
        self.set_alias(alias)

    async def _write_value(self, value: int):
        """Write the value to the coil, or to the bit of the register of an output without a coil"""
        if self.coil is not None:
            await self.client.mb_client.write_single_coil(self.coil, value)
        else:
            await self.accessor.write_raw(self.client, value)


class DigitalOutput(BinaryOutput):
    devtype = DO

    def __init__(
        self,
        circuit,
        client: Client,
        coil,
        reg,
        mask,
        major_group=0,
        pwm: PwmFrequency | None = None,
        pwmdutyreg=None,
        modes=None,
    ):
        """pwm is the frequency shared by the outputs of the group, pwmdutyreg the duty register of this output"""
        super().__init__(circuit, client, coil, reg, mask, major_group)
        if pwm is not None and pwmdutyreg is None:
            raise ValueError(f"DO {circuit}: pwm requires pwmdutyreg")
        self.modes = modes if modes is not None else ["Simple"]
        self.pwm = pwm
        self.accessor_pwm_duty = AccessorU16(pwmdutyreg) if pwm is not None else Accessor(None)
        self.pwm_duty = None
        self.pwm_duty_val = None
        self.pwm_freq = None
        self.mode = None

    def _state(self):
        return dict(super()._state(), mode=self.mode, modes=self.modes, pwm_freq=self.pwm_freq, pwm_duty=self.pwm_duty)

    async def check_new_data(self):
        is_change = False
        if self.pwm is not None:
            self.pwm.update()
            old_pwm = (self.pwm_freq, self.pwm_duty)
            self.pwm_freq = self.pwm.freq
            self.pwm_duty_val = self.accessor_pwm_duty.read(self.client)
            self.pwm_duty = self.pwm.duty(self.pwm_duty_val)
            is_change = old_pwm != (self.pwm_freq, self.pwm_duty)
        # Mode field is for backward compatibility, will be deprecated soon
        self.mode = "PWM" if self.pwm_duty else "Simple"

        return await super().check_new_data() or is_change

    async def set(self, value=None, mode=None, pwm_freq=None, pwm_duty=None, alias=None):
        """Sets new on/off status or the PWM"""
        # parse before any write
        parsed_value = None if value is None else int(to_bool(value))

        if pwm_duty is not None:
            pwm_duty = to_float(pwm_duty)
            if not 0.0 <= pwm_duty <= 100.0:
                raise ValueError(f"DO {self.circuit}: pwm_duty {pwm_duty} is out of range <0..100>")

        if pwm_freq is not None:
            pwm_freq = to_float(pwm_freq)
            if pwm_freq <= 0:
                raise ValueError(f"DO {self.circuit}: pwm_freq {pwm_freq} must be positive")

        if self.pwm is None and (pwm_duty is not None or pwm_freq is not None):
            raise ValueError(f"DO {self.circuit}: PWM is not supported")

        if parsed_value is not None and pwm_duty is not None:
            # No conflict in this case
            if not ((pwm_duty == 100 and parsed_value == 1) or (pwm_duty == 0 and parsed_value == 0)):
                raise ValueError("Set value conflict: Cannot set both value and pwm_duty at once.")

        if pwm_freq is not None:
            # value or pwm_duty replaces the duty of this output
            await self.set_pwm_freq(pwm_freq, keep_duty=parsed_value is None and pwm_duty is None)

        # Set Binary value
        if parsed_value is not None:
            await self._write_value(parsed_value)
            if self.pwm_duty:
                self.pwm_duty = 0
                # Turn off PWM
                await self.accessor_pwm_duty.write(self.client, 0)

        # Set PWM Duty
        elif pwm_duty is not None:
            if self.value != 0:
                await self._write_value(0)
            await self.accessor_pwm_duty.write(self.client, self.pwm.duty_raw(pwm_duty))

        self.set_alias(alias)

    async def set_pwm_freq(self, freq: float, keep_duty=True):
        """Set the frequency shared by the group, keep the duty cycle of all its outputs,
        of this output only with keep_duty

        pwm_freq of the outputs is set by check_new_data() of the scan after the change, which sends
        all outputs of the group as changed; set here, the scan saw no change and sent no event.
        """
        await self.pwm.set(freq)
        for dev in Devices.by_name(DO, major_group=self.major_group):
            if dev.pwm is not self.pwm:
                continue
            if dev is self and not keep_duty:
                continue
            if dev.pwm_duty:
                raw = self.pwm.duty_raw(dev.pwm_duty)
                if raw != dev.pwm_duty_val:
                    await dev.accessor_pwm_duty.write(self.client, raw)
                    dev.pwm_duty_val = raw


class Relay(BinaryOutput):
    devtype = RO


class ULED(BinaryOutput):
    devtype = LED


class DigitalInput(WithDIMode, IODevice):
    devtype = DI

    def __init__(
        self,
        circuit,
        client: Client,
        reg,
        mask,
        regcounter=None,
        regdebounce=None,
        regmode=None,
        regtoggle=None,
        regpolarity=None,
        major_group=0,
        modes=None,
        ds_modes=None,
        counter_modes=None,
    ):
        super().__init__(circuit, client, major_group)
        self.dimode = DIMode(
            client, mask, regmode, regpolarity, regtoggle, modes, ds_modes, f"{self.devtype.upper()} {circuit}"
        )
        self.counter_modes = counter_modes if counter_modes is not None else ["Enabled", "Disabled"]
        self.counter_mode = "Enabled"
        self.accessor = AccessorBit(reg, mask)
        # the unit counts on, a written value (a reset) is not kept in the cache, the read shows the count
        self.accessor_counter = AccessorU32(regcounter, pin=False) if regcounter is not None else Accessor(None)
        self.accessor_debounce = AccessorU16(regdebounce) if regdebounce is not None else Accessor(None)
        self.value = None
        self.counter = None
        self.debounce = None
        self.scanned_state = None

    async def check_new_data(self):
        """Compare with the state of the previous scan, set() changes counter_mode and mode at once"""
        self.dimode.update()
        self.value = self.accessor.read(self.client)
        self.counter = self.read_counter()
        self.debounce = self.accessor_debounce.read(self.client)
        state = (self.value, self.counter, self.debounce, self.counter_mode, self.mode, self.ds_mode)
        changed = state != self.scanned_state
        self.scanned_state = state
        return changed

    def read_counter(self):
        return self.accessor_counter.read(self.client) if self.counter_mode == "Enabled" else 0

    def full(self):
        ret = {
            "dev": "di",
            "circuit": self.circuit,
            "value": self.value,
            "debounce": self.debounce,
            "counter_modes": self.counter_modes,
            "counter_mode": self.counter_mode,
            "counter": self.counter,
            "mode": self.mode,
            "modes": self.modes,
        }
        if self.mode == "DirectSwitch":
            ret["ds_mode"] = self.ds_mode
            ret["ds_modes"] = self.ds_modes
        self._with_common(ret)
        return ret

    async def set(self, debounce=None, mode=None, counter=None, counter_mode=None, ds_mode=None, alias=None):
        """All params are validated before the first write, a disabled counter cannot be written"""
        self.dimode.check(mode, ds_mode)
        if counter_mode is not None and counter_mode not in self.counter_modes:
            raise ValueError(f'DI {self.circuit}: unknown counter_mode "{counter_mode}"')
        if debounce is not None:
            debounce = self._register_value("debounce", debounce, self.accessor_debounce)
        if counter is not None:
            if (counter_mode or self.counter_mode) != "Enabled":
                raise ValueError(f"DI {self.circuit}: the counter is disabled")
            counter = self._register_value("counter", counter, self.accessor_counter)

        await self.dimode.set(mode, ds_mode)

        if counter_mode is not None and counter_mode != self.counter_mode:
            self.counter_mode = counter_mode
            self.counter = self.read_counter()

        if debounce is not None:
            await self.accessor_debounce.write(self.client, debounce)
        if counter is not None:
            await self.accessor_counter.write(self.client, counter)

        self.set_alias(alias)

    def _register_value(self, name, value, accessor: Accessor) -> int:
        """An integer in the range of the register, raise ValueError if the DI has no such register"""
        if accessor.index is None:
            raise ValueError(f"DI {self.circuit}: {name} is not supported")
        number = to_float(value)
        if not number.is_integer():
            raise ValueError(f"DI {self.circuit}: {name} {value} must be an integer")
        low, high = accessor.raw_range
        if not low <= number <= high:
            raise ValueError(f"DI {self.circuit}: {name} {value} is out of range <{low}..{high}>")
        return int(number)

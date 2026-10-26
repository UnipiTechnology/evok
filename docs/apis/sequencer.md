# Evok sequencer

The pulses and the sequences of the outputs (RO, DO, LED) are timed by Evok. Each output has its sequencer,
a device of the type `sequencer` with the circuit `<output type>_<output circuit>`, e.g. `do_1_01`, `ro_2_03`
or `led_1_02`. The output itself has only its value (and the PWM of a DO), the parameters `pulse_duration`,
`timeout` and the state `pending` of the outputs were replaced by the sequencer.

At most one pulse or sequence runs for an output, a new one replaces it. While it runs, a change of the output
itself (except its alias) is refused: REST, JSON and bulk with the status `409` (`SequenceRunning`), the WebSocket
with the same error, RPC with the code `-32002`; cancel the sequence by its sequencer first. When Evok stops,
it writes the final state of the running pulses and sequences which have one (`final`), an output is not left
in the state of a pulse; a sequence without `final` leaves the output in its state. After a crash of Evok
the output stays in its state.

## State

```json
{"dev": "sequencer", "circuit": "do_1_01", "output": {"dev": "do", "circuit": "1_01"},
 "running": true, "name": "pulse", "step": 0, "steps": 1}
```

- `running` - a pulse or a sequence is running, the former `pending` of the output
- `name` - `pulse` or `sequence`, `null` when nothing runs
- `step` / `steps` - the number of the done steps and of all steps of the running sequence, `null` when nothing runs
- `alias` - the alias of the sequencer, if it has one; it is set by `alias` in the POST as of other devices

An event of the sequencer is sent when a pulse or a sequence starts, does a step and ends, the changes
of the output are sent as its own events.

## Request

A POST sets one of a pulse (`value` with `pulse_duration`), a sequence (`steps`) or `cancel`, more of them
in one request are refused with `400`. The whole request is checked before any change:

- `value` without `pulse_duration` is refused, the value of the output is set by the output itself,
  `pulse_duration` without `value` too; `pulse_duration` must be greater than 0,
- `final` requires `steps`, `steps` is a list of 1 to 100 steps,
- the `delay` of a step must not be negative, a step and `final` must change the output, not contain `alias`.

A new pulse or sequence replaces the running one without writing its `final`. A new pulse replaces it after
its value is written: if the write fails, e.g. the unit is unavailable, the running one goes on and writes its end,
the output does not stay in the state of the old pulse. The RPC methods
`relay_set_for_time` and `output_set_for_time` start a pulse by the sequencer too.

## Pulse

`value` with `pulse_duration` in seconds sets the value of the output, after `pulse_duration` the opposite
value is written.

```bash title="Bash"
curl -X POST -d 'value=1&pulse_duration=2' http://127.0.0.1:8080/rest/sequencer/ro_1_01
```

## Sequence

`steps` is a list of the changes of the output, each one with an optional `delay` in seconds before it,
the other keys are the parameters of the output as in its POST. `final` are the parameters written when Evok
stops during the sequence. The parameters are checked by the schema of the output before the start,
at most 100 steps.

```bash title="Bash"
curl -X POST -H 'Content-Type: application/json' http://127.0.0.1:8080/json/sequencer/led_1_02 \
     -d '{"steps": [{"value": 1}, {"delay": 0.5, "value": 0}, {"delay": 0.5, "value": 1}], "final": {"value": 0}}'
```

## Cancel

`cancel` stops the running pulse or sequence without its final state, the output stays in its state.

```bash title="Bash"
curl -X POST -d 'cancel=1' http://127.0.0.1:8080/rest/sequencer/do_1_01
```

The sequencers are not in `/rest/all`, use `/rest/sequencer/all`.

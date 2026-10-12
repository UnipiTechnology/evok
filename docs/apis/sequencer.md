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
- `step` / `steps` - the number of the done steps and of all steps of the running sequence

An event of the sequencer is sent when a pulse or a sequence starts, does a step and ends, the changes
of the output are sent as its own events.

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

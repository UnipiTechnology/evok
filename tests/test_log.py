from evok.log import read_log_tail


def test_read_log_tail(tmp_path):
    log = tmp_path / 'evok.log'
    log.write_text(''.join(f'line {i}\n' for i in range(10)))
    assert read_log_tail(log, 3) == 'line 7\nline 8\nline 9\n'
    assert read_log_tail(log, 100) == log.read_text()


def test_read_log_tail_invalid_utf8(tmp_path):
    log = tmp_path / 'evok.log'
    log.write_bytes(b'ok\n\xff\n')
    assert read_log_tail(log, 2) == 'ok\n�\n'

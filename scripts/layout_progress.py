"""Phase timing on stderr; stdout remains available for CLI results."""

from contextlib import contextmanager
import sys
import time


def progress(message):
    print('layout: ' + message, file=sys.stderr, flush=True)


@contextmanager
def phase(name):
    started = time.monotonic()
    progress(name + ': RUNNING')
    try:
        yield
    except Exception as error:
        progress(f'{name}: FAIL ({time.monotonic() - started:.3f}s; {type(error).__name__}: {error})')
        raise
    else:
        progress(f'{name}: DONE ({time.monotonic() - started:.3f}s)')

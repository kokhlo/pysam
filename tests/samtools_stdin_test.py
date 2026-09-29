import os
import subprocess
import sys
import time

import pytest

import pysam
import pysam.samtools  # noqa: F401  (ensures the dispatcher is importable)

from TestUtils import BAM_DATADIR

# Dispatching samtools in-process inherits the caller's stdin.  When that is
# a terminal the child waits for input that never arrives, so the call hangs
# and cannot be interrupted.  These tests run the dispatch in a child process
# with a controlled stdin and fail if it fails to return.
TIMEOUT = 60


def run_dispatch_with_stdin(code, stdin):
    '''run *code* in a child process with *stdin*, return (elapsed, returncode).'''
    start = time.time()
    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", code],
            stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except TypeError:
        # stdin=DEVNULL is a sentinel on some versions, use the real device
        proc = subprocess.Popen(
            [sys.executable, "-c", code],
            stdin=open(os.devnull), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
    try:
        proc.communicate(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise AssertionError(
            "dispatch did not return within %i seconds with stdin=%r" %
            (TIMEOUT, stdin))
    return time.time() - start, proc.returncode


@pytest.mark.skipif(not hasattr(os, "openpty"),
                    reason="requires a pseudo terminal")
class TestStdinDoesNotBlock:
    '''samtools and bcftools must not wait forever for stdin.'''

    def test_stdin_from_terminal_returns(self):
        '''a terminal as stdin must not make the dispatch hang'''
        master, slave = os.openpty()
        try:
            code = ("import pysam\n"
                    "try:\n"
                    "    pysam.samtools.view('-')\n"
                    "except pysam.SamtoolsError:\n"
                    "    pass\n")
            elapsed, returncode = run_dispatch_with_stdin(code, slave)
        finally:
            os.close(master)
            os.close(slave)
        assert returncode == 0
        assert elapsed < TIMEOUT

    def test_stdin_from_pipe_still_reads(self):
        '''a pipe carrying real input must keep being read'''
        sam = os.path.join(BAM_DATADIR, "ex_spliced.sam")
        with open(sam, "rb") as inf:
            data = inf.read()

        code = ("import sys, pysam\n"
                "lines = pysam.samtools.view('-').splitlines()\n"
                "sys.stdout.write(str(len(lines)))\n")
        start = time.time()
        proc = subprocess.Popen([sys.executable, "-c", code],
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        try:
            out, err = proc.communicate(input=data, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise AssertionError("dispatch did not return within %i seconds" %
                                 TIMEOUT)
        assert proc.returncode == 0, err.decode()
        assert int(out) == 102, "streamed input was not passed through"
        assert time.time() - start < TIMEOUT

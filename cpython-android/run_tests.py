"""Run Python's test suite against this distribution.

    $ ./python/build/run_tests.py [regrtest arguments]

This is the file ``PYTHON.json``'s ``run_tests`` names. It is modelled on
upstream's ``cpython-unix/run_tests-13.py`` and, like it, only re-executes the
interpreter against the ``test`` package the distribution ships.

One deliberate difference: upstream passes ``--slow-ci``, which is the profile
its own CI wants. This distribution runs on a device, where that profile takes
hours and a good deal of it is unsupported on Android anyway, so the default is
a plain run and the caller passes whatever profile they actually want.

Only the standard library is used, because a device is not guaranteed to have
anything else.
"""

import os
import sys


def main(regrtest_args):
    args = [sys.executable, "-m", "test"]
    args.extend(regrtest_args)
    print(" ".join(args))

    os.execv(sys.executable, args)


if __name__ == "__main__":
    main(sys.argv[1:])

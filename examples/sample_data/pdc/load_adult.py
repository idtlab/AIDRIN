"""Load the numeric columns of the adult sample dataset into a running PDC server.

PDC is a server-backed object store, so unlike the other sample formats there is
no file to ship: this script writes the data into PDC, and ``adult.pdc`` (next to
this script) is the descriptor AIDRIN reads it back through.

Requires PDCpy (https://github.com/hpc-io/PDCpy) and a running ``pdc_server``.
Run it with the same ``PDC_TMPDIR`` the server was started with::

    PDC_TMPDIR=/path/to/pdc_tmp python examples/sample_data/pdc/load_adult.py
    PDC_TMPDIR=/path/to/pdc_tmp aidrin data-quality examples/sample_data/pdc/adult.pdc

Each numeric column becomes one 1D object named ``adult_<column>`` in the
container ``aidrin_adult``. Text columns are skipped: PDC objects hold fixed-width
numbers only. Objects that already exist are left alone, so the script can be
run again safely.
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = os.path.join(HERE, "..", "csv", "adult.csv")
CONTAINER = "aidrin_adult"
PREFIX = "adult_"


def object_name(column: str) -> str:
    return PREFIX + column.replace(".", "_")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--csv", default=DEFAULT_CSV, help="CSV file to load (default: the bundled adult.csv)")
    args = parser.parse_args(argv)

    try:
        import pdc
    except ImportError:
        sys.exit("PDCpy is not installed. See https://github.com/hpc-io/PDCpy.")

    from aidrin.file_handling.readers.pdc_reader import PDCError, route_logs_to_stderr, check_server

    tmpdir = os.environ.get("PDC_TMPDIR")
    if not tmpdir:
        sys.exit("Set PDC_TMPDIR to the directory the PDC server was started with.")
    try:
        check_server(tmpdir)
    except PDCError as exc:
        sys.exit(str(exc))

    df = pd.read_csv(args.csv)
    numeric = df.select_dtypes(include="number")
    # PDC logs to stdout; its "not found" errors from the existence checks below are expected.
    route_logs_to_stderr(pdc)
    pdc.init()
    try:
        container = pdc.Container.get(CONTAINER)
    except pdc.PDCError:
        container = pdc.Container(CONTAINER)

    for column in numeric.columns:
        name = object_name(column)
        try:
            pdc.Object.get(name)
            print(f"{name}: already in PDC, skipped")
            continue
        except pdc.PDCError:
            pass
        container.object_from_array(name, np.ascontiguousarray(numeric[column].to_numpy()))
        print(f"{name}: wrote {len(numeric)} values ({numeric[column].dtype})")

    skipped = [c for c in df.columns if c not in numeric.columns]
    print(f"Skipped text columns: {', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
import argparse
import os
import shutil
import sys
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description='Filter an OSM PBF for the default OSRM car profile while retaining tags and references.')
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    source, output = args.input.resolve(), args.output.resolve()
    if not source.is_file():
        parser.error('input PBF does not exist')
    if source == output:
        parser.error('input and output must be different files')
    if not output.parent.is_dir():
        parser.error('output parent does not exist; check the mounted volume')
    if output.exists():
        parser.error('output already exists; existing data was preserved')
    executable = shutil.which('osmium')
    if not executable:
        parser.error('osmium CLI is missing from PATH')
    command = [executable, 'tags-filter', str(source), 'nw/highway', 'w/route', 'r/type=restriction*', 'r/type=route', 'r/type=maneuver', 'r/type=manoeuvre', 'nw/amenity=fuel', '--output', str(output)]
    os.execv(executable, command)


if __name__ == '__main__':
    try:
        main()
    except OSError as exc:
        sys.exit(f'OSM filtering failed: {exc}')

#!/usr/bin/env python3
import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GRAPH = ROOT / 'local' / 'osrm-native'
DOCKER_GRAPH = (ROOT / 'local' / 'osrm').resolve()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Prepare or run a separate native OSRM MLD graph, one stage at a time.')
    parser.add_argument('stage', choices=('prepare', 'extract', 'partition', 'customize', 'serve'))
    parser.add_argument('--input', type=Path, help='Existing PBF, required only for prepare')
    parser.add_argument('--link-input', action='store_true', help='Hard-link input instead of copying; prepare only, same filesystem')
    parser.add_argument('--profile', type=Path, help='Installed OSRM car.lua, required for extract')
    parser.add_argument('--data-dir', type=Path, default=DEFAULT_GRAPH, help='Separate native graph directory; default local/osrm-native')
    args = parser.parse_args(argv)
    if args.profile and args.stage != 'extract':
        parser.error('--profile is only valid for extract')
    graph = args.data_dir.resolve()
    if graph == DOCKER_GRAPH or graph in DOCKER_GRAPH.parents or DOCKER_GRAPH in graph.parents:
        parser.error('native and Docker graph directories must be separate')
    if graph != DEFAULT_GRAPH.resolve() and not graph.parent.is_dir():
        parser.error('graph directory parent does not exist; check the mounted volume')
    pbf = graph / 'region.osm.pbf'
    data = graph / 'region.osrm'
    if args.stage == 'prepare':
        if not args.input or not args.input.is_file():
            parser.error('prepare requires an existing --input PBF')
        graph.mkdir(parents=graph == DEFAULT_GRAPH.resolve(), exist_ok=True)
        if any(graph.iterdir()):
            parser.error('native graph directory must be empty; existing files were preserved')
        if args.link_input:
            os.link(args.input.resolve(), pbf, follow_symlinks=False)
        else:
            with args.input.open('rb') as source, pbf.open('xb') as target:
                shutil.copyfileobj(source, target)
        return
    if args.input or args.link_input:
        parser.error('--input and --link-input are only valid for prepare')
    executable = shutil.which('osrm-routed' if args.stage == 'serve' else f'osrm-{args.stage}')
    if not executable:
        parser.error(f'OSRM executable for {args.stage} is missing from PATH')
    if args.stage == 'extract':
        if not pbf.is_file() or not args.profile or not args.profile.is_file():
            parser.error('extract requires prepared PBF and an existing --profile car.lua')
        if any(graph.glob('region.osrm*')):
            parser.error('native graph already exists; use an empty native directory for a new graph')
        command = [executable, '--threads', '1', '-p', str(args.profile), str(pbf)]
    else:
        if not Path(f'{data}.ebg').is_file():
            parser.error('native graph is missing; complete extract first')
        if args.stage in ('customize', 'serve') and not Path(f'{data}.partition').is_file():
            parser.error('partition data is missing; complete partition first')
        if args.stage == 'serve' and not Path(f'{data}.cell_metrics').is_file():
            parser.error('customized data is missing; complete customize first')
        command = [executable, '--threads', '1']
        command.append(str(data))
        if args.stage == 'serve':
            command += ['--ip', '127.0.0.1', '--port', '5050', '--algorithm', 'mld', '--mmap', '--disable-feature-dataset', 'ROUTE_STEPS']
    os.execv(executable, command)


if __name__ == '__main__':
    try:
        main()
    except OSError as exc:
        sys.exit(f'OSRM setup failed: {exc}')

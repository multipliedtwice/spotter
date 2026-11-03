from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.raw_operator_evidence import RACETRAC_SOURCE


class Command(OperatorCommand):
    help = 'Resolve RaceTrac and RaceWay stations from local published locator records.'
    source_url = RACETRAC_SOURCE
    namespaces = {'RACETRAC': 'RACETRAC', 'RACEWAY': 'RACEWAY'}
    datasource_name = 'RaceTrac'
    unique_operator_points = True
    wrap_raw_records = True

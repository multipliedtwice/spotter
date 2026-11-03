from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.raw_operator_evidence import THORNTONS_SOURCE


class Command(OperatorCommand):
    help = 'Resolve Thorntons stations from local published locator records.'
    source_url = THORNTONS_SOURCE
    namespaces = {'THORNTONS': 'THORNTONS'}
    datasource_name = 'Thorntons'
    unique_operator_points = True
    wrap_raw_records = True

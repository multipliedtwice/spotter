from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.raw_operator_evidence import SUNSTOP_SOURCE


class Command(OperatorCommand):
    help = 'Resolve SunStop stations from local locator records.'
    source_url = SUNSTOP_SOURCE
    namespaces = {'SUNSTOP': 'SUNSTOP'}
    datasource_name = 'SunStop'
    unique_operator_points = True
    wrap_raw_records = True

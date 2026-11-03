from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.raw_operator_evidence import RUTTERS_SOURCE


class Command(OperatorCommand):
    help = "Resolve Rutter's stations from local published locator records."
    source_url = RUTTERS_SOURCE
    namespaces = {'RUTTERS': 'RUTTERS'}
    datasource_name = "Rutter's"
    unique_operator_points = True
    wrap_raw_records = True

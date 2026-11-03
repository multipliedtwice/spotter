from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.raw_operator_evidence import TOOT_SOURCE


class Command(OperatorCommand):
    help = "Resolve Toot'n Totum stations from local locator records."
    source_url = TOOT_SOURCE
    namespaces = {'TOOTN TOTUM': 'TOOTN TOTUM'}
    datasource_name = "Toot'n Totum"
    unique_operator_points = True
    wrap_raw_records = True

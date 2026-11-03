from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.operator_evidence import YESWAY_SOURCE


class Command(OperatorCommand):
    help = 'Resolve Yesway and Allsup stations from a local operator asset.'
    source_url = YESWAY_SOURCE
    namespaces = {'YESWAY': 'YESWAY', 'ALLSUPS': 'ALLSUPS'}
    datasource_name = 'Yesway'
    wrap_raw_records = True

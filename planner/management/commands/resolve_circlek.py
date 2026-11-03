from planner.management.commands.resolve_kwiktrip import Command as OperatorCommand
from planner.operator_evidence import CIRCLEK_SOURCE


class Command(OperatorCommand):
    help = 'Resolve Circle K stations from local operator API records.'
    source_url = CIRCLEK_SOURCE
    namespaces = {'CIRCLE K': 'CIRCLE K', 'CIRCLEK': 'CIRCLE K'}
    datasource_name = 'Circle K'

"""Daily 'should I sell?' check for the stocks you currently hold.

A thin CLI over scan_today.check_positions, so the SELL verdict here is always the
one the backtested system uses: the production strategy, its 'widest' catastrophe
stop, and its 200-day-MA exit. (It used to run its own copy with the 'tightest' stop
and a chandelier exit the production strategy does not have, so it could say SELL
while scan_today.py said HOLD for the same position.)

CLI:  python scan_sell_today.py [positions.csv]
"""

import sys
from datetime import date

from scan_today import POSITIONS_CSV, print_sell_check, production_algorithm


def _cli():
    path = sys.argv[1] if len(sys.argv) > 1 else POSITIONS_CSV
    print(date.today().strftime("%Y-%m-%d"), flush=True)
    print_sell_check(production_algorithm(), path)


if __name__ == "__main__":
    _cli()

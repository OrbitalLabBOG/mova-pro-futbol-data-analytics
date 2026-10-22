"""Account-owned state for read-only R2 reconciliation; sale quotes are market data."""
from copy import deepcopy


def account_owned_state(state):
    body = deepcopy(state)
    body.pop('observed_at', None)
    for pick in body['picks']:
        pick.pop('selling_price', None)
    return body

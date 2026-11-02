"""Maintained Decimal valuation arithmetic; forecasts remain caller assumptions.

Inputs are finite decimal strings, integers or Decimal, never binary floats/bools.
Exact rational accumulation protects cancellation; nonterminating outputs use an
owned 80-significant-digit HALF_EVEN context. No global context is changed.
"""
from decimal import (Context, Decimal, DecimalException, localcontext, ROUND_HALF_EVEN,
                     InvalidOperation, DivisionByZero, Overflow)
from fractions import Fraction

VERSION = '2026-10-31-valuation-1'
NUMERIC_POLICY = {
    'precision': 80, 'rounding': 'ROUND_HALF_EVEN',
    'max_input_significant_digits': 80, 'max_input_adjusted_exponent': 400,
    'max_vector_items': 10000, 'max_discount_periods': 1000,
    'max_rational_bits': 32768,
    'serialization': 'Decimal or finite decimal strings; never float',
}


class CalculationError(ValueError):
    """A fixed-code input/domain failure; values are not echoed."""


def require(condition, code):
    if not condition:
        raise CalculationError(code)


def d(value):
    require(type(value) in (str, int, Decimal), 'DECIMAL_INPUT_TYPE')
    if isinstance(value, str):
        require(0 < len(value) <= 8192, 'DECIMAL_INPUT_SIZE')
    try:
        result = value if isinstance(value, Decimal) else Decimal(value)
    except (DecimalException, ValueError, OverflowError):
        raise CalculationError('DECIMAL_INPUT_INVALID') from None
    require(result.is_finite(), 'DECIMAL_INPUT_NONFINITE')
    if not result:
        return Decimal(0)
    digits = result.as_tuple().digits
    significant = len(digits)
    while significant > 1 and digits[significant - 1] == 0:
        significant -= 1
    require(significant <= 80 and abs(result.adjusted()) <= 400, 'DECIMAL_INPUT_DOMAIN')
    return result


def rational(value):
    return Fraction(d(value))


def bounded(value):
    require(value.numerator.bit_length() <= 32768 and value.denominator.bit_length() <= 32768,
            'RATIONAL_RESOURCE_BOUND')
    return value


def decimal_result(value):
    value = bounded(value)
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        twos += 1
        denominator //= 2
    while denominator % 5 == 0:
        fives += 1
        denominator //= 5
    if denominator == 1:
        scale = max(twos, fives)
        coefficient = value.numerator * 2 ** (scale - twos) * 5 ** (scale - fives)
        # Decimal(int) and Decimal(tuple) are exact and ignore ambient precision.
        raw = Decimal(coefficient).as_tuple()
        return Decimal((raw.sign, raw.digits, -scale))
    with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN, Emax=999999,
                              Emin=-999999, traps=[InvalidOperation, DivisionByZero, Overflow])):
        result = Decimal(value.numerator) / Decimal(value.denominator)
    require(result.is_finite(), 'DECIMAL_RESULT_NONFINITE')
    return result


def vector(values, maximum=10000):
    require(isinstance(values, (list, tuple)), 'VECTOR_INPUT_TYPE')
    require(len(values) <= maximum, 'VECTOR_RESOURCE_BOUND')
    return [rational(v) for v in values]


def _pv(cashflows, rate):
    require(rate > -1, 'DISCOUNT_RATE_DOMAIN')
    require(len(cashflows) <= 1000, 'DISCOUNT_PERIOD_BOUND')
    discount, power, result = bounded(1 / (1 + rate)), Fraction(1), Fraction(0)
    for value in cashflows:
        power = bounded(power * discount)
        result = bounded(result + value * power)
    return result


def pv(cashflows, rate):
    return decimal_result(_pv(vector(cashflows, 1000), rational(rate)))


def gross_debt_wacc(market_equity, gross_financial_debt, cost_equity, pretax_cost_debt, tax_rate):
    equity, debt, ke, kd, tax = map(rational, (market_equity, gross_financial_debt,
                                             cost_equity, pretax_cost_debt, tax_rate))
    require(equity > 0 and debt >= 0 and ke >= 0 and kd >= 0 and 0 <= tax <= 1, 'WACC_DOMAIN')
    ew, dw = equity / (equity + debt), debt / (equity + debt)
    return {'equity_weight': decimal_result(ew), 'debt_weight': decimal_result(dw),
            'wacc': decimal_result(ke * ew + kd * (1 - tax) * dw)}


def terminal_fcff(next_nopat, growth, roic, wacc):
    nopat, growth, roic, wacc = map(rational, (next_nopat, growth, roic, wacc))
    require(0 <= growth < wacc and roic > growth and nopat >= 0, 'TERMINAL_FCFF_DOMAIN')
    reinvestment = nopat * growth / roic
    fcff = nopat - reinvestment
    return {'reinvestment': decimal_result(reinvestment), 'fcff': decimal_result(fcff),
            'terminal_ev': decimal_result(fcff / (wacc - growth))}


def equity_value(fcff, terminal_ev, rate, current_net_debt, shares,
                 current_nonoperating_assets=0, realization_cashflows=None):
    flows = vector(fcff, 1000)
    count = rational(shares)
    require(bool(flows) and count > 0, 'EQUITY_INPUT_DOMAIN')
    realizations = [Fraction(0)] * len(flows) if realization_cashflows is None else vector(realization_cashflows, 1000)
    require(len(realizations) == len(flows), 'REALIZATION_PERIOD_MISMATCH')
    discount_rate = rational(rate)
    enterprise = _pv(flows, discount_rate) + _pv([Fraction(0)] * (len(flows) - 1) + [rational(terminal_ev)], discount_rate)
    nonoperating = rational(current_nonoperating_assets) + _pv(realizations, discount_rate)
    equity = enterprise - rational(current_net_debt) + nonoperating
    return {'enterprise_pv': decimal_result(enterprise), 'nonoperating_pv': decimal_result(nonoperating),
            'equity_pv': decimal_result(equity), 'per_share': decimal_result(equity / count)}


def expected_wealth(outcomes, probabilities):
    values, weights = vector(outcomes), vector(probabilities)
    require(len(values) == len(weights) and bool(weights), 'PROBABILITY_ALIGNMENT')
    require(all(w >= 0 for w in weights) and abs(sum(weights) - 1) <= Fraction(1, 10**12),
            'PROBABILITY_MASS_DOMAIN')
    return decimal_result(sum((w * v for w, v in zip(weights, values)), Fraction(0)))

"""Small corrected numeric operators, separate from the frozen legacy copy.

These functions do not infer forecasts or fetch data. Return observations and
weights retain caller conventions; no silent weight normalization occurs.
"""
from decimal import (Context, Decimal, DivisionByZero, Inexact, InvalidOperation,
                     Overflow, ROUND_HALF_EVEN, localcontext)
from fractions import Fraction
import math

VERSION = 'paths-numeric-corrections-v1'
DECIMAL_PRECISION = 100
MAX_RESETS = 100_000
MAX_WEIGHTED_ROWS = 10_000
_DECIMAL_CONTEXT = Context(prec=DECIMAL_PRECISION, rounding=ROUND_HALF_EVEN,
                           Emin=-999999, Emax=999999, capitals=1, clamp=0,
                           traps=[InvalidOperation, DivisionByZero, Overflow])


class ArithmeticDomainError(ValueError):
    def __init__(self, code, **details):
        super().__init__(code)
        self.code, self.details = code, details


def _decimal(value):
    if isinstance(value, str) and len(value) > 1200:
        raise ArithmeticDomainError('NUMERIC_INPUT_SIZE_LIMIT')
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (ValueError, InvalidOperation):
        raise ArithmeticDomainError('FINITE_NUMBER_REQUIRED') from None
    if not result.is_finite():
        raise ArithmeticDomainError('FINITE_NUMBER_REQUIRED')
    if len(result.as_tuple().digits) > 1000 or abs(result.adjusted()) > 10000:
        raise ArithmeticDomainError('NUMERIC_INPUT_MAGNITUDE_LIMIT')
    return result


def _float(value, *, label):
    result = float(value)
    if not math.isfinite(result):
        raise ArithmeticDomainError('FLOAT_REPRESENTATION_OVERFLOW', field=label)
    if value and result == 0:
        raise ArithmeticDomainError('FLOAT_REPRESENTATION_UNDERFLOW', field=label,
                                    positive_decimal=str(value))
    return result


def analyze_returns(returns, years=None):
    """Compound with Decimal100, rejecting unrepresentable float-path output.

Decimal100 uses an owned half-even context, independent of caller rounding,
precision and traps. It is bounded high precision, not an exact-real product guarantee.
``decimal_rounded`` reports inexact decimal arithmetic. A positive result too
small for the legacy float output contract raises a domain error, rather than
claiming actual ruin. Real -100% loss remains absorbing.
"""
    values = []
    for value in returns:
        if len(values) >= MAX_RESETS:
            raise ArithmeticDomainError('RESET_BUDGET_EXCEEDED')
        value = _decimal(value)
        if value < -1:
            raise ArithmeticDomainError('RETURN_BELOW_MINUS_ONE')
        values.append(value)
    if not values:
        raise ArithmeticDomainError('NONEMPTY_RETURNS_REQUIRED')
    duration = None if years is None else _decimal(years)
    if duration is not None and duration <= 0:
        raise ArithmeticDomainError('POSITIVE_YEARS_REQUIRED')
    with localcontext(_DECIMAL_CONTEXT) as context:
        context.clear_flags()
        wealth, peak, drawdown = Decimal(1), Decimal(1), Decimal(0)
        path = [1.]
        for value in values:
            wealth *= 1 + value
            path.append(_float(wealth, label='wealth_path'))
            peak = max(peak, wealth)
            drawdown = min(drawdown, wealth / peak - 1)
        terminal = _float(wealth, label='terminal_wealth')
        total_return = _float(wealth - 1, label='total_return')
        dd = _float(drawdown, label='max_drawdown')
        if wealth:
            log_wealth = float(wealth.ln())
            cagr = (float((wealth.ln() / duration).exp() - 1)
                    if duration is not None else None)
        else:
            log_wealth, cagr = None, (-1. if duration is not None else None)
        if cagr is not None and not math.isfinite(cagr):
            raise ArithmeticDomainError('CAGR_REPRESENTATION_OVERFLOW')
        return {'operator_version': VERSION, 'terminal_wealth': terminal,
                'terminal_wealth_decimal': str(wealth), 'total_return': total_return,
                'log_wealth': log_wealth, 'log_wealth_is_negative_infinity': wealth == 0,
                'cagr': cagr, 'max_drawdown': dd, 'wealth_path': path,
                'reset_periods': len(values), 'decimal_precision': DECIMAL_PRECISION,
                'decimal_rounded': bool(context.flags[Inexact])}


def _fraction(value):
    return Fraction(_decimal(value))


def _bounded_vector(values, label):
    """Capture at most10,000 entries; consume one extra only to detect overflow."""
    result = []
    try:
        iterator = iter(values)
    except TypeError:
        raise ArithmeticDomainError('ITERABLE_VECTOR_REQUIRED', vector=label) from None
    for value in iterator:
        if len(result) == MAX_WEIGHTED_ROWS:
            raise ArithmeticDomainError('WEIGHTED_VECTOR_BUDGET_EXCEEDED',
                                        vector=label, limit=MAX_WEIGHTED_ROWS)
        result.append(value)
    return result


def _weighted(values, weights):
    values = _bounded_vector(values, 'values')
    weights = _bounded_vector(weights, 'weights')
    if not values or len(values) != len(weights):
        raise ArithmeticDomainError('ALIGNED_NONEMPTY_VALUES_WEIGHTS_REQUIRED')
    pairs = [(_fraction(v), _fraction(w)) for v, w in zip(values, weights)]
    if any(w < 0 for _, w in pairs):
        raise ArithmeticDomainError('NONNEGATIVE_WEIGHTS_REQUIRED')
    # Retain the inherited validation tolerance; do not renormalize the CDF.
    if abs(sum(w for _, w in pairs) - 1) > Fraction('1e-10'):
        raise ArithmeticDomainError('WEIGHTS_MUST_SUM_TO_ONE')
    return sorted((v, w) for v, w in pairs if w > 0)


def weighted_quantile(values, weights, probability):
    """Exact cumulative-mass left inverse; q=0 selects minimum support.

Both vectors are limited to10,000 rows before rational conversion/sorting.
The same inherited approximate weight-sum admission is retained. Finite decimal
round-trip inputs are represented as rational values for all mass comparisons.
"""
    pairs = _weighted(values, weights)
    probability = _fraction(probability)
    if not 0 <= probability <= 1:
        raise ArithmeticDomainError('QUANTILE_OUTSIDE_ZERO_ONE')
    mass = Fraction(0)
    for value, weight in pairs:
        mass += weight
        if mass >= probability:
            return _float(value, label='quantile')
    return _float(pairs[-1][0], label='quantile')


def lower_tail_mean(values, weights, tail_mass=.05):
    """Integrate partial mass with zero weights skipped and <=10,000 input rows."""
    pairs = _weighted(values, weights)
    tail = _fraction(tail_mass)
    if not 0 < tail <= 1:
        raise ArithmeticDomainError('TAIL_MASS_OUTSIDE_ZERO_ONE')
    remaining, total = tail, Fraction(0)
    for value, weight in pairs:
        take = min(remaining, weight)
        total += take * value
        remaining -= take
        if remaining == 0:
            break
    return _float(total / tail, label='tail_mean')

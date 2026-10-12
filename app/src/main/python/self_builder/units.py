"""
Self-Builder - unit table
=========================
A small, closed table of common measurement units (length, mass, volume,
time, temperature, data size, area, speed) with the Persian and Latin names
people actually type. It is domain data, not conversation logic: it lets the
"unit_conversion" archetype build a correct converter between two known
units without the user having to state the factor.

Every unit has `to_base(value) = value * factor + offset` for its dimension's
base unit, so a conversion A -> B is `value * scale + shift` with

    scale = factor_A / factor_B
    shift = (offset_A - offset_B) / factor_B

Units that are NOT in this table can still be converted when the user states
the factor ("هر قدم ۰٫۷۵ متر است"); the table is then only used to
cross-check the factor when both units are known.

Data units are binary (1 KB = 1024 B), stated in the unit's description.
"""

from fractions import Fraction

from . import fa_text
from .errors import SpecError

# id: dimension, factor, offset, persian names, latin names, display
_RAW = {
    # --- length (base: metre)
    "m": ("length", 1.0, 0.0, ["متر"], ["m", "meter", "meters", "metre", "metres"], "متر"),
    "km": ("length", 1000.0, 0.0, ["کیلومتر", "کیلو متر"], ["km", "kilometer", "kilometers", "kilometre", "kilometres"], "کیلومتر"),
    "cm": ("length", 0.01, 0.0, ["سانتی متر", "سانتیمتر"], ["cm", "centimeter", "centimeters"], "سانتی‌متر"),
    "mm": ("length", 0.001, 0.0, ["میلی متر", "میلیمتر"], ["mm", "millimeter", "millimeters"], "میلی‌متر"),
    "mi": ("length", 1609.344, 0.0, ["مایل"], ["mi", "mile", "miles"], "مایل"),
    "yd": ("length", 0.9144, 0.0, ["یارد"], ["yd", "yard", "yards"], "یارد"),
    "ft": ("length", 0.3048, 0.0, ["فوت", "پا"], ["ft", "foot", "feet"], "فوت"),
    "in": ("length", 0.0254, 0.0, ["اینچ"], ["inch", "inches"], "اینچ"),
    "nmi": ("length", 1852.0, 0.0, ["مایل دریایی"], ["nmi"], "مایل دریایی"),
    # --- mass (base: kilogram)
    "kg": ("mass", 1.0, 0.0, ["کیلوگرم", "کیلو گرم", "کیلو"], ["kg", "kilogram", "kilograms"], "کیلوگرم"),
    "g": ("mass", 0.001, 0.0, ["گرم"], ["gram", "grams"], "گرم"),
    "mg": ("mass", 1e-6, 0.0, ["میلی گرم", "میلیگرم"], ["mg", "milligram"], "میلی‌گرم"),
    "t": ("mass", 1000.0, 0.0, ["تن"], ["ton", "tons", "tonne"], "تن"),
    "lb": ("mass", 0.45359237, 0.0, ["پوند"], ["lb", "lbs", "pound", "pounds"], "پوند"),
    "oz": ("mass", 0.028349523125, 0.0, ["اونس"], ["oz", "ounce", "ounces"], "اونس"),
    # --- volume (base: litre)
    "l": ("volume", 1.0, 0.0, ["لیتر"], ["liter", "liters", "litre", "litres"], "لیتر"),
    "ml": ("volume", 0.001, 0.0, ["میلی لیتر", "میلیلیتر"], ["ml", "milliliter", "milliliters"], "میلی‌لیتر"),
    "gal": ("volume", 3.785411784, 0.0, ["گالن"], ["gal", "gallon", "gallons"], "گالن"),
    "m3": ("volume", 1000.0, 0.0, ["متر مکعب"], ["m3"], "متر مکعب"),
    # --- time (base: second)
    "s": ("time", 1.0, 0.0, ["ثانیه"], ["sec", "second", "seconds"], "ثانیه"),
    "min": ("time", 60.0, 0.0, ["دقیقه"], ["minute", "minutes"], "دقیقه"),
    "h": ("time", 3600.0, 0.0, ["ساعت"], ["hour", "hours"], "ساعت"),
    "day": ("time", 86400.0, 0.0, ["روز"], ["day", "days"], "روز"),
    "week": ("time", 604800.0, 0.0, ["هفته"], ["week", "weeks"], "هفته"),
    # --- temperature (base: kelvin)
    "c": ("temperature", 1.0, 273.15, ["سانتی گراد", "درجه سانتی گراد", "سلسیوس", "درجه سلسیوس"],
          ["celsius", "centigrade"], "سانتی‌گراد"),
    "f": ("temperature", Fraction(5, 9), Fraction("459.67") * Fraction(5, 9), ["فارنهایت", "درجه فارنهایت"],
          ["fahrenheit"], "فارنهایت"),
    "k": ("temperature", 1.0, 0.0, ["کلوین", "درجه کلوین"], ["kelvin"], "کلوین"),
    # --- data (base: byte, binary multiples)
    "byte": ("data", 1.0, 0.0, ["بایت"], ["byte", "bytes"], "بایت"),
    "bit": ("data", 0.125, 0.0, ["بیت"], ["bit", "bits"], "بیت"),
    "kb": ("data", 1024.0, 0.0, ["کیلوبایت", "کیلو بایت"], ["kb", "kilobyte", "kilobytes"], "کیلوبایت"),
    "mb": ("data", 1024.0 ** 2, 0.0, ["مگابایت", "مگ", "مگا بایت"], ["mb", "megabyte", "megabytes"], "مگابایت"),
    "gb": ("data", 1024.0 ** 3, 0.0, ["گیگابایت", "گیگ", "گیگا بایت"], ["gb", "gigabyte", "gigabytes"], "گیگابایت"),
    "tb": ("data", 1024.0 ** 4, 0.0, ["ترابایت", "ترا بایت"], ["tb", "terabyte", "terabytes"], "ترابایت"),
    # --- area (base: square metre)
    "m2": ("area", 1.0, 0.0, ["متر مربع"], ["m2"], "متر مربع"),
    "km2": ("area", 1e6, 0.0, ["کیلومتر مربع", "کیلو متر مربع"], ["km2"], "کیلومتر مربع"),
    "ha": ("area", 10000.0, 0.0, ["هکتار"], ["ha", "hectare", "hectares"], "هکتار"),
    # --- speed (base: metre per second)
    "mps": ("speed", 1.0, 0.0, ["متر بر ثانیه"], ["mps"], "متر بر ثانیه"),
    "kmh": ("speed", Fraction(10, 36), 0.0, ["کیلومتر بر ساعت", "کیلو متر بر ساعت"], ["kmh", "kph"], "کیلومتر بر ساعت"),
    "mph": ("speed", 0.44704, 0.0, ["مایل بر ساعت"], ["mph"], "مایل بر ساعت"),
}

DIMENSION_FA = {
    "length": "طول", "mass": "جرم", "volume": "حجم", "time": "زمان", "temperature": "دما",
    "data": "حجم داده", "area": "مساحت", "speed": "سرعت",
}


class Unit:
    __slots__ = ("id", "dimension", "factor", "offset", "display")

    def __init__(self, uid, dimension, factor, offset, display):
        self.id = uid
        self.dimension = dimension
        self.factor = factor
        self.offset = offset
        self.display = display

    def to_dict(self):
        return {"id": self.id, "dimension": self.dimension, "display": self.display}


def _exact(value):
    """Exact rational of a table number (decimal literals are read exactly,
    so 1609.344 is 1609344/1000, not the nearest binary float)."""
    return value if isinstance(value, Fraction) else Fraction(repr(float(value)))


UNITS = {uid: Unit(uid, row[0], _exact(row[1]), _exact(row[2]), row[5]) for uid, row in _RAW.items()}

# normalized matching key -> unit id ; and key-token tuple -> unit id for n-gram scanning
_BY_KEY = {}
_BY_TOKENS = {}
_MAX_NGRAM = 1


def _register(surface, uid):
    global _MAX_NGRAM
    toks = tuple(fa_text.words(surface))
    if not toks:
        return
    _BY_TOKENS.setdefault(toks, uid)
    _BY_KEY.setdefault(fa_text.key(surface), uid)
    _MAX_NGRAM = max(_MAX_NGRAM, len(toks))


for _uid, _row in _RAW.items():
    for _name in _row[3] + _row[4]:
        _register(_name, _uid)
    _register(_row[5], _uid)


def lookup_unit(surface):
    """Unit for a surface string ('سانتی‌متر', 'km', ...) or None."""
    toks = tuple(fa_text.words(surface))
    uid = _BY_TOKENS.get(toks)
    if uid is None:
        uid = _BY_KEY.get(fa_text.key(surface))
    return UNITS.get(uid) if uid else None


def find_units(tokens):
    """Unit mentions in a token list: [(start, end, unit)] with `end`
    exclusive. Longest match wins ("کیلومتر بر ساعت" beats "کیلومتر")."""
    found = []
    i = 0
    n = len(tokens)
    while i < n:
        matched = None
        for size in range(min(_MAX_NGRAM, n - i), 0, -1):
            uid = _BY_TOKENS.get(tuple(tokens[i:i + size]))
            if uid is not None:
                matched = (i, i + size, UNITS[uid])
                break
        if matched:
            found.append(matched)
            i = matched[1]
        else:
            i += 1
    return found


def conversion_params(from_unit, to_unit):
    """(scale, shift) for `from_unit -> to_unit`; SpecError if the
    dimensions differ."""
    if from_unit.dimension != to_unit.dimension:
        raise SpecError(
            f"cannot convert {from_unit.id} ({from_unit.dimension}) to {to_unit.id} ({to_unit.dimension})",
            code="E_SPEC_DIMENSION", from_unit=from_unit.id, to_unit=to_unit.id)
    scale = from_unit.factor / to_unit.factor
    shift = (from_unit.offset - to_unit.offset) / to_unit.factor
    return float(scale), float(shift)


def match_keys(unit_id):
    """Every normalized matching key (Persian + Latin names) of a table unit."""
    row = _RAW[unit_id]
    return sorted({fa_text.key(n) for n in row[3] + row[4] + [row[5]] if fa_text.key(n)})


def supported_names(limit=None):
    """Display names of the table's units (for help messages)."""
    names = [u.display for u in UNITS.values()]
    return names if limit is None else names[:limit]

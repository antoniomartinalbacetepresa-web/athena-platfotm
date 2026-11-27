# Twelve Data daily OHLCV numeric contract

Scope: synthetic adapter regressions toward CORE-001/CORE-012. This contract does
not authorize provider storage, certify historical PIT availability or change
the read-only daily preview's false eligibility flag.

OHLCV values must be JSON numbers (built-in integer/float after JSON decoding)
or decimal strings. Booleans, null, collections and missing fields are rejected.
String spellings follow this ASCII grammar before numeric conversion:

```text
[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?
```

Examples retained for compatibility: `101`, `101.0`, `+101`, `00101.000`,
`101.`, `.101`, `1.01e2` and `1E+2`. The same grammar applies to volume, followed
by exact Decimal integrality and range validation. Integral representations
such as `200.0` and `2e2` remain valid; zero volume is allowed. The inclusive
maximum remains `9223372036854775807`. OHLC prices must remain finite and
strictly positive, and the existing high/low consistency checks still apply.

Underscores, Unicode digits, whitespace around the value, control characters,
hexadecimal syntax, grouping commas, NaN and Infinity are rejected rather than
accepted through Python-specific float/Decimal coercion. JSON document
whitespace outside a numeric value is unaffected. Errors remain sanitized and
never echo the untrusted numeric text or provider key.

Regression file: `backend/tests/test_twelve_data_history_service.py`. Forty
synthetic lexical cases reproduced the permissive-conversion defect before the
change. The adapter suite and the PIT-source-policy suite now pass together:

```sh
cd backend
python -m pytest -q tests/test_twelve_data_history_service.py \
  tests/test_twelve_data_pit_source_policy.py
```

The focal run completed with 176 passing tests in the cloud Python virtual
environment. Date ranges, prior-final-session rules, exact market identity,
request limits, authentication headers, redirect policy, provider error handling
and PIT/storage refusals are unchanged. Final publication SHA and whole-project
CI evidence are recorded separately by the delivery cycle.

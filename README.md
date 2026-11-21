# Test Evidence Audit

A local check for a two-sensor bench calibration. Given two same-unit channels sampled on a shared clock, it checks agreement and reports when missing observations leave a false impression of a pass.

## Run locally

Python 3.10 or later. The CLI uses the standard library and reads the file locally.

```sh
python3 audit.py examples/logger_dropout.csv \
  --sensor BENCH-TEMP --reference REF-TEMP \
  --duration-s 30 --tolerance 0.5 --max-gap-s 2
```

The three example files share one synthetic temperature setup and the PSP CSV layout.

| File | Samples-only check | Evidence audit |
| --- | --- | --- |
| `clean.csv` | Pass | Pass |
| `complete.csv` | Fail | Fail, 7 observations exceed tolerance |
| `logger_dropout.csv` | Pass | Insufficient evidence, gap from 11 s to 19 s |

The complete trace records a 2.6 °C disagreement from seconds 12 through 18. Removing those seven sensor observations makes the largest surviving difference 0.1 °C. The audit reports that the remaining observations cannot support a pass.

## Use an export

The CSV reader supports the wide, shared-clock layout in [PSP Liquids' example export](https://github.com/Purdue-Space-Program/simple_data_plotter/blob/932299158ccd1d2844c414de53847023ba1edf46/utils/test_data_truncated.csv). The default clock is `Dev5_BCLS_ai_time`, with nanosecond timestamps parsed exactly as integers. Choose two same-unit analog columns that use that clock. If your input is Parquet, [PSP's converter](https://github.com/Purdue-Space-Program/simple_data_plotter/blob/932299158ccd1d2844c414de53847023ba1edf46/utils/parquet_to_csv_converter.py) shows how to export wide CSV.

Supply `--start-s` and `--duration-s` to select the calibration interval relative to the first shared-clock timestamp. Supply the actual agreement tolerance and maximum allowable time between paired observations for your protocol. The example uses 0.5 °C and 2 seconds to demonstrate the rule.

A paired observation outside tolerance takes precedence and yields `fail`. With no observed violation, a gap exceeding the allowed interval or fewer than two paired observations yields `insufficient_evidence`. Gaps include the unobserved distance from the selected window boundaries to the first and last paired observations. Blank or NaN cells contribute no pairs. The check assumes a shared clock and a common unit. Passing means the observed pairs and gap lengths meet the chosen rule. It provides no bound on between-sample deviations.

JSON output includes observed violations, insufficiently sampled intervals, and the samples-only comparison. Exit codes are 0 for pass, 1 for an observed failure, 2 for an input error, and 3 for insufficient evidence.

The prototype is MIT-licensed. The bundled examples are synthetic. A public PSP export was used separately for a format smoke test, without treating its signals as a calibration pair.

# Test Evidence Audit

A local CLI for checking whether two sensors agree during a bench calibration. It reports observed disagreement, missing evidence, and borderline readings where measurement uncertainty crosses the tolerance. It reads wide CSVs like the ones exported by PSP Liquids.

## Quickstart

Clone or download this repo and open a terminal in the folder. Use Python 3.10 or newer. There are no packages to install.

### 1. Run the demo

```sh
python3 audit.py examples/logger_dropout.csv --sensor BENCH-TEMP --reference REF-TEMP --duration-s 30 --tolerance 0.5 --max-gap-s 2
```

Expect `insufficient_evidence` and a gap from 11 to 19 seconds. The complete synthetic trace has seven observations with a 2.6 °C disagreement. Those are precisely the observations removed in the dropout example. The remaining observations all agree within 0.1 °C and would pass a samples-only check.

### 2. Find the columns in your own CSV

```sh
python3 audit.py "my run.csv" --list-columns
```

Pick the measured channel, a reference channel in the same units, and their shared timestamp column. The default PSP clock is `Dev5_BCLS_ai_time` in nanoseconds. Set `--clock` and `--timestamp-unit` if your export uses a different header or numeric time unit (`ns`, `us`, `ms`, or `s`). For a Parquet input, export to wide CSV first. [PSP example CSV](https://github.com/Purdue-Space-Program/simple_data_plotter/blob/932299158ccd1d2844c414de53847023ba1edf46/utils/test_data_truncated.csv) · [PSP Parquet converter](https://github.com/Purdue-Space-Program/simple_data_plotter/blob/932299158ccd1d2844c414de53847023ba1edf46/utils/parquet_to_csv_converter.py)

### 3. Audit the calibration window

Replace the example column names and settings with your own protocol. Start time is relative to the first timestamp in the selected clock. Tolerance and uncertainty use the channels' measurement units.

```sh
python3 audit.py "my run.csv" --clock Dev5_BCLS_ai_time --sensor "SENSOR COLUMN" --reference "REFERENCE COLUMN" --start-s 10 --duration-s 30 --tolerance 0.5 --max-gap-s 0.05 --difference-uncertainty 0.1 > audit-report.json
```

Set `--max-gap-s` based on the longest missing interval your check can tolerate. For example, 0.05 s is five nominal intervals at 100 samples/s. Supply `--difference-uncertainty` when your calibration protocol gives a defensible absolute bound on error in the **difference** between the two readings. Its default of zero applies the tolerance to the observed values directly.

## Reading the report

| Verdict | Meaning | Exit code |
| --- | --- | --- |
| `pass` | Every measured difference, including its uncertainty bound, is within tolerance. The window also meets the sampling rule. | 0 |
| `fail` | At least one measured difference exceeds tolerance even after subtracting its uncertainty bound. | 1 |
| `insufficient_evidence` | No definitive failure was observed, but sampling was insufficient or a difference's uncertainty interval crossed the tolerance. | 3 |

An invalid input exits with code 2 and prints the reason to stderr. The JSON also reports the exact gap intervals, the largest interval, the fraction of the window outside oversized gaps, and signed mean difference (sensor minus reference). A failure takes precedence over coverage or uncertainty limits, which remain visible in the report.

For absolute measured difference `d` and a supplied uncertainty bound `u`, the tool considers `[max(0, d-u), d+u]`. For example, `0.45 ± 0.10` overlaps a `0.50` tolerance and requires review. The tool does not estimate uncertainty, synchronize separate clocks, or infer sensor behavior between samples. A passing result describes the check you configured. Blank and NaN sensor cells contribute no pairs. The sampling rule counts gaps between paired readings and at the edges of the selected window.

## Verify

```sh
python3 -m unittest -v
```

The included bench traces are synthetic. A public PSP Liquids export was used for format testing. Source is MIT-licensed.

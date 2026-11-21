"""Audit agreement between two sensors sharing a clock in a wide CSV export."""
import argparse
import csv
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

NS_PER_SECOND = 1_000_000_000


def finite_decimal(raw):
    value = Decimal(raw.strip())
    if not value.is_finite():
        raise ValueError(f"non-finite number {raw!r}")
    return value


def seconds_to_ns(value):
    result = finite_decimal(value) * NS_PER_SECOND
    if result != result.to_integral_value():
        raise ValueError("time arguments must resolve to whole nanoseconds")
    return int(result)


def load_pairs(path, clock, sensor, reference):
    """Read a shared clock without converting epoch nanoseconds to floats."""
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = csv.DictReader(stream)
        columns = (clock, sensor, reference)
        if any((rows.fieldnames or []).count(name) != 1 for name in columns):
            raise ValueError("each selected column must appear exactly once")
        previous = None
        origin = None
        samples = []
        for row in rows:
            try:
                raw = [row.get(name) for name in columns]
                if any(value is None for value in raw):
                    raise ValueError("truncated CSV row")
                stamp, measured, standard = (value.strip() for value in raw)
                if not stamp and not (measured or standard):
                    continue
                timestamp = finite_decimal(stamp)
                if timestamp != timestamp.to_integral_value():
                    raise ValueError("expected an integer epoch-nanosecond timestamp")
                timestamp = int(timestamp)
                if previous is not None and timestamp <= previous:
                    raise ValueError("shared clock must be strictly increasing")
                previous = timestamp
                if origin is None:
                    origin = timestamp
                values = [None if value.lower() in ("", "nan") else finite_decimal(value)
                          for value in (measured, standard)]
                if None not in values:
                    samples.append((timestamp - origin, abs(values[0] - values[1])))
            except (InvalidOperation, ValueError) as error:
                raise ValueError(f"CSV line {rows.line_num}: {error}") from error
    if origin is None:
        raise ValueError("no timestamps in selected clock")
    return samples


def audit(samples, start, end, max_gap, tolerance):
    pairs = [(time, error) for time, error in samples if start <= time <= end]
    boundaries = [start, *(time for time, _ in pairs), end]
    gaps = [{"from_s": left / NS_PER_SECOND, "to_s": right / NS_PER_SECOND,
             "duration_s": (right - left) / NS_PER_SECOND}
            for left, right in zip(boundaries, boundaries[1:]) if right - left > max_gap]
    violations = [{"time_s": time / NS_PER_SECOND, "absolute_error": str(error)}
                  for time, error in pairs if error > tolerance]
    verdict = "fail" if violations else "pass"
    if not violations and (gaps or len(pairs) < 2):
        verdict = "insufficient_evidence"
    return {
        "verdict": verdict,
        "samples_only_verdict": ("fail" if violations else "pass") if pairs else "no_data",
        "paired_samples": len(pairs),
        "scored_window_s": [start / NS_PER_SECOND, end / NS_PER_SECOND],
        "tolerance": str(tolerance),
        "max_gap_s": max_gap / NS_PER_SECOND,
        "worst_observed_absolute_error": str(max(error for _, error in pairs)) if pairs else None,
        "gaps": gaps,
        "out_of_tolerance_samples": violations,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--clock", default="Dev5_BCLS_ai_time")
    parser.add_argument("--sensor", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--start-s", default="0", help="seconds from first shared-clock timestamp")
    parser.add_argument("--duration-s", required=True)
    parser.add_argument("--max-gap-s", required=True)
    parser.add_argument("--tolerance", required=True, help="maximum absolute difference in sensor units")
    args = parser.parse_args()
    try:
        start = seconds_to_ns(args.start_s)
        duration = seconds_to_ns(args.duration_s)
        max_gap = seconds_to_ns(args.max_gap_s)
        tolerance = finite_decimal(args.tolerance)
        if start < 0 or duration <= 0 or not 0 < max_gap < duration or tolerance < 0:
            raise ValueError("require start >= 0, duration > max gap > 0, and tolerance >= 0")
        if len({args.clock, args.sensor, args.reference}) != 3:
            raise ValueError("clock, sensor, and reference must be different columns")
        samples = load_pairs(args.csv, args.clock, args.sensor, args.reference)
    except (OSError, csv.Error, InvalidOperation, ValueError) as error:
        parser.error(str(error))
    result = audit(samples, start, start + duration, max_gap, tolerance)
    print(json.dumps(result, indent=2))
    return {"pass": 0, "fail": 1, "insufficient_evidence": 3}[result["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())

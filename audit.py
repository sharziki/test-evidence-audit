"""Audit agreement between two sensors sharing a clock in a wide CSV export."""
import argparse
import csv
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

NS_PER_SECOND = 1_000_000_000
TIMESTAMP_SCALE = {"ns": 1, "us": 1_000, "ms": 1_000_000, "s": NS_PER_SECOND}


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


def load_pairs(path, clock, sensor, reference, time_unit="ns"):
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
                timestamp = finite_decimal(stamp) * TIMESTAMP_SCALE[time_unit]
                if timestamp != timestamp.to_integral_value():
                    raise ValueError("timestamp must resolve to whole nanoseconds")
                timestamp = int(timestamp)
                if previous is not None and timestamp <= previous:
                    raise ValueError("shared clock must be strictly increasing")
                previous = timestamp
                if origin is None:
                    origin = timestamp
                values = [None if value.lower() in ("", "nan") else finite_decimal(value)
                          for value in (measured, standard)]
                if None not in values:
                    samples.append((timestamp - origin, values[0] - values[1]))
            except (InvalidOperation, ValueError) as error:
                raise ValueError(f"CSV line {rows.line_num}: {error}") from error
    if origin is None:
        raise ValueError("no timestamps in selected clock")
    return samples


def audit(samples, start, end, max_gap, tolerance, uncertainty=Decimal(0)):
    pairs = [(time, difference) for time, difference in samples if start <= time <= end]
    boundaries = [start, *(time for time, _ in pairs), end]
    oversized = [(left, right) for left, right in zip(boundaries, boundaries[1:])
                 if right - left > max_gap]
    gaps = [{"from_s": left / NS_PER_SECOND, "to_s": right / NS_PER_SECOND,
             "duration_s": (right - left) / NS_PER_SECOND} for left, right in oversized]
    violations, indeterminate = [], []
    for time, difference in pairs:
        error = abs(difference)
        lower = max(Decimal(0), error - uncertainty)
        upper = error + uncertainty
        if upper <= tolerance:
            continue
        evidence = {"time_s": time / NS_PER_SECOND, "absolute_error": str(error),
                    "error_bounds": [str(lower), str(upper)]}
        (violations if lower > tolerance else indeterminate).append(evidence)

    reasons = []
    if gaps:
        reasons.append("sampling_gap")
    if len(pairs) < 2:
        reasons.append("too_few_pairs")
    if indeterminate:
        reasons.append("uncertainty_overlaps_tolerance")

    verdict = "fail" if violations else "insufficient_evidence" if reasons else "pass"
    differences = [difference for _, difference in pairs]
    worst = max(map(abs, differences)) if differences else None
    samples_only = "no_data" if worst is None else "fail" if worst > tolerance else "pass"
    gap_time = sum(right - left for left, right in oversized)
    return {
        "verdict": verdict,
        "evidence_limits": reasons,
        "samples_only_verdict": samples_only,
        "paired_samples": len(pairs),
        "scored_window_s": [start / NS_PER_SECOND, end / NS_PER_SECOND],
        "tolerance": str(tolerance),
        "difference_uncertainty": str(uncertainty),
        "max_gap_s": max_gap / NS_PER_SECOND,
        "largest_pair_or_edge_interval_s": max(b - a for a, b in zip(boundaries, boundaries[1:])) / NS_PER_SECOND,
        "fraction_of_window_outside_oversized_gaps": round(1 - gap_time / (end - start), 6),
        "mean_signed_difference": str(sum(differences) / len(differences)) if differences else None,
        "worst_observed_absolute_error": str(worst) if worst is not None else None,
        "gaps": gaps,
        "out_of_tolerance_samples": violations,
        "uncertainty_overlap_samples": indeterminate,
    }


DEFAULTS = {"clock": "Dev5_BCLS_ai_time", "timestamp_unit": "ns",
            "start_s": "0", "difference_uncertainty": "0"}
REQUIRED = ("sensor", "reference", "duration_s", "max_gap_s", "tolerance")
SETTINGS = (*DEFAULTS, *REQUIRED)


def headers_for(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        headers = next(csv.reader(stream), [])
    if not headers:
        raise ValueError("CSV has no header row")
    return headers


def setup(path, defaults):
    columns = headers_for(path)
    for index, name in enumerate(columns, 1):
        print(f"{index:>3}  {name}", file=sys.stderr)

    def ask(label, default=None):
        hint = f" [{default}]" if default is not None else ""
        print(f"{label}{hint}: ", end="", flush=True, file=sys.stderr)
        answer = input().strip()
        return answer or default or ""

    def column(label, default=None):
        while True:
            answer = ask(label + " (number or header)", default)
            if answer in columns:
                return answer
            if answer.isdecimal() and 1 <= int(answer) <= len(columns):
                return columns[int(answer) - 1]
            print("Choose a column from the list.", file=sys.stderr)

    return {
        "clock": column("Shared timestamp column", defaults["clock"]),
        "timestamp_unit": ask("Timestamp unit (ns, us, ms, s)", defaults["timestamp_unit"]),
        "sensor": column("Sensor under test"),
        "reference": column("Reference sensor (same units)"),
        "start_s": ask("Calibration start in seconds from first timestamp", defaults["start_s"]),
        "duration_s": ask("Calibration duration in seconds"),
        "tolerance": ask("Allowed difference in sensor units"),
        "max_gap_s": ask("Longest allowed gap between paired readings in seconds"),
        "difference_uncertainty": ask("Uncertainty bound on the difference", defaults["difference_uncertainty"]),
    }


def print_summary(result):
    print(result["verdict"].replace("_", " ").upper())
    start, end = result["scored_window_s"]
    print(f"{result['paired_samples']} paired readings from {start:g} to {end:g} s")
    if result["worst_observed_absolute_error"] is not None:
        print(f"Largest measured difference: {result['worst_observed_absolute_error']} "
              f"(tolerance {result['tolerance']})")
    if result["gaps"]:
        gap = max(result["gaps"], key=lambda item: item["duration_s"])
        print(f"{len(result['gaps'])} oversized gaps; longest "
              f"{gap['from_s']:g} to {gap['to_s']:g} s ({gap['duration_s']:g} s)")
    for key, description in (("out_of_tolerance_samples", "definite out-of-tolerance readings"),
                             ("uncertainty_overlap_samples", "readings overlap tolerance after uncertainty")):
        if result[key]:
            print(f"{len(result[key])} {description}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--setup", type=Path, metavar="PROFILE", help="choose columns and save a reusable profile")
    mode.add_argument("--profile", type=Path, help="apply a saved profile")
    mode.add_argument("--list-columns", action="store_true", help="print CSV headers and exit")
    parser.add_argument("--report", type=Path, help="save a detailed JSON report to a new file")
    parser.add_argument("--json", action="store_true", help="print full JSON instead of the profile summary")
    parser.add_argument("--clock")
    parser.add_argument("--timestamp-unit", choices=TIMESTAMP_SCALE)
    parser.add_argument("--sensor")
    parser.add_argument("--reference")
    parser.add_argument("--start-s", help="seconds from first shared-clock timestamp")
    parser.add_argument("--duration-s")
    parser.add_argument("--max-gap-s")
    parser.add_argument("--tolerance", help="maximum absolute difference in sensor units")
    parser.add_argument("--difference-uncertainty",
                        help="absolute bound on error in the measured difference, in sensor units")
    args = parser.parse_args()
    try:
        if args.list_columns:
            print("\n".join(headers_for(args.csv)))
            return 0
        config = DEFAULTS.copy()
        if args.profile:
            profile = json.loads(args.profile.read_text(encoding="utf-8"))
            if not isinstance(profile, dict) or any(
                key not in SETTINGS or not isinstance(value, str) for key, value in profile.items()
            ):
                raise ValueError("profile must be a JSON object with audit settings as strings")
            config.update(profile)
        config.update({key: getattr(args, key) for key in SETTINGS if getattr(args, key) is not None})
        for destination in (args.setup, args.report):
            if destination and destination.exists():
                raise ValueError(f"output already exists: {destination}")
        if args.setup and args.report and args.setup.resolve() == args.report.resolve():
            raise ValueError("profile and report must use different paths")
        if args.setup:
            config.update(setup(args.csv, config))
        if any(not config.get(key) for key in REQUIRED):
            raise ValueError("provide a profile, run --setup, or enter the required audit settings")
        start = seconds_to_ns(config["start_s"])
        duration = seconds_to_ns(config["duration_s"])
        max_gap = seconds_to_ns(config["max_gap_s"])
        tolerance = finite_decimal(config["tolerance"])
        if start < 0 or duration <= 0 or not 0 < max_gap < duration or tolerance < 0:
            raise ValueError("require start >= 0, duration > max gap > 0, and tolerance >= 0")
        uncertainty = finite_decimal(config["difference_uncertainty"])
        if uncertainty < 0:
            raise ValueError("difference uncertainty must be nonnegative")
        columns = {key: config[key] for key in ("clock", "sensor", "reference")}
        if len(set(columns.values())) != 3:
            raise ValueError("clock, sensor, and reference must be different columns")
        time_unit = config["timestamp_unit"]
        if time_unit not in TIMESTAMP_SCALE:
            raise ValueError("timestamp unit must be ns, us, ms, or s")
        samples = load_pairs(args.csv, **columns, time_unit=time_unit)
        result = audit(samples, start, start + duration, max_gap, tolerance, uncertainty)
        result["columns"] = columns
        result["timestamp_unit"] = time_unit
        result["input_file"] = args.csv.name
        payload = json.dumps(result, indent=2) + "\n"
        if args.setup:
            with args.setup.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(config, indent=2) + "\n")
            print(f"Saved profile to {args.setup}", file=sys.stderr)
        if args.report:
            with args.report.open("x", encoding="utf-8") as stream:
                stream.write(payload)
            print(f"Saved report to {args.report}", file=sys.stderr)
    except EOFError:
        parser.error("setup ended before all settings were entered")
    except (OSError, csv.Error, InvalidOperation, ValueError) as error:
        parser.error(str(error))
    if args.json or not (args.setup or args.profile):
        print(payload, end="")
    else:
        print_summary(result)
    return {"pass": 0, "fail": 1, "insufficient_evidence": 3}[result["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())

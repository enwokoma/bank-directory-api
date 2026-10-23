"""Measure bank detection against name-enquiry results, and suggest settings from them.

    python -m src.evaluate_detection enquiries.csv
    python -m src.evaluate_detection enquiries.csv --apply

The CSV has a header row and one row per name enquiry that resolved: the
account number in an `account_number` column, and the institution it resolved
at in a `nibss_code` or a `bank_id` column (a row may have both; the bank id
wins). Other columns are ignored, as are rows whose institution is not in the
data file or whose account number cannot be read; both are counted and reported.

Every row goes through `detect()` from `src/countries/nigeria/detection.py`,
and the report says where the right institution ranked: how often it came
first (top-1 recall), in the first three (top-3), or in the recommended block
the API returns at the default coverage, its mean rank, and the same per
institution with at least 20 rows. Then come suggested settings for
`account_detection.json`, derived from the data: a `share` per institution
proportional to its rows (as a percentage of all rows, the scale the file
uses), the leading digits that cover 95% of its rows as `account_prefixes`
(only from institutions with at least 50 rows, and leaving the mobile numbers
of an institution that issues them out, since the digits apply to NUBAN
numbers), and the observed fraction of mobile-shaped numbers as
`phone_number_accounts` for institutions the file already marks as issuing
phone numbers. `--apply` writes the suggestions into the file, keeping its
aliases, other codes and every institution the data says nothing about, so
the change can be reviewed as a git diff.

Account numbers are personal data. The command never prints one, nor any other
cell of the file: the report holds counts, rates and bank ids only, a row that
cannot be read is counted rather than shown, and an error about the file names
no cell either.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.core.dataset import CountryDataset, load_datasets
from src.core.detection import DEFAULT_COVERAGE, recommended_count
from src.countries.nigeria.detection import SETTINGS_FILE, DetectionSettings, detect, load_settings

ACCOUNT_COLUMN = "account_number"
NIBSS_CODE_COLUMN = "nibss_code"
BANK_ID_COLUMN = "bank_id"
NIBSS_CODE_LENGTH = 6

# A recall rate from fewer rows than this says little, so the breakdown by
# institution leaves such institutions out.
MIN_ROWS_FOR_BREAKDOWN = 20
# Leading digits are suggested from this many NUBAN numbers at least: with
# fewer, a digit the bank does use may not have come up yet.
MIN_ROWS_FOR_PREFIXES = 50
# The digits suggested as prefixes are the most common ones, as many as cover
# this fraction of the institution's rows.
PREFIX_COVERAGE = 0.95
# The ranks the recall is reported at.
TOP_RANKS = (1, 3)
DIGITS = "0123456789"

# The order keys are written in, as the committed file has them.
_KEY_ORDER = ("share", "phone_number_accounts", "account_prefixes", "aliases", "other_bank_codes")


@dataclass(frozen=True)
class Row:
    """One name enquiry that resolved: the account number and the bank it resolved at."""

    account_number: str
    bank_id: str


@dataclass(frozen=True)
class RowsRead:
    rows: tuple[Row, ...]
    # Rows that named an institution the data file does not have, by NIBSS code or bank id.
    unknown_institutions: int


@dataclass(frozen=True)
class Outcome:
    """What detection made of one row."""

    bank_id: str
    # Where the right institution ranked, from 1; None when it was not listed at all.
    rank: int | None
    # How many candidates the recommended block held at the default coverage.
    recommended: int
    # The first digit of the 10-digit account number, and whether the number is shaped like a mobile number.
    first_digit: str
    mobile: bool

    @property
    def in_recommended(self) -> bool:
        return self.rank is not None and self.rank <= self.recommended


@dataclass(frozen=True)
class Evaluation:
    outcomes: tuple[Outcome, ...]
    # Rows whose account number detection could not read.
    unreadable: int


@dataclass(frozen=True)
class Tally:
    """How the right institution ranked over a set of rows."""

    rows: int
    # Rows where the right institution ranked at or above each of TOP_RANKS.
    within: dict[int, int]
    in_recommended: int
    recommended_sizes: int
    # Rows where the right institution was listed, and the sum of its ranks there.
    found: int
    rank_sum: int

    @classmethod
    def of(cls, outcomes: list[Outcome]) -> Tally:
        found = [outcome.rank for outcome in outcomes if outcome.rank is not None]
        return cls(
            rows=len(outcomes),
            within={top: sum(1 for rank in found if rank <= top) for top in TOP_RANKS},
            in_recommended=sum(1 for outcome in outcomes if outcome.in_recommended),
            recommended_sizes=sum(outcome.recommended for outcome in outcomes),
            found=len(found),
            rank_sum=sum(found),
        )

    @property
    def missing(self) -> int:
        return self.rows - self.found

    @property
    def mean_rank(self) -> float | None:
        return self.rank_sum / self.found if self.found else None


@dataclass(frozen=True)
class Suggestion:
    """Settings for one institution, derived from its rows."""

    share: float
    # None when there are too few rows to say; empty when the rows start with
    # every digit, so no prefix rule helps.
    account_prefixes: tuple[str, ...] | None
    # None for an institution the file does not mark as issuing phone numbers.
    phone_number_accounts: float | None

    def as_json(self) -> dict[str, Any]:
        item: dict[str, Any] = {"share": self.share}
        if self.phone_number_accounts is not None:
            item["phone_number_accounts"] = self.phone_number_accounts
        if self.account_prefixes is not None:
            item["account_prefixes"] = list(self.account_prefixes)
        return item


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.evaluate_detection", description=__doc__.split("\n\n")[1])
    parser.add_argument("csv", type=Path, help="Name-enquiry results: account_number and nibss_code or bank_id columns")
    parser.add_argument(
        "--settings",
        type=Path,
        default=SETTINGS_FILE,
        help="The account_detection.json to evaluate with and, with --apply, to write to (default: the committed one)",
    )
    parser.add_argument("--apply", action="store_true", help="Write the suggested settings into the settings file")
    args = parser.parse_args(argv)

    dataset = load_datasets()["NGA"]
    settings = load_settings(args.settings)
    try:
        read = read_rows(args.csv, dataset)
    except OSError as exc:
        parser.error(f"cannot read {args.csv}: {exc.strerror or exc}")
    except ValueError as exc:
        parser.error(str(exc))

    evaluation = evaluate(dataset, read.rows, settings)
    total = len(read.rows) + read.unknown_institutions
    print(
        f"Evaluated {len(evaluation.outcomes):,} of {total:,} rows in {args.csv.name}: "
        f"{read.unknown_institutions:,} named an institution that is not in the data file, "
        f"{evaluation.unreadable:,} had an account number that could not be read."
    )
    if not evaluation.outcomes:
        print("Nothing to evaluate.")
        return 1

    print()
    print(format_overall(Tally.of(list(evaluation.outcomes))))
    print()
    print(format_breakdown(evaluation.outcomes))
    suggestions = suggest(evaluation.outcomes, settings)
    print()
    print(
        "Suggested settings, from the rows (share as a percentage of rows; leading digits from institutions "
        f"with at least {MIN_ROWS_FOR_PREFIXES} rows; phone-number fractions for institutions the file marks as "
        "issuing phone numbers):"
    )
    print(json.dumps({"institutions": {bank_id: item.as_json() for bank_id, item in suggestions.items()}}, indent=2))
    if args.apply:
        changed, untouched = apply_suggestions(args.settings, suggestions)
        print()
        print(
            f"Wrote {changed} institutions' settings to {args.settings}; {untouched} listed institutions had no rows "
            "and are unchanged. Review the change with git diff."
        )
    return 0


def read_rows(path: Path, dataset: CountryDataset) -> RowsRead:
    """Read the CSV, resolving each row's institution to a bank id.

    Raises ValueError when the header lacks the needed columns. The message
    names no cell of the file.
    """
    by_nibss_code = {
        bank["identifiers"]["nibss_code"]: bank["id"] for bank in dataset.banks if "nibss_code" in bank["identifiers"]
    }
    rows = []
    unknown = 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = {(name or "").strip().lower(): name for name in reader.fieldnames or ()}
        if ACCOUNT_COLUMN not in columns or not ({NIBSS_CODE_COLUMN, BANK_ID_COLUMN} & set(columns)):
            raise ValueError(
                f"{path.name} needs a header row with an {ACCOUNT_COLUMN} column "
                f"and a {NIBSS_CODE_COLUMN} or {BANK_ID_COLUMN} column."
            )
        for record in reader:
            bank_id = _resolve(record, columns, dataset, by_nibss_code)
            if bank_id is None:
                unknown += 1
                continue
            rows.append(Row(account_number=(record.get(columns[ACCOUNT_COLUMN]) or "").strip(), bank_id=bank_id))
    return RowsRead(rows=tuple(rows), unknown_institutions=unknown)


def _resolve(
    record: dict[str, Any], columns: dict[str, str], dataset: CountryDataset, by_nibss_code: dict[str, str]
) -> str | None:
    """The bank id a row's institution column names, or None when the data file has no such institution."""
    bank_id = _cell(record, columns, BANK_ID_COLUMN)
    if bank_id:
        return bank_id if bank_id in dataset.banks_by_id else None
    code = _cell(record, columns, NIBSS_CODE_COLUMN)
    if code.isdigit():
        # A spreadsheet may have dropped the code's leading zeros.
        code = code.zfill(NIBSS_CODE_LENGTH)
    return by_nibss_code.get(code) if code else None


def _cell(record: dict[str, Any], columns: dict[str, str], column: str) -> str:
    name = columns.get(column)
    return (record.get(name) or "").strip() if name is not None else ""


def evaluate(dataset: CountryDataset, rows: tuple[Row, ...], settings: DetectionSettings) -> Evaluation:
    """Run detection on every row and record where the right institution ranked."""
    outcomes = []
    unreadable = 0
    for row in rows:
        try:
            result = detect(dataset, row.account_number, settings=settings)
        except ValueError:
            unreadable += 1
            continue
        ranked = [candidate.bank["id"] for candidate in result.candidates]
        outcomes.append(
            Outcome(
                bank_id=row.bank_id,
                rank=ranked.index(row.bank_id) + 1 if row.bank_id in ranked else None,
                recommended=recommended_count(result.candidates),
                first_digit=result.account_number[0],
                mobile=result.looks_like_phone_number,
            )
        )
    return Evaluation(outcomes=tuple(outcomes), unreadable=unreadable)


def format_overall(tally: Tally) -> str:
    lines = [f"  top-{top} recall           {_rate(tally.within[top], tally.rows):>6}" for top in TOP_RANKS]
    lines.append(
        f"  recommended recall     {_rate(tally.in_recommended, tally.rows):>6}   "
        f"(coverage {DEFAULT_COVERAGE}, {tally.recommended_sizes / tally.rows:.1f} candidates recommended on average)"
    )
    lines.append(
        f"  mean rank              {_mean_rank(tally):>6}   "
        f"(the right institution is missing from the list in {tally.missing:,} rows, {_rate(tally.missing, tally.rows)})"
    )
    return "\n".join(lines)


def format_breakdown(outcomes: tuple[Outcome, ...]) -> str:
    """Recall per institution, for those with at least MIN_ROWS_FOR_BREAKDOWN rows, most rows first."""
    tallies = {bank_id: Tally.of(group) for bank_id, group in _by_institution(outcomes).items()}
    shown = {bank_id: tally for bank_id, tally in tallies.items() if tally.rows >= MIN_ROWS_FOR_BREAKDOWN}
    if not shown:
        return f"No institution has {MIN_ROWS_FOR_BREAKDOWN} rows or more, so there is no breakdown by institution."
    width = max(len(bank_id) for bank_id in shown)
    header = f"  {'institution':<{width}}    rows   top-1   top-3   recommended   mean rank   missing"
    lines = [f"By institution, for the {len(shown)} with at least {MIN_ROWS_FOR_BREAKDOWN} rows:", header]
    for bank_id, tally in shown.items():
        lines.append(
            f"  {bank_id:<{width}}  {tally.rows:>6}  {_rate(tally.within[1], tally.rows):>6}  "
            f"{_rate(tally.within[3], tally.rows):>6}  {_rate(tally.in_recommended, tally.rows):>12}  "
            f"{_mean_rank(tally):>10}  {tally.missing:>8}"
        )
    return "\n".join(lines)


def suggest(outcomes: tuple[Outcome, ...], settings: DetectionSettings) -> dict[str, Suggestion]:
    """Settings per institution derived from its rows, most rows first; see the module docstring."""
    suggestions = {}
    for bank_id, group in _by_institution(outcomes).items():
        institution = settings.institutions.get(bank_id)
        issues_phone_numbers = institution is not None and institution.phone_number_accounts > 0
        mobile = sum(1 for outcome in group if outcome.mobile)
        # Leading digits apply to NUBAN numbers, so a wallet's mobile numbers say nothing about them.
        nuban_numbers = [outcome for outcome in group if not (issues_phone_numbers and outcome.mobile)]
        suggestions[bank_id] = Suggestion(
            share=_significant(100 * len(group) / len(outcomes)),
            account_prefixes=(
                leading_digits(Counter(outcome.first_digit for outcome in nuban_numbers))
                if len(nuban_numbers) >= MIN_ROWS_FOR_PREFIXES
                else None
            ),
            phone_number_accounts=round(mobile / len(group), 2) if issues_phone_numbers else None,
        )
    return suggestions


def leading_digits(counts: Counter[str]) -> tuple[str, ...]:
    """The most common first digits, as many as cover PREFIX_COVERAGE of the numbers; empty when that takes every digit."""
    total = sum(counts.values())
    chosen = []
    covered = 0
    for digit, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        chosen.append(digit)
        covered += count
        if covered >= PREFIX_COVERAGE * total:
            break
    return () if set(chosen) == set(DIGITS) else tuple(sorted(chosen))


def apply_suggestions(path: Path, suggestions: dict[str, Suggestion]) -> tuple[int, int]:
    """Write the suggested values into the settings file, keeping everything else.

    An institution's share, prefixes and phone-number fraction are replaced by
    the suggested ones where there is a suggestion; its aliases and other codes
    stay, as does every institution without rows. An institution the file did
    not list is added at the end. Returns how many institutions were written
    and how many listed ones were left alone. The file keeps its line endings.
    """
    data = path.read_bytes()
    raw = json.loads(data.decode("utf-8"))
    institutions = raw["institutions"]
    changed = 0
    for bank_id, suggestion in suggestions.items():
        item = dict(institutions.get(bank_id, {}))
        item["share"] = suggestion.share
        if suggestion.phone_number_accounts is not None:
            item["phone_number_accounts"] = suggestion.phone_number_accounts
        if suggestion.account_prefixes:
            item["account_prefixes"] = list(suggestion.account_prefixes)
        elif suggestion.account_prefixes is not None:
            item.pop("account_prefixes", None)
        ordered = {key: item[key] for key in _KEY_ORDER if key in item} | {
            key: value for key, value in item.items() if key not in _KEY_ORDER
        }
        if ordered != institutions.get(bank_id):
            changed += 1
        institutions[bank_id] = ordered
    newline = "\r\n" if b"\r\n" in data else "\n"
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline=newline)
    # The written file must still load; a failure here is a bug, not a data problem.
    load_settings(path)
    return changed, sum(1 for bank_id in institutions if bank_id not in suggestions)


def _by_institution(outcomes: tuple[Outcome, ...]) -> dict[str, list[Outcome]]:
    """Outcomes grouped by the right institution, most rows first, then by id."""
    groups: dict[str, list[Outcome]] = {}
    for outcome in outcomes:
        groups.setdefault(outcome.bank_id, []).append(outcome)
    return dict(sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])))


def _rate(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "-"


def _mean_rank(tally: Tally) -> str:
    return f"{tally.mean_rank:.2f}" if tally.mean_rank is not None else "-"


def _significant(value: float, digits: int = 3) -> float:
    """The value to this many significant digits, so a small share stays positive and a big one readable."""
    return float(f"{value:.{digits}g}")


if __name__ == "__main__":
    sys.exit(main())

"""Shared shape of a bank detection: which institution an account number belongs to.

A country whose account numbers say something about their bank, such as a
check digit computed with the bank's code, names a detection module in its
profile. The module exposes:

    detect(dataset, account_number, *, hint=None, types=None) -> Detection

and raises ValueError for an account number it cannot read. The route in
`src/api/routes.py` turns the result into JSON, so every country answers in
the same shape.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from typing import Any

from src.countries.profile import CountryProfile


@dataclass(frozen=True)
class Candidate:
    """One institution that may hold the account, with the evidence for it."""

    bank: dict[str, Any]
    # The estimated probability that this is the right institution, 0 to 1. A
    # detection's confidences add up to 1.
    confidence: float
    # Short codes for the evidence, strongest first, such as "check_digit" or
    # "hint". Empty when nothing counts for the institution but nothing rules it out.
    reasons: tuple[str, ...]
    # The code the account number's check digit was tested with.
    institution_code: str
    check_digit_valid: bool


@dataclass(frozen=True)
class Detection:
    """Every institution that may hold the account, most likely first."""

    account_number: str
    looks_like_phone_number: bool
    candidates: tuple[Candidate, ...]


def get_detector(profile: CountryProfile) -> Callable[..., Detection] | None:
    """Return the country's `detect` function, or None when it has no detection scheme."""
    return _import_detector(profile.detection_module) if profile.detection_module else None


@cache
def _import_detector(module_path: str) -> Callable[..., Detection]:
    detector: Callable[..., Detection] = importlib.import_module(module_path).detect
    return detector

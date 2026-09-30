"""Domain enums, kept free of database imports so pure data code can use them."""

from enum import StrEnum


class Exchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"


class CorporateActionType(StrEnum):
    SPLIT = "split"
    BONUS = "bonus"
    RIGHTS = "rights"
    DIVIDEND = "dividend"
    OTHER = "other"


class QualityStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"

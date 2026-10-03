"""Company announcements from NSE's PR bundle (the `an` file), the news brain's source.

Each day's file lists what companies told the exchange that day: one line per item,
"<company>  <SYMBOL> : <subject> <SYMBOL> : <text>" since 2019. Before that NSE spliced
the subject into the company name ("JTrading WindowJamna Auto Industries Limited has
informed..."), so the subject is found by matching NSE's known subjects. Routine
filings with nothing to say about the business (NAV declarations, lost share
certificates, newspaper copies) are dropped.

Pure module: the database layer stores what this returns.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import date

_LINE = re.compile(r"^(?P<name>.*?)\s+(?P<symbol>[A-Z0-9&_-]+)\s*:\s*(?P<text>.*)$")
TEXT_LIMIT = 2000

# NSE's announcement subjects, longest first so "Credit Rating- Revision" wins over
# "Credit Rating".
SUBJECTS = sorted(
    [
        "Acquisition",
        "Action(s) initiated or orders passed",
        "Action(s) taken or orders passed",
        "Agreements",
        "Allotment of Securities",
        "Amalgamation/Merger",
        "Amendment to AOA/MOA",
        "Analysts/Institutional Investor Meet/Con. Call Updates",
        "Appointment",
        "Awarding of order(s)/contract(s)",
        "Bagging/Receiving of orders/contracts",
        "Buy back",
        "Capacity addition",
        "Cessation",
        "Change in Auditors",
        "Change in Company Secretary/Compliance Officer",
        "Change in Director(s)",
        "Change in Management",
        "Clarification",
        "Clarification - Financial Results",
        "Commencement of commercial production/operations",
        "Corporate Insolvency Resolution Process",
        "Credit Rating",
        "Credit Rating- New",
        "Credit Rating- Others",
        "Credit Rating- Revision",
        "Daily Buy-Back of equity shares",
        "Default",
        "Disclosure of material issue",
        "Disclosure under SEBI Takeover Regulations",
        "Diversification/Disinvestment",
        "Dividend",
        "Dividend Updates",
        "ESOP/ESOS/ESPS",
        "Financial Results",
        "Fraud/Default/Arrest",
        "General Updates",
        "Giving guarantees/indemnity/ becoming a surety for third party",
        "Investor Presentation",
        "Issue of Securities",
        "Joint Venture",
        "Memorandum of Understanding/Agreements",
        "Monthly Business Updates",
        "Outcome of Board Meeting",
        "Pendency of Litigation(s)/dispute(s) or the outcome impacting the Company",
        "Pledge",
        "Press Release",
        "Related Party Transactions",
        "Reply to Clarification Sought",
        "Reply to Clarification- Financial results",
        "Resignation",
        "Resignation of Statutory Auditor",
        "Restructuring",
        "Retirement",
        "Scheme of Arrangement",
        "Shareholders meeting",
        "Statement of deviation(s) or variation(s) under Reg. 32",
        "Updates",
        # Routine: dropped (see NOISE).
        "Certificate under SEBI (Depositories and Participants) Regulations, 2018",
        "Code of Conduct under SEBI(PIT) Reg., 2015",
        "Copy of Newspaper Publication",
        "Declaration of NAV",
        "Issue of Duplicate Share Certificate",
        "Loss of Share Certificates",
        "Trading Window",
        "Address Change",
        "Record Date",
    ],
    key=len,
    reverse=True,
)
NOISE = frozenset(
    {
        "Certificate under SEBI (Depositories and Participants) Regulations, 2018",
        "Code of Conduct under SEBI(PIT) Reg., 2015",
        "Copy of Newspaper Publication",
        "Declaration of NAV",
        "Issue of Duplicate Share Certificate",
        "Loss of Share Certificates",
        "Trading Window",
        "Address Change",
        "Record Date",
    }
)
# Old lines without a recoverable subject are routine when they say so.
_NOISE_TEXT = re.compile(
    r"net asset value|loss of share certificate|duplicate share certificate|"
    r"newspaper|trading window|regulation 74\s*\(5\)",
    re.I,
)


@dataclass(frozen=True)
class Announcement:
    symbol: str
    day: date
    subject: str | None
    text: str

    @property
    def digest(self) -> str:
        return hashlib.md5(f"{self.symbol}|{self.subject}|{self.text}".encode()).hexdigest()


def _subject(symbol: str, name: str, text: str) -> tuple[str | None, str]:
    """(subject, text without it)."""
    for marker in (f" {symbol} :", f" {symbol}:", f" {symbol}  :"):
        cut = text.find(marker)
        if 0 < cut <= 200:
            return text[:cut].strip(), text[cut + len(marker) :].strip()
    head = text[:200]
    for subject in SUBJECTS:
        at = head.find(subject)
        if at >= 0:
            return subject, _repair(name, (text[:at] + text[at + len(subject) :]).strip())
    return None, text.strip()


def _repair(name: str, body: str) -> str:
    """Undo the letters NSE doubled around the spliced subject ("HDDFC Bank Limited has
    informed" -> "HDFC Bank Limited has informed")."""
    name = name.strip()
    tail = name[-10:]
    at = body.find(tail, 0, len(name) + 15)
    if len(name) >= 10 and at >= 0 and not body.startswith(name):
        return name + body[at + len(tail) :]
    return body


def parse_pr_announcements(text: str, day: date) -> list[Announcement]:
    """The day's announcements, routine ones dropped, duplicates removed. Lines that
    don't start a new item continue the one before."""
    rows: list[dict[str, str]] = []
    for line in text.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        match = _LINE.match(line)
        if match and len(match["symbol"]) >= 2:
            rows.append(match.groupdict())
        elif rows:
            rows[-1]["text"] += " " + line
    found: dict[str, Announcement] = {}
    for row in rows:
        subject, body = _subject(row["symbol"], row["name"], row["text"])
        if subject in NOISE or (subject is None and _NOISE_TEXT.search(body)):
            continue
        item = Announcement(row["symbol"], day, subject, " ".join(body.split())[:TEXT_LIMIT])
        found.setdefault(item.digest, item)
    return list(found.values())

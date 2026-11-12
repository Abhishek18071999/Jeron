# Writes the fetched "Integrated Filing- Financials" lists as a CSV with the columns of
# NSE's Financial Results CSV, so `fundamentals-import` reads it unchanged. A filing is
# dated by the later of its broadcast and creation times (a revision has only the latter),
# so nothing is known before the exchange showed it.
import csv, glob, json, sys
from datetime import datetime

FMT = "%d-%b-%Y %H:%M:%S"
def when(r):
    times = [datetime.strptime(r[k].title(), FMT) for k in ("broadcast_Date", "creation_Date") if r[k]]
    return max(times).strftime(FMT)

def standard(url):
    # `quarter_of` treats every form but "Ind-AS New" as a lender, bank or insurer.
    form = url.rsplit("/", 1)[-1].upper()
    if form.startswith("INTEGRATED_FILING_INDAS"):
        return "Ind-AS New"
    return "NBFC-IND" if form.startswith("INTEGRATED_FILING_NBFC") else "Non-Ind-AS"

rows = {}
for p in sorted(glob.glob(sys.argv[1] + "/*.json")):
    for r in json.load(open(p))["data"]:
        rows[r["xbrl"]] = r
w = csv.writer(open(sys.argv[2], "w", newline=""), quoting=csv.QUOTE_ALL)
w.writerow(["COMPANY NAME", "AUDITED / UNAUDITED", "CUMULATIVE / NON-CUMULATIVE",
            "CONSOLIDATED / NON-CONSOLIDATED", "IND AS/ NON IND AS", "PERIOD", "PERIOD ENDED",
            "RELATING TO", "** XBRL", "Exchange Received Time", "Exchange Dissemination Time",
            "Time Taken"])
for r in sorted(rows.values(), key=lambda r: (r["qe_Date"][-4:], r["cmName"], r["creation_Date"])):
    t = when(r)
    w.writerow([r["cmName"], r["audited"], "Non-cumulative",
                "Consolidated" if r["consolidated"] == "Consolidated" else "Non-Consolidated",
                standard(r["xbrl"]), "Quarterly", r["qe_Date"].title(), r["type_Sub"], r["xbrl"],
                t, t, r["diff"] or ""])
print(len(rows), "filings")

from app.data.search import Listing, initials, key, latest_symbols, load_aliases, search

LISTINGS = [
    Listing("RELIANCE", "Reliance Industries Limited", "EQ"),
    Listing("RALLIS", "Rallis India Limited", "EQ"),
    Listing("SBIN", "State Bank of India", "EQ"),
    Listing("SBILIFE", "SBI Life Insurance Company Limited", "EQ"),
    Listing("HINDUNILVR", "Hindustan Unilever Limited", "EQ"),
    Listing("LT", "Larsen & Toubro Limited", "EQ"),
    Listing("BAJAJ-AUTO", "Bajaj Auto Limited", "EQ"),
    Listing("TATASTEEL", "Tata Steel Limited", "EQ"),
    Listing("SAIL", "Steel Authority of India Limited", "EQ"),
    Listing("ZOMATO", None, "EQ"),
    Listing("ETERNAL", "ETERNAL LIMITED", "EQ"),
    Listing("OLDCO", None, "BE"),
]
RENAMES = {"ZOMATO": "ETERNAL", "GONE": "NOWHERE"}


def find(query, aliases=None, prominent=frozenset()):
    return [
        (m.symbol, m.alias) for m in search(query, LISTINGS, RENAMES, aliases or {}, 10, prominent)
    ]


def test_key_and_initials():
    assert key("tata steel") == "TATASTEEL" and key("L&T") == "LT" and key("_%") == ""
    assert initials("Reliance Industries Limited") == {"RIL"}  # "RI" is too short
    assert initials("State Bank of India") == {"SBI"}
    assert initials("Tata Consultancy Services Limited") == {"TCSL", "TCS"}
    assert initials("ITC Limited") == set()


def test_symbols_names_and_punctuation():
    assert find("tata steel") == [("TATASTEEL", None)]
    assert find("bajaj auto") == [("BAJAJ-AUTO", None)]
    assert find("l&t")[0] == ("LT", None)
    assert find("steel") == [("SAIL", None), ("TATASTEEL", None)]  # name words
    assert find("") == [] and find("_") == []


def test_initials_and_short_names():
    # Initials alone tie with Rallis India; the short-name list puts Reliance first.
    assert find("ril") == [("RALLIS", None), ("RELIANCE", None)]
    assert find("ril", {"RIL": "RELIANCE"})[0] == ("RELIANCE", "RIL")
    assert find("hul") == [("HINDUNILVR", None)]
    assert find("sbi") == [("SBIN", None), ("SBILIFE", None)]
    # A short name pointing at a stock that isn't listed is ignored.
    assert find("xyz", {"XYZ": "MISSING"}) == []


def test_old_symbols_show_the_current_one():
    assert find("zomato") == [("ETERNAL", "was ZOMATO")]
    assert "ZOMATO" not in [s for s, _ in find("o")]


def test_prominent_stocks_first_within_a_step():
    assert find("ril", prominent={"RELIANCE"})[0] == ("RELIANCE", None)


def test_latest_symbols_follows_chains():
    assert latest_symbols([("LTI", "LTIM"), ("LTIM", "LTM")]) == {"LTI": "LTM", "LTIM": "LTM"}
    assert latest_symbols([("A", "B"), ("B", "A")]) == {"A": "B", "B": "A"}  # no loop


def test_alias_file_loads():
    aliases = load_aliases()
    assert aliases["RIL"] == "RELIANCE" and aliases["LANDT"] == "LT"
    assert all(a == key(a) and s == s.strip().upper() for a, s in aliases.items())

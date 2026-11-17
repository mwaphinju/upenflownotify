import re

# Keyed by the 3 digits that follow the "254" country code, e.g. "254710..." -> prefix "710".
DEFAULT_NETWORK_PREFIXES: dict[str, list[str]] = {
    "Safaricom": [
        "110", "111", "112", "113", "114", "115",
        "700", "701", "702", "703", "704", "705", "706", "707", "708", "709",
        "710", "711", "712", "713", "714", "715", "716", "717", "718", "719",
        "720", "721", "722", "723", "724", "725", "726", "727", "728", "729",
        "740", "741", "742", "743", "744", "745", "746", "747", "748", "749",
        "757", "758", "759", "768", "769",
        "790", "791", "792", "793", "794", "795", "796", "797", "798", "799",
    ],
    "Airtel": [
        "100", "101", "102", "103",
        "730", "731", "732", "733", "734", "735", "736", "737", "738", "739",
        "750", "751", "752", "753", "754", "755", "756",
        "780", "781", "782", "783", "784", "785", "786", "787", "788", "789",
    ],
    "Telkom": ["770", "771", "772", "773", "774", "775", "776", "777", "778", "779"],
}


def normalize_kenyan_mobile(value: str) -> str | None:
    compact = re.sub(r"[\s()+-]", "", value)
    if not compact.isdigit():
        return None
    if len(compact) == 10 and compact[0] == "0":
        compact = "254" + compact[1:]
    elif len(compact) == 9 and compact[0] in {"1", "7"}:
        compact = "254" + compact
    if len(compact) != 12 or not compact.startswith("254") or compact[3] not in {"1", "7"}:
        return None
    return compact


def mask_phone(value: str) -> str:
    if len(value) < 7:
        return "***"
    return f"{value[:4]}***{value[-3:]}"


def detect_network(normalized_phone: str, prefix_table: dict[str, list[str]] | None = None) -> str | None:
    table = prefix_table or DEFAULT_NETWORK_PREFIXES
    if len(normalized_phone) != 12 or not normalized_phone.startswith("254"):
        return None
    prefix = normalized_phone[3:6]
    for network, prefixes in table.items():
        if prefix in prefixes:
            return network
    return None
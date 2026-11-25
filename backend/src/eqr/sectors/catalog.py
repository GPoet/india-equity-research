"""Sectors tracked (each backed by an official NSE index), how companies map to them, and
the economic links between sectors (supply chain, financing, end demand).

The links are hand-written domain knowledge with a reason each; the analysis reports the
measured correlation next to every link so a weak link is visible, not hidden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

BENCHMARK = "Nifty 50"


@dataclass(frozen=True)
class Sector:
    key: str
    label: str
    index: str  # exact NSE index name in ind_close_all


_S = [
    ("private_bank", "Private banks", "Nifty Private Bank"),
    ("psu_bank", "PSU banks", "Nifty PSU Bank"),
    ("nbfc", "NBFCs", "Nifty NBFC"),
    ("housing_finance", "Housing finance", "Nifty Housing Finance"),
    ("insurance", "Insurance", "Nifty Insurance"),
    ("capital_markets", "Capital markets (brokers, AMCs, exchanges)", "Nifty Capital Markets"),
    (
        "microfinance",
        "Small finance banks and microfinance",
        "Nifty Small Finance Banks & Microfinance Institutions",
    ),
    ("it", "IT services", "Nifty IT"),
    ("telecom", "Telecom", "Nifty Telecommunications"),
    ("media", "Media", "Nifty Media"),
    ("internet", "Internet companies", "Nifty India Internet"),
    ("pharma", "Pharma", "Nifty Pharma"),
    ("hospitals", "Hospitals", "Nifty Hospitals"),
    ("fmcg", "FMCG", "Nifty FMCG"),
    ("consumer_durables", "Consumer durables", "Nifty Consumer Durables"),
    ("retail", "Retail", "Nifty Retail"),
    ("consumer_services", "Consumer services", "Nifty Consumer Services"),
    ("tourism", "Travel and tourism", "Nifty India Tourism"),
    ("auto", "Autos", "Nifty Auto"),
    ("ev", "EV and new-age auto", "Nifty EV & New Age Automotive"),
    ("metal", "Metals and mining", "Nifty Metal"),
    ("cement", "Cement", "Nifty Cement"),
    ("chemicals", "Chemicals", "Nifty Chemicals"),
    ("oil_gas", "Oil and gas", "Nifty Oil & Gas"),
    ("power", "Power", "Nifty Power"),
    ("capital_goods", "Capital goods", "Nifty Capital Goods"),
    ("construction", "Construction and infra", "Nifty Construction"),
    ("realty", "Real estate", "Nifty Realty"),
    ("defence", "Defence", "Nifty India Defence"),
    ("railways", "Railway PSUs", "Nifty India Railways PSU"),
    ("logistics", "Transport and logistics", "Nifty Transportation & Logistics"),
    ("sugar", "Sugar and ethanol", "Nifty Sugar & Ethanol"),
]
SECTORS: dict[str, Sector] = {k: Sector(k, label, idx) for k, label, idx in _S}

# Economic links: (related sector, why it is linked).
LINKS: dict[str, list[tuple[str, str]]] = {
    "private_bank": [
        ("nbfc", "same credit cycle"),
        ("realty", "home-loan demand"),
        ("auto", "vehicle loans"),
        ("psu_bank", "same rate cycle"),
    ],
    "psu_bank": [
        ("private_bank", "same rate cycle"),
        ("power", "infra lending book"),
        ("capital_goods", "government capex lending"),
        ("construction", "project loans"),
    ],
    "nbfc": [
        ("private_bank", "credit cycle and funding costs"),
        ("auto", "vehicle finance"),
        ("consumer_durables", "consumer loans"),
        ("housing_finance", "retail lending"),
    ],
    "housing_finance": [
        ("realty", "housing demand"),
        ("cement", "construction activity"),
        ("private_bank", "rate cycle"),
    ],
    "insurance": [("capital_markets", "investment flows"), ("hospitals", "health claims")],
    "capital_markets": [("insurance", "savings flows"), ("nbfc", "financialisation of savings")],
    "microfinance": [("nbfc", "unsecured credit cycle"), ("fmcg", "rural demand")],
    "it": [("internet", "digital spend"), ("telecom", "digital infrastructure")],
    "telecom": [("internet", "data consumption"), ("media", "content distribution")],
    "media": [("telecom", "distribution"), ("internet", "advertising spend")],
    "internet": [
        ("it", "tech spending"),
        ("retail", "consumption"),
        ("consumer_services", "discretionary spend"),
    ],
    "pharma": [("hospitals", "healthcare demand"), ("chemicals", "API and intermediate inputs")],
    "hospitals": [("pharma", "healthcare demand"), ("insurance", "health insurance penetration")],
    "fmcg": [
        ("retail", "same consumer"),
        ("sugar", "input costs"),
        ("microfinance", "rural demand"),
    ],
    "consumer_durables": [
        ("realty", "new-home demand"),
        ("retail", "same consumer"),
        ("nbfc", "consumer financing"),
    ],
    "retail": [("fmcg", "same consumer"), ("consumer_services", "urban discretionary spend")],
    "consumer_services": [
        ("retail", "urban discretionary spend"),
        ("tourism", "leisure spend"),
        ("internet", "online consumption"),
    ],
    "tourism": [("consumer_services", "leisure spend"), ("logistics", "aviation and travel")],
    "auto": [
        ("metal", "steel and aluminium inputs"),
        ("nbfc", "vehicle finance"),
        ("oil_gas", "fuel prices"),
        ("ev", "powertrain shift"),
    ],
    "ev": [
        ("auto", "vehicle demand"),
        ("power", "charging and grid"),
        ("metal", "copper and lithium"),
    ],
    "metal": [
        ("auto", "steel demand"),
        ("construction", "infra steel demand"),
        ("capital_goods", "industrial demand"),
        ("realty", "building demand"),
    ],
    "cement": [
        ("realty", "housing construction"),
        ("construction", "infra projects"),
        ("housing_finance", "home-loan volumes"),
    ],
    "chemicals": [
        ("pharma", "intermediates demand"),
        ("oil_gas", "petrochemical feedstock"),
        ("fmcg", "specialty ingredients"),
    ],
    "oil_gas": [("chemicals", "feedstock"), ("auto", "fuel demand"), ("power", "gas-based power")],
    "power": [
        ("capital_goods", "generation and grid equipment"),
        ("metal", "copper and aluminium"),
        ("psu_bank", "project finance"),
    ],
    "capital_goods": [
        ("power", "grid and generation orders"),
        ("defence", "defence orders"),
        ("railways", "rail orders"),
        ("construction", "infra capex"),
    ],
    "construction": [("cement", "materials"), ("metal", "steel"), ("capital_goods", "infra capex")],
    "realty": [
        ("cement", "materials"),
        ("housing_finance", "mortgages"),
        ("consumer_durables", "home fit-outs"),
        ("private_bank", "rate cycle"),
    ],
    "defence": [("capital_goods", "defence manufacturing"), ("railways", "PSU capex")],
    "railways": [
        ("capital_goods", "rolling stock and electrification"),
        ("construction", "track work"),
        ("metal", "rail steel"),
    ],
    "logistics": [
        ("oil_gas", "fuel costs"),
        ("auto", "freight vehicle demand"),
        ("retail", "goods volumes"),
    ],
    "sugar": [("oil_gas", "ethanol blending"), ("fmcg", "sweetener demand")],
}

# Exact names of government-owned (PSU) banks, normalised by _norm_name.
PSU_BANKS = frozenset(
    {
        "state bank of india",
        "bank of baroda",
        "punjab national bank",
        "canara bank",
        "union bank of india",
        "indian bank",
        "bank of india",
        "central bank of india",
        "uco bank",
        "indian overseas bank",
        "bank of maharashtra",
        "punjab & sind bank",
        "punjab and sind bank",
    }
)

# (phrases, sector). Whole-word matching (a trailing "s" allowed); first match wins, so
# specific rules sit above general ones: "NBFC" before "bank", "banking software" before
# "bank", "industrial automation" before "auto", "hospitality" before "hospital".
_RULES: list[tuple[tuple[str, ...], str]] = [
    (("housing finance", "finance - housing", "home finance"), "housing_finance"),
    (("microfinance", "small finance bank"), "microfinance"),
    (("insurance",), "insurance"),
    (("nbfc", "non banking", "non-banking"), "nbfc"),
    (
        ("stock broking", "broking", "asset management", "exchange", "depositor", "capital market"),
        "capital_markets",
    ),
    (
        ("banking software", "software", "computers", "it enabled", "it services", "it consulting"),
        "it",
    ),
    (("bank", "banking"), "private_bank"),  # PSU split by exact name below
    (("finance", "financial services", "investment company", "holding company"), "nbfc"),
    (("telecom", "telecommunication"), "telecom"),
    (("media", "entertainment", "broadcasting", "film", "publishing"), "media"),
    (("e-commerce", "internet"), "internet"),
    (("hospitality", "hotel", "travel", "airline", "aviation", "tourism"), "tourism"),
    (("hospital", "healthcare services", "healthcare facilities"), "hospitals"),
    (("retail", "retailing"), "retail"),
    (("pharma", "pharmaceutical", "drug"), "pharma"),
    (("sugar",), "sugar"),
    (("edible oil", "vanaspati"), "fmcg"),
    (("consumer services",), "consumer_services"),
    (
        (
            "consumer durable",
            "consumer electronics",
            "electronics",
            "household appliance",
            "furniture",
        ),
        "consumer_durables",
    ),
    (
        (
            "industrial automation",
            "power equipment",
            "transmission equipment",
            "electric equipment",
            "electrical equipment",
            "heavy electrical",
            "capital goods",
            "engineering",
            "industrial machinery",
            "machinery",
            "cable",
            "compressor",
            "pump",
        ),
        "capital_goods",
    ),
    (("electric vehicle",), "ev"),
    (
        (
            "automobile",
            "auto component",
            "auto ancillar",
            "auto",
            "tyre",
            "two wheeler",
            "passenger car",
            "commercial vehicle",
            "tractor",
        ),
        "auto",
    ),
    (
        ("steel", "iron", "metal", "aluminium", "copper", "zinc", "mining", "coal", "ferro alloy"),
        "metal",
    ),
    (("cement",), "cement"),
    (
        (
            "chemical",
            "fertiliser",
            "fertilizer",
            "pesticide",
            "agrochemical",
            "paint",
            "dye",
            "pigment",
        ),
        "chemicals",
    ),
    (
        (
            "refinery",
            "refineries",
            "oil exploration",
            "oil",
            "gas",
            "petroleum",
            "lpg",
            "lubricant",
        ),
        "oil_gas",
    ),
    (("power", "electric utilit"), "power"),
    (("defence", "aerospace", "ship building", "shipbuilding"), "defence"),
    (("railway",), "railways"),
    (("construction", "infrastructure", "civil", "epc"), "construction"),
    (("realty", "real estate"), "realty"),
    (("logistic", "shipping", "port", "transport", "courier", "freight"), "logistics"),
    (
        (
            "fmcg",
            "personal care",
            "cosmetic",
            "toiletries",
            "food",
            "beverage",
            "tobacco",
            "dairy",
            "household product",
            "consumer",
        ),
        "fmcg",
    ),
]
_COMPILED = [
    (re.compile("|".join(rf"\b{re.escape(p)}(?:s|es)?\b" for p in phrases)), sector)
    for phrases, sector in _RULES
]


def _norm_name(name: str) -> str:
    n = re.sub(r"\b(limited|ltd)\b\.?", "", name.lower()).strip()
    n = re.sub(r"^the\s+", "", n)
    return re.sub(r"\s+", " ", n).strip(" .,")


def sector_for_industry(industry: str | None, company_name: str = "") -> str | None:
    if not industry:
        return None
    text = industry.lower()
    for pattern, sector in _COMPILED:
        if pattern.search(text):
            if sector == "private_bank" and _norm_name(company_name) in PSU_BANKS:
                return "psu_bank"
            return sector
    return None

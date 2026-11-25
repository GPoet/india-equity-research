from datetime import date

import pytest

from eqr.sources.bse import bse_refs, parse_bse_bhavcopy, parse_bse_quarter, parse_scrips

ARCH = [
    {
        "Quarter": "Consolidated-Sep-26;SQ2026-2027;131.00;c",
        "stand_xbrl_link": None,
        "conso_xbrl_link": "/XBRLFILES/IFIndasUploadDocument/a.xml",
        "Filing_Date_Time": "2026-11-13T17:59:40.173",
        "Revised_Date_Time": None,
        "Year": "2026-2027",
    },
    {
        "Quarter": "Consolidated-Sep-26;SN2026-2027;131.30;c",
        "stand_xbrl_link": None,
        "conso_xbrl_link": "/XBRLFILES/IFIndasUploadDocument/a.xml",
        "Filing_Date_Time": "2026-11-13T17:59:40.173",
        "Revised_Date_Time": None,
        "Year": "2026-2027",
    },
    {
        "Quarter": "Standalone-Mar-20;MQ2019-2020;105.00;D",
        "stand_xbrl_link": "/XBRLFILES/FourOneUploadDocument/b.xml",
        "conso_xbrl_link": None,
        "Filing_Date_Time": "2020-05-14T17:49:56",
        "Revised_Date_Time": "2020-05-20T10:00:00",
        "Year": "2019-2020",
    },
    {
        "Quarter": "Standalone-Mar-16;MQ2015-2016;95.00;D",
        "stand_xbrl_link": "/old.xml",
        "conso_xbrl_link": None,
        "Filing_Date_Time": "2016-05-14T17:49:56",
        "Revised_Date_Time": None,
        "Year": "2015-2016",
    },
]


def test_parse_quarter() -> None:
    assert parse_bse_quarter("Consolidated-Sep-26;SQ2026-2027;131.00;c") == (
        date(2026, 9, 30),
        True,
    )
    assert parse_bse_quarter("Standalone-Mar-20;MQ2019-2020;105.00;D") == (date(2020, 3, 31), False)
    assert (
        parse_bse_quarter("Consolidated-Sep-26;SN2026-2027;131.30;c") is None
    )  # nine months: not a quarter
    assert parse_bse_quarter("garbage") is None


def test_refs_quarters_only_from_2017_with_revision_time() -> None:
    refs = bse_refs(ARCH, "500002")
    assert [(r.period_end, r.consolidated) for r in refs] == [
        (date(2026, 9, 30), True),
        (date(2020, 3, 31), False),
    ]
    assert refs[0].xbrl_url == "https://www.bseindia.com/XBRLFILES/IFIndasUploadDocument/a.xml"
    assert refs[1].filed_at == "20-May-2020 10:00:00"  # a revision counts from when it was filed
    assert refs[0].source == "bse"


def test_bse_bhavcopy_keyed_by_code() -> None:
    text = (
        "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,"
        "StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,"
        "SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,"
        "Rsvd1,Rsvd2,Rsvd3,Rsvd4\n"
        "2026-11-23,2026-11-23,CM,BSE,STK,500002,INE117A01022,ABB,A,,,,,ABB INDIA LIMITED,6900,6950,6850,"
        "6862.00,6862,6915.00,,,,,5238,36137690.00,100,F1,1,,,,,\n"
    )
    bars = parse_bse_bhavcopy(text)
    b = bars["500002"]
    assert b.close == pytest.approx(6862.0) and b.isin == "INE117A01022" and b.series == "A"


def test_parse_scrips_equity_active() -> None:
    rows = [
        {
            "SCRIP_CD": "500002",
            "Scrip_Name": "ABB India Ltd",
            "Status": "Active",
            "ISIN_NUMBER": "INE117A01022",
            "scrip_id": "ABB",
            "Segment": "Equity",
            "NSURL": "https://www.bseindia.com/stock-share-price/abb/500002/",
        },
        {
            "SCRIP_CD": "9",
            "Scrip_Name": "Bond",
            "Status": "Active",
            "ISIN_NUMBER": "INE1",
            "scrip_id": "B",
            "Segment": "Debt",
            "NSURL": "",
        },
    ]
    got = parse_scrips(rows)
    assert list(got) == ["500002"] and got["500002"]["ticker"] == "ABB"

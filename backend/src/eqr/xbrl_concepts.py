"""XBRL concept names used by NSE results filings, mapped to our metric names.

Each tuple is tried in order; the first concept present wins.
"""

from __future__ import annotations

# Ind-AS companies (also NBFCs, which use the Division III layout).
INCOME: dict[str, tuple[str, ...]] = {
    "revenue": ("RevenueFromOperations",),
    "other_income": ("OtherIncome",),
    "total_income": ("Income",),
    "employee_cost": ("EmployeeBenefitExpense",),
    "finance_costs": ("FinanceCosts",),
    "depreciation": ("DepreciationDepletionAndAmortisationExpense",),
    "total_expenses": ("Expenses",),
    "pbt_before_exceptional": ("ProfitBeforeExceptionalItemsAndTax",),
    "exceptional_items": ("ExceptionalItemsBeforeTax",),
    "pbt": ("ProfitBeforeTax",),
    "tax": ("TaxExpense",),
    "pat": ("ProfitLossForPeriod",),
    "pat_owners": ("ProfitOrLossAttributableToOwnersOfParent",),
    "eps_basic": (
        "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
        "BasicEarningsLossPerShareFromContinuingOperations",
    ),
    "eps_diluted": (
        "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
        "DilutedEarningsLossPerShareFromContinuingOperations",
    ),
    "paid_up_capital": ("PaidUpValueOfEquityShareCapital",),
    "face_value": ("FaceValueOfEquityShareCapital",),
    "cfo": ("CashFlowsFromUsedInOperatingActivities",),
    "cfi": ("CashFlowsFromUsedInInvestingActivities",),
    "cff": ("CashFlowsFromUsedInFinancingActivities",),
    "capex_ppe": ("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",),
    "capex_intangibles": ("PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",),
    "dividends_paid": ("DividendsPaidClassifiedAsFinancingActivities",),
}

BALANCE: dict[str, tuple[str, ...]] = {
    "total_assets": ("Assets",),
    "total_equity": ("Equity",),
    "equity_owners": ("EquityAttributableToOwnersOfParent",),
    "minority_interest": ("NonControllingInterest",),
    "borrowings_current": ("BorrowingsCurrent",),
    "borrowings_noncurrent": ("BorrowingsNoncurrent",),
    "cash": ("CashAndCashEquivalents",),
    "bank_balances": ("BankBalanceOtherThanCashAndCashEquivalents",),
    "current_investments": ("CurrentInvestments",),
    "current_assets": ("CurrentAssets",),
    "current_liabilities": ("CurrentLiabilities",),
    "inventories": ("Inventories",),
    "trade_receivables": ("TradeReceivablesCurrent", "TradeReceivables"),
    "trade_payables": ("TradePayablesCurrent",),
    "equity_share_capital": ("EquityShareCapital",),
    # NBFC (Division III) layout: debt totals instead of a current/non-current split
    "borrowings": ("Borrowings",),
    "debt_securities": ("DebtSecurities",),
    "subordinated_liabilities": ("SubordinatedLiabilities",),
    "deposits": ("Deposits",),
    "loans": ("Loans",),
}

# Banks file under the banking taxonomy (Banking Regulation Act format).
BANK_INCOME: dict[str, tuple[str, ...]] = {
    "total_income": ("Income",),
    "interest_earned": ("InterestEarned",),
    "interest_expended": ("InterestExpended",),
    "other_income": ("OtherIncome",),
    "operating_expenses": ("OperatingExpenses",),
    "employee_cost": ("EmployeesCost",),
    "ppop": ("OperatingProfitBeforeProvisionAndContingencies",),
    "provisions": ("ProvisionsOtherThanTaxAndContingencies",),
    "pbt": ("ProfitLossFromOrdinaryActivitiesBeforeTax",),
    "tax": ("TaxExpense",),
    "pat": ("ProfitLossForThePeriod",),
    "pat_owners": ("ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates",),
    "eps_basic": ("BasicEarningsPerShareAfterExtraordinaryItems",),
    "eps_diluted": ("DilutedEarningsPerShareAfterExtraordinaryItems",),
    "gross_npa": ("GrossNonPerformingAssets",),
    "net_npa": ("NonPerformingAssets",),
    "gnpa_pct": ("PercentageOfGrossNpa",),
    "nnpa_pct": ("PercentageOfNpa",),
    "cet1_pct": ("CET1Ratio",),
    "roa_pct": ("ReturnOnAssets",),
    "paid_up_capital": ("PaidUpValueOfEquityShareCapital",),
    "face_value": ("FaceValueOfEquityShareCapital",),
}

BANK_BALANCE: dict[str, tuple[str, ...]] = {
    "total_assets": ("Assets",),
    "advances": ("Advances",),
    "deposits": ("Deposits",),
    "borrowings": ("Borrowings",),
    "investments": ("Investments",),
    "capital": ("Capital",),
    "reserves": ("ReservesAndSurplus",),
    "cash_rbi": ("CashAndBalancesWithReserveBankOfIndia",),
    "cash_banks": ("BalancesWithBanksAndMoneyAtCallAndShortNotice",),
}

# Concepts whose presence marks an Ind-AS financial company (NBFC, insurer, AMC),
# where EBITDA is meaningless because interest is the cost of goods sold.
FINANCIAL_MARKERS = frozenset(
    {"InterestEarned", "ImpairmentOnFinancialInstruments", "FeesAndCommissionIncome"}
)

# Consolidated bank filings tag these ratios as 0.0 when they are not reported.
# Treated as blanks only when GNPA% and NNPA% are both 0 (no real bank has 0% GNPA),
# or for CET1, which is never 0 for an operating bank.
BANK_BLANK_RATIOS = ("gnpa_pct", "nnpa_pct", "cet1_pct", "roa_pct")

QUARTER_DAYS = range(80, 101)

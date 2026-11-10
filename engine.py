"""
CRE Valuation Engine — v1, Step 1: direct capitalization.

Design rule from the spec: the AI reads and writes; this module does the math.
Every number in the memo must trace back to a function in this file.
"""
from dataclasses import dataclass, asdict


@dataclass
class OperatingInputs:
    units: int
    avg_rent: float                 # $/unit/month, in-place
    vacancy: float                  # % of GPR
    concessions_bad_debt: float     # % of GPR
    other_income: float             # $/unit/month
    opex_per_unit: float            # $/unit/year, EXCLUDING taxes, mgmt, reserves
    mgmt_fee: float                 # % of EGI
    reserves_per_unit: float        # $/unit/year


@dataclass
class TaxInputs:
    current_tax_bill: float         # seller's in-place bill (broker case)
    assessment_ratio: float = 0.40  # Georgia assesses at 40% of FMV
    millage: float = 0.030          # 30 mills = $30 per $1,000 of assessed value

    @property
    def effective_rate(self) -> float:
        """Tax as a % of market value."""
        return self.assessment_ratio * self.millage


def operating_statement(op: OperatingInputs) -> dict:
    """Revenue and expenses down to NOI before property taxes."""
    gpr = op.units * op.avg_rent * 12
    vacancy = gpr * op.vacancy
    concessions = gpr * op.concessions_bad_debt
    other = op.units * op.other_income * 12
    egi = gpr - vacancy - concessions + other

    opex = op.units * op.opex_per_unit
    mgmt = egi * op.mgmt_fee
    reserves = op.units * op.reserves_per_unit
    total_exp = opex + mgmt + reserves

    return {
        "gpr": gpr,
        "vacancy": -vacancy,
        "concessions_bad_debt": -concessions,
        "other_income": other,
        "egi": egi,
        "opex": opex,
        "management": mgmt,
        "reserves": reserves,
        "expenses_before_tax": total_exp,
        "noi_before_tax": egi - total_exp,
    }


def direct_cap(op: OperatingInputs, tax: TaxInputs, cap_rate: float,
               reassess: bool = True) -> dict:
    """
    Direct cap value.

    reassess=False -> broker case: uses the seller's current tax bill.
    reassess=True  -> adjusted case: taxes reset to the purchase price.
        Taxes depend on value and value depends on taxes, so solve:
            V = (NOI_pre - t*V) / c   ->   V = NOI_pre / (c + t)
        Because taxes are linear in value this closed form is exact;
        no iteration is needed.
    """
    stmt = operating_statement(op)
    noi_pre = stmt["noi_before_tax"]

    if reassess:
        value = noi_pre / (cap_rate + tax.effective_rate)
        taxes = tax.effective_rate * value
    else:
        taxes = tax.current_tax_bill
        value = (noi_pre - taxes) / cap_rate

    noi = noi_pre - taxes
    return {
        **stmt,
        "taxes": taxes,
        "noi": noi,
        "cap_rate": cap_rate,
        "value": value,
        "value_per_unit": value / op.units,
        "case": "adjusted (taxes reassessed)" if reassess else "broker (in-place taxes)",
    }


def cap_rate_sensitivity(op: OperatingInputs, tax: TaxInputs,
                         cap_rates: list[float], reassess: bool = True) -> list[dict]:
    rows = []
    for c in cap_rates:
        r = direct_cap(op, tax, c, reassess)
        rows.append({"cap_rate": c, "value": r["value"], "per_unit": r["value_per_unit"]})
    return rows


def estimate_value(units: int, gpr_annual: float, physical_vacancy: float,
                   other_income_monthly: float, opex_annual: float,
                   market: str, year_built: int,
                   *,  # ---- optional "improve accuracy" inputs ----
                   millage_override: float | None = None,     # decimal, e.g. 0.032 for 32 mills
                   collected_rent_annual: float | None = None,  # actual rent collected, last 12 months
                   concessions_pct: float = 0.0,               # decimal share of rent given away
                   utility_reimb_monthly: float = 0.0,         # RUBS not already in other income
                   insurance_increase: float = 0.0,            # $/yr expected at next renewal
                   capex_needed: float = 0.0,                  # near-term major repairs, $
                   property_type: str = "Conventional") -> dict:
    """
    Owner-facing estimate: what a buyer would likely pay.
    Owner supplies the property facts; market_data supplies everything else.
    Optional inputs replace market assumptions with the property's actual numbers.
    """
    import market_data as md

    m = md.MARKETS[market]
    pclass = md.property_class(year_built)
    cap = m["cap_rate_class_b"] + md.CLASS_SPREAD[pclass]
    vacancy = max(physical_vacancy, m["vacancy_floor"])
    notes = []

    # Credit loss: the larger of the standard assumption, stated concessions,
    # or what the T-12 shows was actually lost beyond vacancy.
    credit = max(md.CREDIT_LOSS, concessions_pct)
    if concessions_pct > md.CREDIT_LOSS:
        notes.append(f"Concessions of {concessions_pct:.1%} used in place of the standard {md.CREDIT_LOSS:.0%}.")
    if collected_rent_annual:
        actual_loss = max(0.0, 1 - collected_rent_annual / gpr_annual)
        implied_credit = actual_loss - vacancy
        if implied_credit > credit:
            credit = implied_credit
            notes.append(f"Rent collected over the last 12 months is {actual_loss:.1%} below potential rent, "
                         f"so collection loss was raised to {credit:.1%}.")
        else:
            notes.append(f"Rent collected ({actual_loss:.1%} below potential) is in line with the assumptions.")

    millage = millage_override if millage_override else m["millage"]
    if millage_override:
        notes.append(f"Your millage rate ({millage*1000:.2f} mills) used instead of the market default.")

    total_other = other_income_monthly + utility_reimb_monthly
    if utility_reimb_monthly:
        notes.append(f"Utility reimbursements of ${utility_reimb_monthly:,.0f}/mo added to other income.")

    total_opex = opex_annual + insurance_increase
    if insurance_increase:
        notes.append(f"Expected insurance increase of ${insurance_increase:,.0f}/yr added to expenses.")

    op = OperatingInputs(
        units=units,
        avg_rent=gpr_annual / units / 12,
        vacancy=vacancy,
        concessions_bad_debt=credit,
        other_income=total_other / units,
        opex_per_unit=total_opex / units,
        mgmt_fee=md.MGMT_FEE,
        reserves_per_unit=md.RESERVES_PER_UNIT,
    )
    tax = TaxInputs(current_tax_bill=0, assessment_ratio=md.GEORGIA_ASSESSMENT_RATIO,
                    millage=millage)

    mid = direct_cap(op, tax, cap, reassess=True)
    low = direct_cap(op, tax, cap + md.CAP_RANGE, reassess=True)
    high = direct_cap(op, tax, cap - md.CAP_RANGE, reassess=True)

    # A buyer deducts near-term capital needs dollar for dollar from the price.
    for r in (mid, low, high):
        r["value_before_capex"] = r["value"]
        r["value"] = r["value"] - capex_needed
        r["value_per_unit"] = r["value"] / units
    if capex_needed:
        notes.append(f"${capex_needed:,.0f} of near-term repairs deducted from value.")

    warnings = []
    if property_type == "Student housing":
        warnings.append("Student housing is leased by the bed and trades at different cap rates than "
                        "conventional apartments. This estimate uses conventional assumptions and may be off.")
    elif property_type == "Affordable / rent-restricted":
        warnings.append("Rent-restricted properties have capped rent growth and often trade at different cap "
                        "rates. This estimate uses conventional assumptions and may be off.")

    sources = {
        "Cap rate": m["cap_source"], "Class adjustment": md.CLASS_SOURCE,
        "Property tax": "Owner-provided millage rate" if millage_override else m["millage_source"],
        "Vacancy floor": m["vacancy_source"],
    }
    return {
        "mid": mid, "low": low, "high": high,
        "cap_rate": cap, "property_class": pclass, "vacancy_used": vacancy,
        "credit_loss_used": credit, "effective_tax_rate": tax.effective_rate,
        "capex": capex_needed, "notes": notes, "warnings": warnings, "sources": sources,
    }

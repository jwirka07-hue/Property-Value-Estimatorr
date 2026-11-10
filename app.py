"""
What's my apartment property worth?  —  Streamlit app
Run locally:  streamlit run app.py
"""
import streamlit as st

import market_data as md
import rentroll
from engine import estimate_value

st.set_page_config(page_title="Apartment Value Estimator", page_icon="🏢", layout="centered")


def money(x: float) -> str:
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


st.title("What's your apartment property worth?")
st.caption("Georgia multifamily · Upload a rent roll, answer three questions, get a value range.")

# ---------- 1. Property ----------
st.subheader("1. Your property")
c1, c2 = st.columns(2)
market = c1.selectbox("Market", list(md.MARKETS.keys()))
year_built = c2.number_input("Year built", min_value=1900, max_value=2027, value=None,
                             step=1, placeholder="e.g. 1998")

# ---------- 2. Rent roll ----------
st.subheader("2. Rent roll")
uploaded = st.file_uploader("Upload your rent roll (CSV or Excel)", type=["csv", "xlsx", "xls"],
                            help="Needs a unit column and a rent column. A status column "
                                 "(Occupied / Vacant) and market rent column help but are optional.")
st.download_button("Download a blank template", rentroll.template().to_csv(index=False),
                   "rent_roll_template.csv", "text/csv")

rr = None
with st.expander("No rent roll handy? Enter totals instead"):
    m1, m2, m3 = st.columns(3)
    man_units = m1.number_input("Total units", min_value=0, value=None, step=1)
    man_occ = m2.number_input("Occupied units", min_value=0, value=None, step=1)
    man_rent = m3.number_input("Average rent ($/mo)", min_value=0.0, value=None, step=25.0)

if uploaded is not None:
    try:
        rr = rentroll.summarize(rentroll.read_file(uploaded))
        st.success(f"Read {rr['units']} units · {rr['occupied']} occupied · "
                   f"average rent {money(rr['avg_in_place_rent'])}/mo")
        for w in rr["warnings"]:
            st.info(w)
    except Exception as e:
        st.error(f"Couldn't read that file: {e}")
elif man_units and man_rent and man_occ is not None:
    if man_occ > man_units:
        st.error("Occupied units can't be more than total units.")
    else:
        rr = {"units": int(man_units), "occupied": int(man_occ),
              "physical_vacancy": (man_units - man_occ) / man_units,
              "avg_in_place_rent": man_rent, "gpr_annual": man_units * man_rent * 12}

# ---------- 3. Income & expenses ----------
st.subheader("3. Income and expenses")
e1, e2 = st.columns(2)
opex = e1.number_input("Annual operating expenses ($)", min_value=0.0, value=None, step=1000.0,
                       help="Utilities, repairs, payroll, insurance, admin, marketing. "
                            "Leave OUT property taxes, management fees and reserves — "
                            "we add those at what a buyer would pay.")
other = e2.number_input("Other monthly income ($, optional)", min_value=0.0, value=0.0, step=100.0,
                        help="Parking, pet fees, laundry, utility reimbursements — total per month.")

# ---------- Optional: improve accuracy ----------
with st.expander("Add Other Information to Improve Accuracy"):
    st.caption("All optional. Each answer replaces a market assumption with your property's actual numbers.")

    st.markdown("**Property type**")
    property_type = st.selectbox("What kind of property is it?",
                                 ["Conventional", "Student housing", "Affordable / rent-restricted"],
                                 label_visibility="collapsed")

    st.markdown("**Property taxes**")
    t1, t2 = st.columns(2)
    address = t1.text_input("Property address", placeholder="123 Main St, Athens, GA",
                            help="Kept with your estimate for reference.")
    mills = t2.number_input("Total millage rate (mills)", min_value=0.0, max_value=80.0, value=None,
                            step=0.5, placeholder="e.g. 32.5",
                            help="Listed on your county tax bill. Rates vary a lot by city and county — "
                                 "inside Atlanta city limits is much higher than most suburbs.")

    st.markdown("**Income detail (from your T-12)**")
    i1, i2 = st.columns(2)
    collected = i1.number_input("Rent actually collected, last 12 months ($)", min_value=0.0,
                                value=None, step=10000.0,
                                help="Total rent received, after vacancy, concessions and bad debt. "
                                     "Shows how much of the rent roll actually turns into cash.")
    concessions = i2.number_input("Move-in specials / concessions (% of rent)", min_value=0.0,
                                  max_value=50.0, value=0.0, step=0.5,
                                  help="Example: one month free on a 12-month lease ≈ 8.3%.")
    utilities = i1.number_input("Utility reimbursements collected ($/month)", min_value=0.0,
                                value=0.0, step=100.0,
                                help="Water, sewer or trash billed back to residents (RUBS). "
                                     "Leave at 0 if already counted in other income above.")
    insurance = i2.number_input("Expected insurance increase at renewal ($/year)", min_value=0.0,
                                value=0.0, step=1000.0,
                                help="Southeast premiums have risen sharply. If your renewal quote is "
                                     "higher than what's in your expenses, enter the difference.")

    st.markdown("**Condition and upcoming repairs**")
    ch1, ch2 = st.columns(2)
    old_roof = ch1.checkbox("Roof is 20+ years old")
    old_hvac = ch1.checkbox("Most HVAC systems are 15+ years old")
    poly = ch2.checkbox("Polybutylene or galvanized plumbing")
    unreno = ch2.checkbox("Most units have original interiors")
    capex = st.number_input("Estimated cost of major repairs needed in the next 2–3 years ($)",
                            min_value=0.0, value=0.0, step=10000.0,
                            help="Buyers subtract this from the price dollar for dollar.")
    if (old_roof or old_hvac or poly) and capex == 0:
        st.warning("You checked a major system near the end of its life. A buyer will price in that "
                   "replacement — enter an estimated cost above for a more realistic number.")
    if unreno:
        st.info("Original interiors can mean rent upside for a buyer. That's reflected in the cap rate "
                "range, not added to value.")

ready = rr is not None and year_built and opex
if st.button("Estimate value", type="primary", disabled=not ready, use_container_width=True):
    r = estimate_value(rr["units"], rr["gpr_annual"], rr["physical_vacancy"],
                       other, opex, market, int(year_built),
                       millage_override=mills / 1000 if mills else None,
                       collected_rent_annual=collected or None,
                       concessions_pct=concessions / 100,
                       utility_reimb_monthly=utilities,
                       insurance_increase=insurance,
                       capex_needed=capex,
                       property_type=property_type)
    mid, low, high = r["mid"], r["low"], r["high"]

    st.divider()
    st.markdown("### Estimated value")
    st.markdown(f"## {money(low['value'])} – {money(high['value'])}")
    k1, k2, k3 = st.columns(3)
    k1.metric("Midpoint", money(mid["value"]))
    k2.metric("Per unit", money(mid["value_per_unit"]))
    k3.metric("Cap rate", f"{r['cap_rate']:.2%}")

    for w in r["warnings"]:
        st.warning(w)
    if r["notes"]:
        st.markdown("**Based on the extra information you added:**\n" +
                    "\n".join(f"- {n}" for n in r["notes"]))

    if mid["noi"] <= 0:
        st.error("Expenses exceed income, so the property has no positive NOI to value. "
                 "Check the expense figure.")

    with st.expander("How we got this number", expanded=True):
        rows = [
            ("Gross potential rent", mid["gpr"]),
            (f"Vacancy ({r['vacancy_used']:.1%})", mid["vacancy"]),
            (f"Concessions + bad debt ({r['credit_loss_used']:.1%})", mid["concessions_bad_debt"]),
            ("Other income", mid["other_income"]),
            ("**Effective gross income**", mid["egi"]),
            ("Operating expenses", -mid["opex"]),
            (f"Management ({md.MGMT_FEE:.0%} of EGI)", -mid["management"]),
            (f"Reserves (${md.RESERVES_PER_UNIT}/unit)", -mid["reserves"]),
            (f"Property taxes, reset to sale price ({r['effective_tax_rate']:.2%} of value)", -mid["taxes"]),
            ("**Net operating income**", mid["noi"]),
        ]
        st.markdown("| Line | Annual |\n|---|---:|\n" +
                    "\n".join(f"| {k} | {money(v)} |" for k, v in rows))
        if r["capex"]:
            value_line = (f"**Value** = NOI ÷ cap rate − repairs = {money(mid['noi'])} ÷ {r['cap_rate']:.2%} "
                          f"− {money(r['capex'])} = {money(mid['value_before_capex'])} − {money(r['capex'])} = "
                          f"**{money(mid['value'])}**  \n")
        else:
            value_line = (f"**Value** = NOI ÷ cap rate = {money(mid['noi'])} ÷ {r['cap_rate']:.2%} = "
                          f"**{money(mid['value'])}**  \n")
        st.markdown(
            value_line +
            f"The range uses cap rates of {r['cap_rate'] + md.CAP_RANGE:.2%} (low) to "
            f"{r['cap_rate'] - md.CAP_RANGE:.2%} (high). Built in {int(year_built)} → "
            f"priced as Class {r['property_class']}."
        )
        st.caption("Why taxes are reset: in Georgia a sale triggers reassessment at the purchase "
                   "price, so a buyer underwrites the new tax bill, not yours.")

    with st.expander("Assumptions and sources"):
        for k, v in r["sources"].items():
            st.markdown(f"- **{k}:** {v}")

st.divider()
st.caption("This is an automated estimate for informational purposes only. It is not an appraisal "
           "or broker opinion of value and should not be relied on for lending, tax or legal decisions.")

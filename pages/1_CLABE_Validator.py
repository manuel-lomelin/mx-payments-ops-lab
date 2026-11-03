import pandas as pd
import streamlit as st

from core.clabe import load_banks, validate_clabe

st.set_page_config(page_title="CLABE validator", page_icon="🏦", layout="wide")
st.title("CLABE validator")
st.caption("18 digits = 3 bank + 3 plaza + 11 account + 1 check digit (weights 3, 7, 1).")

value = st.text_input("CLABE", value="002010077777777771", max_chars=24)
if value:
    result = validate_clabe(value)
    if result.valid:
        st.success(f"Valid CLABE · {result.bank_name}")
    else:
        for msg in result.messages:
            st.error(msg)
    if result.bank_code:
        cols = st.columns(5)
        cols[0].metric("Bank code", result.bank_code)
        cols[1].metric("Bank", result.bank_name or "Unknown")
        cols[2].metric("Plaza", result.plaza_code)
        cols[3].metric("Account", result.account_number)
        expected = result.expected_check_digit
        cols[4].metric("Check digit", f"{result.check_digit} (expected {expected})")

with st.expander("Bank catalog (public subset; verify against Banxico)"):
    banks = load_banks()
    st.dataframe(
        pd.DataFrame(sorted(banks.items()), columns=["code", "name"]),
        hide_index=True,
        width="stretch",
    )

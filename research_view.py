"""The Research layout (WP-3.4): draws one research_data.Research result. Shared by the Research page and the
Library page; formatting only, nothing is computed here."""
import html

import pandas as pd
import plotly.express as px
import streamlit as st

import research_data as rd

NA = "n/a"
LIGHT_CSS = {"green": "#2e7d32", "amber": "#f9a825", "red": "#c62828", "grey": "#9e9e9e"}  # badge backgrounds


def pct(x, places=1, sign=False, blank=NA):
    """'12.3%'; the formatting lives in research_data (shared with the comparison)."""
    return rd.pct(x, places, sign, blank)


def money(ccy, x):
    """'RM 430.0 bn' for MYR, 'USD 101.2 bn' otherwise; the k / m / bn rounding lives in research_data."""
    return rd.short_money(ccy, x)


def shown(x):
    return NA if x is None else str(x)


def badge(lt):
    """The light as a small coloured badge showing the colour word."""
    return (f'<span style="background:{LIGHT_CSS[lt.colour]};color:#ffffff;padding:2px 10px;'
            f'border-radius:10px;font-size:0.85em;font-weight:600">{lt.colour}</span>')


def times(x, suffix=""):
    """A multiple to 1 decimal: '14.2' or '9.8x' (formatting in research_data)."""
    return rd.times(x, suffix)


def price_text(x):
    """A price: 3 decimals below 1, else 2, with thousands separators (formatting in research_data)."""
    return rd.price_text(x)


def priced(x, ccy):
    """'0.285 MYR'; 'n/a' alone when there is no price (formatting in research_data)."""
    return rd.priced(x, ccy)


def draw_price_chart(chart, ccy):
    """The 5-year Close line from research_data's price_chart frame."""
    fig = px.line(chart, x="Date", y="Close")
    fig.update_layout(xaxis_title=None, yaxis_title=shown(ccy))
    st.plotly_chart(fig)


def draw_returns(stats):
    """The three return metrics and the three risk metrics (beta: WP-3.8); shared by the ETF and the stock view."""
    for col, k in zip(st.columns(3), ("1y", "3y", "5y")):
        col.metric(f"{k} return", pct(stats["returns"][k], sign=True),
                   help="Total change in price with dividends reinvested over the period")
        col.caption(f"{pct(stats['annual_returns'][k])} a year")

    v1, v2, v3 = st.columns(3)
    v1.metric("Volatility", pct(stats["volatility_3y"]),
              help="How much the price typically swings in a year; higher means a bumpier ride")
    v1.caption("annualised, last 3 years")
    v2.metric("Max drawdown", pct(stats["max_drawdown_3y"]),
              help="The biggest drop from a high point to a later low before it recovered")
    v2.caption("worst fall from a peak, last 3 years")
    index = stats.get("beta_index")  # .get: a snapshot saved before WP-3.8 has neither key
    v3.metric("Beta", rd.beta_text(stats.get("beta_3y")),
              help=f"Against {index}, last 3 years. 1.00 moves in step with the market." if index
              else "No home market index for this code.")


def fact(col, label, value, caption=None, help=None):
    """A labelled figure that wraps onto a second line in a narrow column instead of being cut off with
    '...' as st.metric does (WP-3.2.1). Plain markdown text, no HTML; a small heading without a link icon."""
    col.caption(label, help=help)
    col.markdown(f"#### {value}", anchors=False)
    if caption is not None:
        col.caption(caption)


def draw_links(r):
    st.subheader("Links")
    st.caption(f"[Yahoo]({r.links['yahoo']}) · [Filings]({r.links['filings']})")


def draw_company(r, co):
    st.subheader("Company")
    st.caption(" · ".join([shown(r.sector), shown(r.industry)]))
    f1, f2 = st.columns(2)
    low, high = co["range_low"], co["range_high"]
    fact(f1, "52-week range",
         NA if low is None or high is None else f"{price_text(low)} – {price_text(high)} {shown(r.currency)}",
         caption=None if co["range_position"] is None else f"now {pct(co['range_position'], places=0)} of the way up",
         help="Lowest and highest traded price over the last year")
    nxt = co["next_earnings"]
    fact(f2, "Next earnings", NA if nxt is None else f"{nxt:%d %b %Y}",
         help="The next results date Yahoo expects; it may be an estimate")
    m1, m2 = st.columns(2)
    m1.metric("Insiders own", pct(co["insiders"]), help="Share of the company held by directors and managers")
    m2.metric("Institutions own", pct(co["institutions"]), help="Share held by funds, banks and insurers")
    with st.expander("What the company does"):
        summary = co["summary"]
        st.markdown(NA if not summary else summary.replace("$", "\\$"))  # a bare $ would start maths
        if co["website"]:
            st.markdown(f"[{co['website']}]({co['website']})")


def draw_credit(r):
    st.subheader("Credit health")
    if r.is_financial:
        st.info(rd.BANK_LINE)
    if not r.periods:
        st.info("Yahoo has no financial statements for this code, so the ratios cannot be worked out.")
        return
    cols = ["Group", "Ratio", *r.periods, "Light", "Why"]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for row in rd.credit_rows(r):
        cells = " | ".join(html.escape(str(x)) for x in [row["group"], row["ratio"], *row["cells"]])
        lines.append(f"| {cells} | {badge(row['light'])} | {html.escape(row['light'].reason)} |")
    st.markdown("\n".join(lines), unsafe_allow_html=True)  # only the badge is HTML
    st.caption("Overall light = the worst of the four lender ratios: " + ", ".join(rd.LENDER_RATIOS)
               + ". TTM = the latest twelve months.")


def draw_price(r, co):
    st.subheader("Price and risk")
    if co["price_chart"].empty:
        st.write("Price history: not provided by Yahoo for this code.")
        return
    draw_price_chart(co["price_chart"], r.currency)
    st.caption("Five years of prices, adjusted for dividends and splits.")
    draw_returns(co)


def draw_valuation(r):
    st.subheader("Valuation")
    v = r.valuation
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("P/E", times(v["pe"]),
              help="Price divided by last year's profit per share; lower means cheaper for the same profit")
    a2.metric("Forward P/E", times(v["forward_pe"]),
              help="Price divided by the profit per share analysts expect next year")
    a3.metric("P/B", times(v["pb"]),
              help="Price divided by the book value (assets minus debts) per share")
    a4.metric("EV/EBITDA", times(v["ev_ebitda"], "x"),
              help="Company value including debt, divided by yearly earnings before interest, tax and depreciation")
    b1, b2, b3 = st.columns(3)
    fact(b1, "Dividend yield", pct(v["dividend_yield"], places=2),
         help="Dividends paid over the last year as a share of the price")
    fact(b2, "Analyst target", priced(v["target_mean"], r.currency),
         caption=None if v["upside"] is None
         else f"{'upside' if v['upside'] >= 0 else 'downside'} {pct(v['upside'], sign=True)}",
         help="The average price analysts expect in about a year")
    counts = (v["buy"], v["hold"], v["sell"])
    fact(b3, "Analysts", NA if all(x is None for x in counts)
         else f"{shown(v['buy'])} buy · {shown(v['hold'])} hold · {shown(v['sell'])} sell",
         caption=None if v["analysts"] is None else f"{v['analysts']} analysts",
         help="How many analysts say buy, hold or sell, from Yahoo's latest month")


def draw_dividends(r, co):
    st.subheader("Dividends")
    t = co["dividends"]
    if t.empty:
        st.write("Dividend history: not provided by Yahoo for this code.")
    else:
        st.dataframe(t, hide_index=True, column_config={
            "Per share": st.column_config.NumberColumn(f"Per share ({shown(r.currency)})", format="%.4f")})
        if not t["Payments"].any():
            st.write("No dividends in the years shown")
    st.metric("Payout ratio", pct(co["payout_ratio"]), help="Share of profit paid out as dividends")


def draw_statements(r):
    if not r.periods:
        return
    st.subheader("Statements")
    st.caption(f"Key lines only, the figures the ratios are built from. {rd.statement_unit(r)}.")
    tables = rd.statement_rows(r)
    for s, title in rd.STATEMENT_TITLES.items():
        with st.expander(title):
            st.dataframe(tables[s].style.format("{:,.0f}", na_rep=""))


def draw_compare(c):
    """The "What moved" table of a research_data.Comparison: texts only, every figure and change already
    written by research_data.compare."""
    st.subheader("What moved")
    if c.rows:
        st.caption(f"Saved figures from {c.saved_on} beside today's from {c.today_on}.")
    for note in c.notes:
        st.caption(note)
    if not c.rows:
        return
    st.dataframe(pd.DataFrame(
        [[m.section, m.figure, m.saved, m.today, m.change, m.note] for m in c.rows],
        columns=["Section", "Figure", f"Saved ({c.saved_on})", f"Today ({c.today_on})", "Change", "Note"]),
        hide_index=True)


def draw(r, *, caption=None):
    """The Research layout for r: header, tiles, then the stock view or the ETF body. caption replaces the
    "Data as of ... saved copies are reused for an hour" line when given (the Library's reopened snapshot)."""
    e = r.etf
    group = e["category"] if e is not None else r.sector
    st.subheader(r.name)
    st.caption(" · ".join([shown(r.exchange), shown(group), r.code]))
    if e is not None:
        st.markdown(f"**{rd.etf_verdict(e)}**")

    c1, c2, c3 = st.columns(3)
    fact(c1, "Price", priced(r.price, r.currency))
    if e is not None:
        size = money(e["currency"], e["fund_size"])
        if e["fund_size_myr"] is not None:
            size = f"{money('MYR', e['fund_size_myr'])} ({size})"
        fact(c2, "Fund size", size,
             help="Total assets of the fund, in Ringgit with the fund's own currency in brackets")
    else:
        co = r.company
        cap = money(r.currency, r.market_cap)
        if co is not None and co["market_cap_myr"] is not None:
            myr = money("MYR", co["market_cap_myr"])
            cap = myr if r.currency == "MYR" else f"{myr} ({money(r.currency, co['market_cap'])})"
        fact(c2, "Market cap", cap,
             help="What the market values the whole company at, in Ringgit with the listing currency in brackets")
    c3.markdown("Overall<br>" + badge(r.overall), unsafe_allow_html=True)
    c3.caption(r.overall.reason)
    if caption is None:
        caption = f"Data as of {r.fetched_at:%Y-%m-%d %H:%M}, Yahoo Finance; saved copies are reused for an hour"
    st.caption(caption)

    if e is None:
        if co is not None:
            draw_company(r, co)
        draw_credit(r)
        if co is not None:
            draw_price(r, co)
        draw_valuation(r)
        if co is not None:
            draw_dividends(r, co)
        draw_statements(r)
        draw_links(r)
        return

    st.subheader("Costs and size")
    lights = e["lights"]
    rows = [("Expense ratio", pct(e["expense_ratio"], places=2), lights["expense_ratio"]),
            ("Fund size", size, lights["fund_size"])]
    st.markdown("| Item | Value | Light | Why |\n|---|---|---|---|\n"
                + "\n".join(f"| {item} | {html.escape(value)} | {badge(lt)} | {html.escape(lt.reason)} |"
                            for item, value, lt in rows),  # only the badge is HTML
                unsafe_allow_html=True)
    st.metric("Distribution yield", pct(e["distribution_yield"], places=2),
              help="Dividends paid over the last year as a share of the price")

    st.subheader("Returns and risk")
    if not e["price_chart"].empty:
        draw_price_chart(e["price_chart"], e["currency"])
    st.caption("Dividends included.")
    draw_returns(e)

    st.subheader("What it holds")
    top = e["top_holdings_pct"]
    if top.empty:
        st.write("Top ten holdings: not provided by Yahoo for this fund.")
    else:
        st.markdown("**Top ten holdings**")
        top_max = e["top_weight_max_pct"]
        if top_max is None:  # Yahoo gave names without weights: plain table, no bars
            st.dataframe(top[["Name", "Symbol"]], hide_index=True)
        else:
            st.dataframe(top, hide_index=True, column_config={
                "Weight %": st.column_config.ProgressColumn("Weight", format="%.1f%%", min_value=0.0,
                                                            max_value=top_max)})
    sectors = e["sector_mix"]
    if sectors.empty:
        st.write("Sector mix: not provided by Yahoo for this fund.")
    else:
        st.markdown("**Sector mix**")
        fig = px.bar(sectors, x="Weight", y="Sector", orientation="h", hover_data={"Weight": ":.1%"})
        fig.update_layout(xaxis_tickformat=".1%", xaxis_title=None, yaxis_title=None,
                          yaxis_autorange="reversed")
        st.plotly_chart(fig)
    assets = e["asset_mix"]
    if not assets.empty:
        st.caption("Assets: " + ", ".join(f"{c} {pct(w)}" for c, w in assets.itertuples(index=False)))
    st.caption("Country mix: not provided by Yahoo")

    draw_links(r)

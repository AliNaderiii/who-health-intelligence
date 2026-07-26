"""
WHO Global Health Intelligence Platform — Streamlit Dashboard (Production LIVE mode)

Implements production requirements:
- Top status panel with data mode LIVE/DEMO/STALE REAL DATA, API status, last extraction, source, records, countries, year range, quality status
- Colors: Green live healthy, Amber stale cached, Red failed/unavailable
- Refresh Data button triggering real API refresh with progress, success/failure reporting, extraction timestamp, cache clearing, no duplicates
- Streamlit caching with configurable TTL (WHO_REFRESH_TTL)
- Graceful handling of LIVE failure with no cached snapshot: error, API status, fix instructions, no synthetic data
- Stale fallback labeled STALE REAL DATA with original timestamp and failure reason
- DEMO mode explicitly banner: DEMO DATA — NOT OFFICIAL WHO OBSERVATIONS
- Correct aggregation wording: unweighted country-level average vs population-weighted only if available
- Correlation labeled as descriptive association, not causal
- Uses Automated Analytical Summary, Data-Driven Observation (not AI Insight) unless real ML model exists
- All data logic in services.py, UI orchestration only here
"""

from __future__ import annotations

import sys
from pathlib import Path

# Streamlit runs this file as a script, so only its own directory is on sys.path.
# Both the repository root (for ``src.*`` imports) and ``src`` (for the
# ``who_health_intelligence`` package) must be added explicitly, otherwise the
# app crashes on import when it is launched without a preset PYTHONPATH — which
# is exactly how Streamlit Community Cloud starts it.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent  # <repo>/src
_PROJECT_ROOT = _PACKAGE_ROOT.parent  # <repo>
for _path in (str(_PROJECT_ROOT), str(_PACKAGE_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

from who_health_intelligence.dashboard import services as svc
from who_health_intelligence.utils.config import (
    DATABASE_PATH,
    DASHBOARD_TITLE,
    DASHBOARD_SUBTITLE,
    WHO_API_BASE_URL,
    WHO_REFRESH_TTL,
    WHO_INDICATORS,
    REPORTS_DIR,
)
from who_health_intelligence.utils.data_mode import get_current_data_mode, DataMode

# Page config must be first Streamlit call
st.set_page_config(
    page_title=DASHBOARD_TITLE,
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1a1a2e; }
.stApp { background-color: #f7f8fc; }
h1 { font-weight: 700; font-size: 1.8rem; color: #0f172a; margin-bottom: 0.2rem; }
h2 { font-weight: 600; font-size: 1.25rem; color: #1e293b; margin-top: 1.2rem; }
h3 { font-weight: 600; font-size: 1rem; color: #334155; }
div[data-testid="metric-container"] { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 1rem 1.2rem; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
.panel-info { background: #eff6ff; border-left: 4px solid #3b82f6; padding: 0.8rem 1rem; border-radius: 6px; margin: 0.8rem 0; font-size: 0.92rem; }
.panel-warning { background: #fffbeb; border-left: 4px solid #f59e0b; padding: 0.8rem 1rem; border-radius: 6px; margin: 0.8rem 0; font-size: 0.92rem; }
.panel-success { background: #f0fdf4; border-left: 4px solid #22c55e; padding: 0.8rem 1rem; border-radius: 6px; margin: 0.8rem 0; font-size: 0.92rem; }
.panel-danger { background: #fef2f2; border-left: 4px solid #ef4444; padding: 0.8rem 1rem; border-radius: 6px; margin: 0.8rem 0; font-size: 0.92rem; }
.panel-neutral { background: #f8fafc; border-left: 4px solid #94a3b8; padding: 0.8rem 1rem; border-radius: 6px; margin: 0.8rem 0; font-size: 0.92rem; }
.panel-live { background: #f0fdf4; border: 2px solid #22c55e; border-radius: 10px; padding: 1rem; margin: 0.8rem 0; }
.panel-demo { background: #fef9c3; border: 2px solid #eab308; border-radius: 10px; padding: 1rem; margin: 0.8rem 0; }
.panel-stale { background: #fffbeb; border: 2px solid #f59e0b; border-radius: 10px; padding: 1rem; margin: 0.8rem 0; }
.panel-failed { background: #fef2f2; border: 2px solid #ef4444; border-radius: 10px; padding: 1rem; margin: 0.8rem 0; }
section[data-testid="stSidebar"] h2 { font-size: 1.1rem; margin-top: 0.5rem; }
.js-plotly-plot { border-radius: 10px; }
</style>
""", unsafe_allow_html=True)

# Header
st.markdown(f"## 🏥 {DASHBOARD_TITLE}")
st.markdown(f"<span style='color:#64748b; font-size:0.95rem'>{DASHBOARD_SUBTITLE}</span>", unsafe_allow_html=True)

st.markdown(
    '<div class="panel-neutral">'
    "<strong>Scope:</strong> Descriptive analytics and data exploration from WHO Global Health Observatory. "
    "No validated predictive models are included. This is <em>Public Health Data Engineering, Epidemiological Analytics, and Interactive Business Intelligence</em>."
    "</div>",
    unsafe_allow_html=True,
)

# ------------------------------------------------------------------
# Data loading with caching TTL from env
# ------------------------------------------------------------------
#
# IMPORTANT (Streamlit Cloud startup): no extraction work happens at import
# time. The app shell above is rendered first, then this controlled loader runs
# inside a visible status container. It reads the local snapshot and only
# performs a real WHO API request when LIVE mode has no snapshot at all.
@st.cache_data(show_spinner=False, ttl=WHO_REFRESH_TTL)
def _cached_load(db_path: str):
    return svc.load_dashboard_data(db_path)


_startup_status = st.empty()
_needs_live_fetch = (
    get_current_data_mode() == DataMode.LIVE
    and svc.auto_bootstrap_enabled()
    and not svc.database_has_records(str(DATABASE_PATH))
)

if _needs_live_fetch:
    _startup_status.info(
        "⏳ Starting up — no local WHO snapshot found. Requesting LIVE data from "
        f"`{WHO_API_BASE_URL}`. This first load can take up to a few minutes."
    )
else:
    _startup_status.info("⏳ Loading health data …")

with st.spinner("Loading health data …"):
    df, db_meta = _cached_load(str(DATABASE_PATH))

_startup_status.empty()

# ------------------------------------------------------------------
# Data mode and status handling
# ------------------------------------------------------------------
current_mode = get_current_data_mode()

# If the controlled loader attempted a live extraction and it failed, propagate
# the reason so the status panel can render STALE REAL DATA / LIVE DATA
# UNAVAILABLE instead of an unqualified LIVE label.
_bootstrap_result = db_meta.get("bootstrap_result") or {}
_startup_failure_reason = (
    None if _bootstrap_result.get("success", True) else _bootstrap_result.get("failure_reason")
)
data_status = svc.get_data_mode_status(
    str(DATABASE_PATH), api_failure_reason=_startup_failure_reason
)

# Determine status colors and banners
data_mode_label = data_status.get("data_mode", db_meta.get("data_mode", "UNKNOWN"))
api_status_label = data_status.get("api_status", "Unknown")
last_extraction = data_status.get("last_extraction") or db_meta.get("extraction_date") or "Not recorded"
source_label = data_status.get("source", "WHO GHO")
# For filtering, we need to ensure df and db_meta contain needed fields
n_records_meta = data_status.get("n_records", db_meta.get("row_count", 0))
n_countries_meta = data_status.get("n_countries", 0)
year_range_meta = data_status.get("year_range", db_meta.get("year_range", "N/A"))
quality_status_meta = data_status.get("quality_status", db_meta.get("quality_status", "Unknown"))
is_demo = data_status.get("is_demo", False) or db_meta.get("is_demo", False)
is_stale = data_status.get("is_stale", False) or db_meta.get("is_stale", False)
failure_reason = data_status.get("failure_reason")

# Compute mapping coverage for dashboard requirement
mapping_coverage = db_meta.get("mapping_coverage", {})
total_countries = mapping_coverage.get("total_countries", 0) if mapping_coverage else 0
mapped_countries = mapping_coverage.get("mapped_countries", 0) if mapping_coverage else 0
unmapped_countries = mapping_coverage.get("unmapped_countries", 0) if mapping_coverage else 0
mapping_pct = mapping_coverage.get("mapping_coverage_pct", 0) if mapping_coverage else 0

# Status panel logic with colors
if is_demo:
    # DEMO banner - explicit
    st.markdown(
        '<div class="panel-demo">'
        "<strong style='color:#a16207;'>⚠️ DEMO DATA — NOT OFFICIAL WHO OBSERVATIONS</strong><br>"
        "This dashboard is running in <strong>DEMO mode</strong> (WHO_DATA_MODE=demo). "
        "Data shown is synthetic/bootstrap data for local development and testing only. "
        "It must NOT be mistaken for live WHO Global Health Observatory observations.<br>"
        f"<small>Source: {source_label} | Records: {n_records_meta:,} | Year range: {year_range_meta}</small>"
        "</div>",
        unsafe_allow_html=True,
    )
    status_color = "amber"
elif is_stale:
    st.markdown(
        '<div class="panel-stale">'
        "<strong style='color:#92400e;'>⚠️ STALE REAL DATA</strong><br>"
        f"Live API refresh failed. Showing previously cached <strong>real WHO snapshot</strong>.<br>"
        f"<strong>Original extraction timestamp:</strong> {last_extraction}<br>"
        f"<strong>API failure reason:</strong> {failure_reason or data_status.get('failure_reason') or 'Unknown - check logs'}<br>"
        f"<small>Source: {source_label} | Records: {n_records_meta:,} | Countries: {n_countries_meta} | Year range: {year_range_meta} | Quality: {quality_status_meta}</small><br>"
        "<em>To fix: Check network connectivity, WHO API availability at https://ghoapi.azureedge.net/api/, and use Refresh Data button.</em>"
        "</div>",
        unsafe_allow_html=True,
    )
    status_color = "amber"
elif api_status_label in ("Failed", "FAILED") or db_meta.get("status") == "error":
    st.markdown(
        '<div class="panel-failed">'
        "<strong style='color:#b91c1c;'>🔴 LIVE DATA UNAVAILABLE</strong><br>"
        "No cached real snapshot exists and live WHO API extraction failed.<br>"
        f"<strong>Failed API status:</strong> {api_status_label}<br>"
        f"<strong>Reason:</strong> {failure_reason or db_meta.get('error') or 'Unknown'}<br>"
        "<strong>How to fix:</strong><br>"
        "- Check internet connectivity and firewall (allow https://ghoapi.azureedge.net/api/)<br>"
        "- Verify WHO API status: try <code>python main.py validate-api</code><br>"
        "- Retry with Refresh Data button below<br>"
        "- If persistent, check logs in <code>logs/</code> and reports in <code>reports/data_quality_report.json</code><br>"
        "<em>This production deployment never displays synthetic data in LIVE mode.</em>"
        "</div>",
        unsafe_allow_html=True,
    )
    status_color = "red"
else:
    # LIVE healthy
    st.markdown(
        '<div class="panel-live">'
        "<strong style='color:#15803d;'>🟢 LIVE - Real WHO Data</strong><br>"
        f"<span><strong>Data mode:</strong> {data_mode_label} | <strong>API status:</strong> {api_status_label} "
        f"| <strong>Last successful extraction:</strong> {last_extraction}</span><br>"
        f"<small><strong>Data source:</strong> {source_label} | <strong>Records:</strong> {n_records_meta:,} "
        f"| <strong>Countries:</strong> {n_countries_meta} | <strong>Year range:</strong> {year_range_meta} "
        f"| <strong>Quality:</strong> {quality_status_meta} | <strong>Mapping:</strong> {mapped_countries}/{total_countries} "
        f"({mapping_pct}%)</small>"
        "</div>",
        unsafe_allow_html=True,
    )
    status_color = "green"

# Detailed status panel (always visible per requirements)
st.markdown("### 📊 Data Status Panel")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Data Mode", data_mode_label)
col2.metric("API Status", api_status_label)
col3.metric("Last Extraction", str(last_extraction)[:19] if last_extraction else "N/A")
col4.metric("Quality Status", quality_status_meta)

col5, col6, col7, col8 = st.columns(4)
col5.metric("Records", f"{n_records_meta:,}")
col6.metric("Countries", n_countries_meta)
col7.metric("Year Range", year_range_meta)
col8.metric("Mapping Coverage", f"{mapping_pct}%" if mapping_pct else "N/A")

# Show mapping details
if mapping_coverage:
    with st.expander("🌍 Geographic Mapping Coverage Details", expanded=False):
        st.write(f"**Total countries in dataset:** {total_countries}")
        st.write(f"**Mapped countries:** {mapped_countries}")
        st.write(f"**Unmapped countries:** {unmapped_countries}")
        st.write(f"**Coverage percentage:** {mapping_pct}%")
        if mapping_coverage.get("unmapped_codes"):
            st.write(f"**Unmapped codes:** {mapping_coverage['unmapped_codes'][:20]}")
        st.caption("Geography mapping uses ISO 3166-1 alpha-3 via pycountry (if available) with internal WHO member state fallback. Unmapped codes tracked in data-quality report.")

# ------------------------------------------------------------------
# Refresh Data button
# ------------------------------------------------------------------
st.markdown("### 🔄 Data Refresh (LIVE mode)")

if st.button("🔄 Refresh Data from WHO API (LIVE)", help="Trigger real API refresh, show progress, clear caches, never duplicate records"):
    # Only allow refresh in LIVE mode or if explicitly demo? Per spec, button must trigger real API refresh
    # We'll call service that uses WHOETLPipeline
    with st.spinner("Refreshing live data from WHO GHO API … This may take 1-3 minutes."):
        # Clear cache first to ensure fresh load after refresh
        result = svc.trigger_live_refresh(db_path=str(DATABASE_PATH))

        if result.get("success"):
            st.success(f"✅ Refresh successful! Status: {result.get('status')} | Records loaded: {result.get('records_loaded')} | Extraction: {result.get('extraction_timestamp')} | Quality score: {result.get('quality_score')}")
            if result.get("stale_fallback_used"):
                st.warning(f"⚠️ Stale fallback was used: {result.get('failure_reason')}")
        else:
            st.error(f"❌ Refresh failed: {result.get('failure_reason')} | Status: {result.get('status')}")
            st.info("If no cached real snapshot exists, dashboard will show error and no synthetic data. Fix: check network, WHO API availability, retry.")

        # Clear Streamlit caches to reload fresh data
        st.cache_data.clear()
        st.info("Caches cleared. Reloading data…")
        # Rerun to reload
        st.rerun()

# Show last quality report if available (resolved from config, never a hardcoded local path)
_quality_report_path = Path(REPORTS_DIR) / "data_quality_report.json"
if _quality_report_path.exists():
    with st.expander("📋 Latest Data Quality Report (JSON snapshot)", expanded=False):
        try:
            import json
            q_content = json.loads(_quality_report_path.read_text(encoding="utf-8"))
            st.json(q_content)
        except Exception as e:
            st.write(f"Could not load quality report JSON: {e}")

# ------------------------------------------------------------------
# Graceful failure handling if df empty
# ------------------------------------------------------------------
if df.empty:
    error_msg = db_meta.get("error", "The database is missing or empty.")
    if is_demo:
        st.error(f"**Data unavailable in DEMO mode.** {error_msg}")
    elif is_stale:
        # Already shown stale banner, but still error if df truly empty (should not happen in stale mode)
        st.error(f"**No data available even for stale fallback.** {error_msg}")
    else:
        # LIVE failure with no cached snapshot
        st.error(f"**LIVE DATA UNAVAILABLE.** {error_msg}")
        st.markdown(
            '<div class="panel-danger">'
            "<strong>LIVE mode failed and no previously cached real snapshot exists.</strong><br>"
            "- Stopping dashboard gracefully per production requirements<br>"
            "- Showing clear error message and failed API status<br>"
            "- Explaining how to fix the issue<br>"
            "- <strong>Not displaying synthetic data</strong><br><br>"
            f"<strong>API endpoint:</strong> {WHO_API_BASE_URL}<br>"
            f"<strong>API status:</strong> {api_status_label}<br>"
            f"<strong>Failure reason:</strong> {failure_reason or error_msg}<br><br>"
            "<strong>How to fix:</strong><br>"
            "1. Check internet / firewall allows https://ghoapi.azureedge.net/api/<br>"
            "2. Run <code>python main.py validate-api</code> to test endpoint<br>"
            "3. Run ETL manually: <code>WHO_DATA_MODE=live python main.py etl</code><br>"
            "4. Check logs in <code>logs/</code> and quality report in <code>reports/data_quality_report.json</code><br>"
            "5. For Streamlit Cloud: note that local SQLite file is not persistent; real API extraction will be attempted on each deploy<br>"
            "</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="panel-info">'
            "<strong>To load data (LIVE):</strong><br>"
            "<code>WHO_DATA_MODE=live python main.py etl</code><br><br>"
            "<strong>To load DEMO data (explicit):</strong><br>"
            "<code>WHO_DATA_MODE=demo python scripts/bootstrap_data.py</code> or "
            "<code>WHO_DATA_MODE=demo python main.py etl --demo</code><br>"
            "<em>DEMO banner will be clearly shown.</em>"
            "</div>",
            unsafe_allow_html=True,
        )
    st.stop()

# ------------------------------------------------------------------
# Compute filter options (cached)
# ------------------------------------------------------------------
@st.cache_data(ttl=WHO_REFRESH_TTL)
def _filter_options(df_snapshot: pd.DataFrame):
    return svc.get_filter_options(df_snapshot)

opts = _filter_options(df)

# ------------------------------------------------------------------
# Sidebar filters
# ------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Filters")
    selected_indicators = st.multiselect(
        "Indicators",
        options=opts["indicators"],
        default=opts["indicators"],
        format_func=svc.indicator_short_name,
        help="Select one or more health indicators to analyse.",
    )
    if opts["years"]:
        if len(opts["years"]) == 1:
            year_range = (opts["years"][0], opts["years"][0])
            st.text(f"Year: {opts['years'][0]} (only year available)")
        else:
            year_range = st.slider(
                "Year range",
                min_value=int(opts["years"][0]),
                max_value=int(opts["years"][-1]),
                value=(int(opts["years"][0]), int(opts["years"][-1])),
            )
    else:
        year_range = (2000, 2023)

    continent_choices = ["All"] + opts["continents"]
    selected_continent = st.selectbox("Region", options=continent_choices, help="Filter by continent.")

    country_codes_all = [c[0] for c in opts["countries"]]
    country_labels = {c[0]: c[1] for c in opts["countries"]}
    selected_countries = st.multiselect(
        "Countries (optional)",
        options=country_codes_all,
        default=[],
        format_func=lambda c: country_labels.get(c, c),
        help="Leave empty for all countries. Max 50.",
        max_selections=50,
    )

    selected_genders = st.multiselect(
        "Demographic group", options=opts["genders"], default=opts["genders"], help="Select demographic groups."
    )

    st.divider()
    source_meta = svc.get_data_source_metadata(db_meta, df)
    st.markdown("#### Data source")
    st.caption(f"**{source_meta['source']}**")
    st.caption(f"API: `{source_meta['api']}`")
    if source_meta["extraction_date"]:
        st.caption(f"Extracted: {source_meta['extraction_date']}")
    st.caption(f"Years: {source_meta['year_range']}  ·  Records: {source_meta['total_records']:,}")
    st.caption(f"Mode: {source_meta.get('data_mode','')} | API: {source_meta.get('api_status','')}")

# ------------------------------------------------------------------
# Apply filters
# ------------------------------------------------------------------
continents_filter = None if selected_continent == "All" else [selected_continent]

filtered_df = svc.apply_filters(
    df,
    indicators=selected_indicators if selected_indicators else None,
    year_range=year_range,
    countries=selected_countries if selected_countries else None,
    continents=continents_filter,
    genders=selected_genders if selected_genders else None,
)

if filtered_df.empty:
    st.warning("No data matches current filters. Try broadening selection.")
    st.stop()

# Data summary
st.markdown(svc.build_data_summary(filtered_df, db_meta))

# KPI Cards
latest_year = int(filtered_df["Year"].max()) if "Year" in filtered_df.columns else int(filtered_df["year"].max())
kpis = svc.compute_kpis(filtered_df, df, latest_year)

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Countries reporting", f"{kpis['n_countries']}")
k2.metric("Indicators", f"{kpis['n_indicators']}")
k3.metric("Latest year", f"{kpis['selected_year']}")
k4.metric("Reporting coverage", f"{kpis['reporting_coverage_pct']:.1f}%")
k5.metric("Missing-value rate", f"{kpis['missing_value_rate_pct']:.2f}%")

st.divider()

# Automated Analytical Summary (not AI Insight)
primary_indicator = selected_indicators[0] if selected_indicators else None
if primary_indicator:
    avg = svc.compute_unweighted_average(filtered_df, primary_indicator, latest_year)
    if avg is not None:
        ind_name = svc.indicator_short_name(primary_indicator)
        st.markdown(
            f'<div class="panel-info">'
            f"<strong>Automated Analytical Summary:</strong> "
            f"In <strong>{latest_year}</strong>, the unweighted country-level average for "
            f"<em>{ind_name}</em> is <strong>{avg:.2f}</strong> across "
            f"<strong>{kpis['n_countries']}</strong> reporting countries. "
            f"Reporting coverage is {kpis['reporting_coverage_pct']:.1f}% of the dataset. "
            f"This is an <strong>unweighted country-level average</strong> (each country equal weight); "
            f"population-weighted averages require population data (not currently available)."
            f"</div>",
            unsafe_allow_html=True,
        )

# Tabs
tab_map, tab_rank, tab_trend, tab_compare, tab_profile, tab_dist, tab_corr, tab_data = st.tabs(
    ["🗺️ Geographic", "🏆 Ranking", "📈 Trend", "📊 Comparison", "🏳️ Country Profile", "📉 Distribution", "🔗 Association", "📋 Data Explorer"]
)

with tab_map:
    st.markdown("### Global Choropleth Map")
    if primary_indicator is None:
        st.info("Select at least one indicator.")
    else:
        indicator_sel = st.selectbox("Indicator for map", selected_indicators, format_func=svc.indicator_short_name, key="map_indicator") if len(selected_indicators) > 1 else primary_indicator
        map_year = st.slider("Year", min_value=int(filtered_df["Year"].min()), max_value=int(filtered_df["Year"].max()), value=min(latest_year, int(filtered_df["Year"].max())), key="map_year")
        geo_df = svc.build_geospatial_data(filtered_df, indicator_sel, map_year)

        if geo_df.empty:
            st.info("No geographic data for this selection.")
        else:
            hover_cols = {"Value": ":.2f", "Continent": True, "CountryCode": False}
            color_scale = "RdYlGn_r" if "MORTALITY" in indicator_sel else "RdYlGn"
            fig = px.choropleth(
                geo_df, locations="CountryCode", color="Value",
                hover_name="Country" if "Country" in geo_df.columns else "CountryCode",
                hover_data=hover_cols,
                color_continuous_scale=color_scale,
                labels={"Value": svc.indicator_description(indicator_sel)},
                height=520,
            )
            fig.update_layout(geo=dict(showframe=True, showcoastlines=True, projection_type="natural earth"), margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)

            if "Continent" in geo_df.columns:
                cont_agg = geo_df.groupby("Continent")["Value"].agg(["mean", "median", "min", "max", "count"]).round(2).reset_index()
                cont_agg.columns = ["Region", "Mean", "Median", "Min", "Max", "Countries"]
                st.markdown("##### Unweighted regional averages (each country equal weight)")
                st.caption("Population-weighted averages require population data (not currently available).")
                st.dataframe(cont_agg, use_container_width=True, hide_index=True)

with tab_rank:
    st.markdown("### Country Ranking")
    if not selected_indicators:
        st.info("Select at least one indicator.")
    else:
        rank_indicator = st.selectbox("Rank by", selected_indicators, format_func=svc.indicator_short_name, key="rank_indicator")
        rank_year = st.slider("Year", min_value=int(filtered_df["Year"].min()), max_value=int(filtered_df["Year"].max()), value=min(latest_year, int(filtered_df["Year"].max())), key="rank_year")
        rank_n = st.slider("Show top N", 5, 50, 20, key="rank_n")
        is_mortality = "MORTALITY" in rank_indicator
        rank_df = svc.build_ranking_data(filtered_df, rank_indicator, rank_year, top_n=rank_n, ascending=not is_mortality)

        if rank_df.empty:
            st.info("No data for ranking.")
        else:
            name_col = "Country" if "Country" in rank_df.columns else "CountryCode"
            fig = px.bar(rank_df, x="Value", y=name_col, orientation="h", color="Value", color_continuous_scale="RdYlGn_r" if is_mortality else "RdYlGn", labels={"Value": svc.indicator_short_name(rank_indicator)}, height=max(350, rank_n * 22))
            fig.update_layout(yaxis={"categoryorder": "total ascending"}, showlegend=False, margin=dict(l=0, r=10, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)

with tab_trend:
    st.markdown("### Time-Series Trend (Unweighted country-level average)")
    st.caption("Each country weighted equally. Population-weighted averages require population data.")
    if not selected_indicators:
        st.info("Select at least one indicator.")
    else:
        for indicator in selected_indicators:
            st.markdown(f"##### {svc.indicator_short_name(indicator)}")
            st.caption(svc.indicator_description(indicator) + f" | Unit: {svc.indicator_unit(indicator)} | Sample size varies by year")
            ts = svc.build_time_series_data(filtered_df, indicator)
            if ts.empty:
                st.info("No temporal data.")
                continue
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=ts["Year"], y=ts["mean"], mode="lines+markers", name="Unweighted mean", line=dict(color="#2563eb", width=2.5), marker=dict(size=5)))
            fig.add_trace(go.Scatter(x=ts["Year"], y=ts["mean"] + ts["std"], mode="lines", line=dict(width=0), showlegend=False))
            fig.add_trace(go.Scatter(x=ts["Year"], y=ts["mean"] - ts["std"], mode="lines", line=dict(width=0), fill="tonexty", fillcolor="rgba(37,99,235,0.10)", name="±1 SD band"))
            fig.update_layout(xaxis_title="Year", yaxis_title=svc.indicator_description(indicator), height=370, template="plotly_white", margin=dict(l=50, r=20, t=15, b=40), legend=dict(orientation="h", y=1.08))
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Unweighted country-level average: each country counted equally. Population-weighted average only if population data available.")

            st.markdown("**Selected-country trends**")
            country_ts = svc.build_country_time_series(filtered_df, indicator, top_n=8)
            if not country_ts.empty:
                name_col = "Country" if "Country" in country_ts.columns else "CountryCode"
                fig2 = px.line(country_ts, x="Year", y="Value", color=name_col, labels={"Value": svc.indicator_short_name(indicator)}, height=320)
                fig2.update_layout(template="plotly_white", margin=dict(l=50, r=20, t=10, b=40), legend=dict(orientation="h", y=-0.25))
                st.plotly_chart(fig2, use_container_width=True)

with tab_compare:
    st.markdown("### Indicator Comparison (Single Year)")
    st.caption("Compare indicator values across countries in a single year.")
    if len(selected_indicators) < 2:
        st.info("Select at least two indicators.")
    else:
        comp_year = st.slider("Year", min_value=int(filtered_df["Year"].min()), max_value=int(filtered_df["Year"].max()), value=min(latest_year, int(filtered_df["Year"].max())), key="comp_year")
        year_data = filtered_df[filtered_df["Year"] == comp_year]
        if "Both sexes" in year_data["Gender"].values:
            year_data = year_data[year_data["Gender"] == "Both sexes"]
        pivot = year_data.pivot_table(index="CountryCode", columns="Indicator", values="Value", aggfunc="mean")
        if "Country" in year_data.columns:
            name_map = year_data[["CountryCode", "Country"]].drop_duplicates().set_index("CountryCode")["Country"]
            pivot.insert(0, "Country", pivot.index.map(name_map))
        pivot.columns = [svc.indicator_short_name(c) if c in svc.INDICATOR_SHORT_NAMES else c for c in pivot.columns]
        st.dataframe(pivot.round(2), use_container_width=True, hide_index=True, height=400)

with tab_profile:
    st.markdown("### Country Profile")
    st.caption("Deep-dive into single country's time-series across all indicators.")
    country_codes_all = [c[0] for c in opts["countries"]]
    country_labels = {c[0]: c[1] for c in opts["countries"]}
    profile_country = st.selectbox("Select country", options=country_codes_all, format_func=lambda c: country_labels.get(c, c), key="profile_country")
    profile_df = svc.build_country_profile(filtered_df, profile_country)

    if profile_df.empty:
        st.info(f"No data for {country_labels.get(profile_country, profile_country)} with current filters.")
    else:
        country_name = country_labels.get(profile_country, profile_country)
        st.markdown(f"#### {country_name} ({profile_country})")
        for indicator in profile_df["Indicator"].unique():
            ind_data = profile_df[profile_df["Indicator"] == indicator].sort_values("Year")
            if ind_data.empty:
                continue
            st.markdown(f"**{svc.indicator_short_name(indicator)}** (n={len(ind_data)} observations)")
            fig = px.line(ind_data, x="Year", y="Value", labels={"Value": svc.indicator_description(indicator)}, height=250)
            fig.update_traces(line=dict(color="#2563eb", width=2))
            fig.update_layout(template="plotly_white", margin=dict(l=40, r=10, t=10, b=30))
            st.plotly_chart(fig, use_container_width=True)
            st.caption(f"Mean: {ind_data['Value'].mean():.2f} · Min: {ind_data['Value'].min():.2f} ({int(ind_data.loc[ind_data['Value'].idxmin(), 'Year'])}) · Max: {ind_data['Value'].max():.2f} ({int(ind_data.loc[ind_data['Value'].idxmax(), 'Year'])})")

with tab_dist:
    st.markdown("### Distribution Analysis")
    st.caption("Examine distribution of values across countries.")
    if not selected_indicators:
        st.info("Select at least one indicator.")
    else:
        dist_indicator = st.selectbox("Indicator", selected_indicators, format_func=svc.indicator_short_name, key="dist_indicator")
        dist_year = st.slider("Year", min_value=int(filtered_df["Year"].min()), max_value=int(filtered_df["Year"].max()), value=min(latest_year, int(filtered_df["Year"].max())), key="dist_year")
        dist_df = svc.build_distribution_data(filtered_df, dist_indicator, dist_year)

        if dist_df.empty:
            st.info("No data for this selection.")
        else:
            col_hist, col_box = st.columns(2)
            with col_hist:
                st.markdown("**Histogram**")
                fig_hist = px.histogram(dist_df, x="Value", nbins=25, color="Continent" if "Continent" in dist_df.columns else None, labels={"Value": svc.indicator_description(dist_indicator)}, height=350)
                fig_hist.update_layout(template="plotly_white", margin=dict(l=40, r=10, t=10, b=30))
                st.plotly_chart(fig_hist, use_container_width=True)
            with col_box:
                st.markdown("**Box plot by region**")
                if "Continent" in dist_df.columns:
                    fig_box = px.box(dist_df, x="Continent", y="Value", color="Continent", labels={"Value": svc.indicator_short_name(dist_indicator)}, height=350)
                else:
                    fig_box = px.box(dist_df, y="Value", labels={"Value": svc.indicator_short_name(dist_indicator)}, height=350)
                fig_box.update_layout(template="plotly_white", showlegend=False, margin=dict(l=40, r=10, t=10, b=30))
                st.plotly_chart(fig_box, use_container_width=True)

            st.markdown("**Summary statistics (unweighted country-level values)**")
            st.dataframe(dist_df["Value"].describe().round(2), use_container_width=True)

with tab_corr:
    st.markdown("### Statistical Association Analysis")
    st.markdown('<div class="panel-warning"><strong>Descriptive association, not causal inference.</strong> Association does not imply causation.</div>', unsafe_allow_html=True)
    if len(selected_indicators) < 2:
        st.info("Select at least two indicators.")
    else:
        st.markdown('<div class="panel-warning"><strong>Important:</strong> This view shows <em>statistical associations</em> between indicators. Association does not imply causation. Observed correlations may be driven by shared confounders (e.g. GDP, healthcare investment, data quality) and should not be interpreted as causal relationships.</div>', unsafe_allow_html=True)

        ind_x = st.selectbox("X-axis indicator", selected_indicators, format_func=svc.indicator_short_name, key="corr_x")
        remaining = [i for i in selected_indicators if i != ind_x]
        ind_y = st.selectbox("Y-axis indicator", remaining, format_func=svc.indicator_short_name, key="corr_y")
        corr_year = st.slider("Year", min_value=int(filtered_df["Year"].min()), max_value=int(filtered_df["Year"].max()), value=min(latest_year, int(filtered_df["Year"].max())), key="corr_year")

        corr_df, pearson_r = svc.build_correlation_data(filtered_df, ind_x, ind_y, corr_year)

        if corr_df.empty:
            st.info("Insufficient overlapping data.")
        else:
            fig = px.scatter(corr_df, x="Value_X", y="Value_Y", color="Continent" if "Continent" in corr_df.columns else None, hover_name="Country" if "Country" in corr_df.columns else "CountryCode", trendline="ols", labels={"Value_X": svc.indicator_short_name(ind_x), "Value_Y": svc.indicator_short_name(ind_y)}, height=480)
            fig.update_layout(template="plotly_white", margin=dict(l=50, r=20, t=10, b=40))
            st.plotly_chart(fig, use_container_width=True)

            abs_r = abs(pearson_r) if pearson_r == pearson_r else 0
            strength = "strong" if abs_r > 0.7 else "moderate" if abs_r > 0.4 else "weak"
            direction = "positive" if pearson_r > 0 else "negative"

            st.markdown(
                '<div class="panel-info">'
                f"<strong>Data-Driven Observation:</strong> Pearson <em>r</em> = <strong>{pearson_r:.3f}</strong> — a <em>{strength} {direction}</em> statistical association across {len(corr_df)} countries in {corr_year}.<br>"
                f"<strong>Method:</strong> Pearson correlation | <strong>Missing handling:</strong> pairwise deletion | <strong>Year:</strong> {corr_year} | <strong>Indicators:</strong> {svc.indicator_short_name(ind_x)} vs {svc.indicator_short_name(ind_y)}<br>"
                f"This is a <strong>descriptive association, not causal inference</strong>."
                "</div>",
                unsafe_allow_html=True,
            )

with tab_data:
    st.markdown("### Data Explorer")
    display_cols_default = [c for c in ["Country", "CountryCode", "Year", "Gender", "Indicator", "Value", "Continent"] if c in filtered_df.columns]
    display_cols = st.multiselect("Columns", filtered_df.columns.tolist(), default=display_cols_default)
    if display_cols:
        st.dataframe(filtered_df[display_cols].sort_values(["Indicator", "CountryCode", "Year"]), use_container_width=True, hide_index=True, height=400)

    st.markdown("##### Summary statistics")
    st.dataframe(filtered_df.describe().round(3), use_container_width=True)

    csv_bytes = svc.build_export_csv(filtered_df[display_cols] if display_cols else filtered_df)
    st.download_button(label="📥  Download filtered data (CSV)", data=csv_bytes, file_name=f"who_health_data_{year_range[0]}-{year_range[1]}.csv", mime="text/csv")

# Methodology
with st.expander("ℹ️  Methodology & data sources", expanded=False):
    st.markdown("#### Data source")
    st.markdown(f"- **Provider:** {source_meta['source']}")
    st.markdown(f"- **API endpoint:** `{source_meta['api']}` (validated before implementation, configurable via WHO_API_BASE_URL)")
    st.markdown(f"- **Extraction date:** {source_meta['extraction_date'] or 'Not recorded'}")
    st.markdown(f"- **Year range:** {source_meta['year_range']}")
    st.markdown(f"- **Total records:** {source_meta['total_records']:,}")
    st.markdown(f"- **Data mode:** {source_meta.get('data_mode','')} | API status: {source_meta.get('api_status','')}")
    st.markdown("#### Indicator definitions (official WHO)")
    for ind_name in opts["indicators"]:
        st.markdown(f"- **{svc.indicator_short_name(ind_name)}** — {svc.indicator_official_definition(ind_name)} (unit: {svc.indicator_unit(ind_name)}) Source: {WHO_API_BASE_URL}{WHO_INDICATORS.get(ind_name,{}).get('code','')}")

    st.markdown("#### Aggregation method")
    st.markdown("All cross-country averages shown are **unweighted country-level averages** (each country counted equally). Population-weighted averages require population data, not currently included. If population data integrated, weighted averages will be clearly labeled as such. Do NOT call simple mean a global population-weighted average.")

    st.markdown("#### Missing data handling")
    st.markdown("- Records with missing values excluded from aggregation.\n- Countries with no data for given year omitted.\n- Missing-value rate KPI shows proportion of nulls in filtered dataset.")

    st.markdown("#### Geographic mapping")
    st.markdown("Country codes follow ISO 3166-1 alpha-3. Continent assignments use standard UN geographic regions plus pycountry where available. Some WHO aggregate codes excluded. Mapping coverage shown in status panel: total/mapped/unmapped/code coverage % tracked in data-quality report.")

    st.markdown('<div class="panel-warning"><strong>Disclaimer:</strong> This platform is descriptive analytics tool, not AI prediction system. Correlation does not imply causation. Not medical decision-support tool.</div>', unsafe_allow_html=True)

# Data Quality Panel
with st.expander("📊  Data quality & Responsible use", expanded=False):
    quality_report = svc.compute_quality_report(filtered_df)
    if "error" in quality_report:
        st.warning(f"Could not compute quality report: {quality_report['error']}")
    else:
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Quality score", f"{quality_report['overall_score']:.0f}/100")
        q2.metric("Completeness", f"{quality_report['completeness']['overall_completeness_pct']:.1f}%")
        q3.metric("Consistent", "Yes" if quality_report["consistency"]["is_consistent"] else "Issues found")
        q4.metric("Countries", quality_report["geographic_coverage"]["countries"])

        st.markdown("##### Per-column completeness")
        col_data = quality_report["completeness"]["per_column"]
        col_table = pd.DataFrame([{"Column": col, "Completeness": f"{v['completeness_score']:.1f}%", "Nulls": v["null_count"]} for col, v in col_data.items()])
        st.dataframe(col_table, use_container_width=True, hide_index=True)

        tc = quality_report["temporal_coverage"]
        st.markdown(f"**Temporal coverage:** {tc['years_covered']} years ({tc['year_range'][0]}–{tc['year_range'][1]}). {'Gaps: ' + str(tc['year_gaps']) if tc['has_gaps'] else 'No year gaps.'}")

    st.markdown("---")
    st.markdown("#### Responsible Use")
    st.markdown("""
- This dashboard is **not a medical decision-support tool**.
- It must **not be used for clinical diagnosis or treatment decisions**.
- WHO data may be revised; reporting gaps may exist.
- Country comparisons may be affected by methodology and availability.
- **Correlation does not imply causation**.
- Dashboard provides analytical context, not medical advice.
- Data freshness: shows extraction timestamp; stale real data labeled STALE REAL DATA with original timestamp and failure reason.
- Streamlit Cloud limitation: local SQLite file not persistent; real API extraction attempted on each deploy, with stale fallback if available.
- For persistent production, consider PostgreSQL, Supabase, S3-compatible object storage, or managed database.
""")
    st.markdown("**Medical disclaimer:** This tool is for public health data engineering and epidemiological analytics education only. Not for clinical decision-making.")
    st.markdown("**Correlation disclaimer:** All association analyses are descriptive, not causal. Do not interpret correlation as causation.")

# Footer
st.divider()
st.caption(f"{DASHBOARD_TITLE} · Data: WHO GHO · Descriptive analytics only · Data mode: {data_mode_label} · API: {api_status_label} · Last extraction: {last_extraction} · No AI prediction system")

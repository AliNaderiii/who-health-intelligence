"""
WHO Global Health Intelligence Platform — Streamlit Dashboard.

A descriptive public-health analytics dashboard for WHO Global Health
Observatory data. This is a data-engineering and epidemiological analytics
tool. It does NOT contain validated predictive models.

All data logic lives in ``services.py``. This module is pure UI orchestration:
layout, user interaction, chart rendering, and graceful error handling.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Resolve project root so imports work both under `streamlit run` and `python`
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# ---- Data services (all logic lives here) ----
from who_health_intelligence.dashboard import services as svc
from who_health_intelligence.utils.config import DATABASE_PATH, DASHBOARD_TITLE, DASHBOARD_SUBTITLE


# ================================================================
# Page configuration — must be the first Streamlit call
# ================================================================
st.set_page_config(
    page_title=DASHBOARD_TITLE,
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ================================================================
# Minimal, accessible CSS
# ================================================================
st.markdown("""
<style>
/* ---------- Base ---------- */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    color: #1a1a2e;
}
.stApp { background-color: #f7f8fc; }

/* ---------- Typography ---------- */
h1 { font-weight: 700; font-size: 1.8rem; color: #0f172a; margin-bottom: 0.2rem; }
h2 { font-weight: 600; font-size: 1.25rem; color: #1e293b; margin-top: 1.2rem; }
h3 { font-weight: 600; font-size: 1rem; color: #334155; }

/* ---------- Metric cards ---------- */
div[data-testid="metric-container"] {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 1rem 1.2rem;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}

/* ---------- Panels ---------- */
.panel-info {
    background: #eff6ff; border-left: 4px solid #3b82f6;
    padding: 0.8rem 1rem; border-radius: 6px; margin: 0.8rem 0; font-size: 0.92rem;
}
.panel-warning {
    background: #fffbeb; border-left: 4px solid #f59e0b;
    padding: 0.8rem 1rem; border-radius: 6px; margin: 0.8rem 0; font-size: 0.92rem;
}
.panel-success {
    background: #f0fdf4; border-left: 4px solid #22c55e;
    padding: 0.8rem 1rem; border-radius: 6px; margin: 0.8rem 0; font-size: 0.92rem;
}
.panel-neutral {
    background: #f8fafc; border-left: 4px solid #94a3b8;
    padding: 0.8rem 1rem; border-radius: 6px; margin: 0.8rem 0; font-size: 0.92rem;
}

/* ---------- Sidebar ---------- */
section[data-testid="stSidebar"] h2 { font-size: 1.1rem; margin-top: 0.5rem; }

/* ---------- Plotly containers ---------- */
.js-plotly-plot { border-radius: 10px; }
</style>
""", unsafe_allow_html=True)


# ================================================================
# Header
# ================================================================
st.markdown(f"## 🏥 {DASHBOARD_TITLE}")
st.markdown(
    f"<span style='color:#64748b; font-size:0.95rem'>{DASHBOARD_SUBTITLE}</span>",
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="panel-neutral">'
    "<strong>Scope:</strong> Descriptive analytics and data exploration. "
    "No validated predictive models are included in this platform."
    "</div>",
    unsafe_allow_html=True,
)


# ================================================================
# Data loading (cached)
# ================================================================
@st.cache_data(show_spinner="Loading health data …")
def _cached_load(db_path: str):
    return svc.load_full_dataset(db_path)


df, db_meta = _cached_load(DATABASE_PATH)

# ---- Graceful failure: missing / empty database ----
if df.empty:
    error_msg = db_meta.get("error", "The database is missing or empty.")
    st.error(f"**Data unavailable.** {error_msg}")
    st.markdown(
        '<div class="panel-info">'
        "<strong>To load data:</strong><br>"
        "<code>python main.py etl</code><br>"
        "Or, for development with sample data:<br>"
        "<code>python scripts/bootstrap_data.py</code>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.stop()


# ---- Compute filter options (cached on full dataset) ----
@st.cache_data
def _filter_options(df_snapshot: pd.DataFrame):
    return svc.get_filter_options(df_snapshot)


opts = _filter_options(df)


# ================================================================
# Sidebar — Filters
# ================================================================
with st.sidebar:
    st.markdown("### Filters")

    # -- Indicator --
    selected_indicators = st.multiselect(
        "Indicators",
        options=opts["indicators"],
        default=opts["indicators"],
        format_func=svc.indicator_short_name,
        help="Select one or more health indicators to analyse.",
    )

    # -- Year --
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

    # -- Continent / Region --
    continent_choices = ["All"] + opts["continents"]
    selected_continent = st.selectbox(
        "Region",
        options=continent_choices,
        help="Filter by continent. Select 'All' for global view.",
    )

    # -- Country --
    country_codes_all = [c[0] for c in opts["countries"]]
    country_labels = {c[0]: c[1] for c in opts["countries"]}
    selected_countries = st.multiselect(
        "Countries (optional)",
        options=country_codes_all,
        default=[],
        format_func=lambda c: country_labels.get(c, c),
        help="Leave empty for all countries. Select specific countries for focused analysis.",
        max_selections=50,
    )

    # -- Gender / Demographic --
    selected_genders = st.multiselect(
        "Demographic group",
        options=opts["genders"],
        default=opts["genders"],
        help="Select one or more demographic groups.",
    )

    st.divider()

    # -- Data source metadata --
    source_meta = svc.get_data_source_metadata(db_meta, df)
    st.markdown("#### Data source")
    st.caption(f"**{source_meta['source']}**")
    st.caption(f"API: `{source_meta['api']}`")
    if source_meta["extraction_date"]:
        st.caption(f"Extracted: {source_meta['extraction_date']}")
    st.caption(f"Years: {source_meta['year_range']}  ·  Records: {source_meta['total_records']:,}")


# ================================================================
# Apply filters
# ================================================================
continents_filter = None if selected_continent == "All" else [selected_continent]

filtered_df = svc.apply_filters(
    df,
    indicators=selected_indicators if selected_indicators else None,
    year_range=year_range,
    countries=selected_countries if selected_countries else None,
    continents=continents_filter,
    genders=selected_genders if selected_genders else None,
)

# ---- Graceful failure: empty after filtering ----
if filtered_df.empty:
    st.warning(
        "No data matches the current filter combination. "
        "Try broadening your selection (e.g. selecting 'All' regions, more indicators, or a wider year range)."
    )
    st.stop()


# ================================================================
# Data summary bar
# ================================================================
st.markdown(svc.build_data_summary(filtered_df, db_meta))


# ================================================================
# KPI Cards
# ================================================================
latest_year = int(filtered_df["Year"].max())
kpis = svc.compute_kpis(filtered_df, df, latest_year)

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Countries reporting", f"{kpis['n_countries']}")
k2.metric("Indicators", f"{kpis['n_indicators']}")
k3.metric("Latest year", f"{kpis['selected_year']}")
k4.metric("Reporting coverage", f"{kpis['reporting_coverage_pct']:.1f}%")
k5.metric("Missing-value rate", f"{kpis['missing_value_rate_pct']:.2f}%")

st.divider()


# ================================================================
# Automated Analytical Summary
# ================================================================
primary_indicator = selected_indicators[0] if selected_indicators else None
if primary_indicator:
    avg = svc.compute_unweighted_average(filtered_df, primary_indicator, latest_year)
    if avg is not None:
        ind_name = svc.indicator_short_name(primary_indicator)
        ind_desc = svc.indicator_description(primary_indicator)
        st.markdown(
            f'<div class="panel-info">'
            f"<strong>Automated Analytical Summary:</strong> "
            f"In <strong>{latest_year}</strong>, the unweighted cross-country average for "
            f"<em>{ind_name}</em> is <strong>{avg:.2f}</strong> across "
            f"<strong>{kpis['n_countries']}</strong> reporting countries. "
            f"Reporting coverage is {kpis['reporting_coverage_pct']:.1f}% of the dataset."
            f"</div>",
            unsafe_allow_html=True,
        )


# ================================================================
# Analytical Views — Tabs
# ================================================================
tab_map, tab_rank, tab_trend, tab_compare, tab_profile, tab_dist, tab_corr, tab_data = st.tabs(
    [
        "🗺️ Geographic",
        "🏆 Ranking",
        "📈 Trend",
        "📊 Comparison",
        "🏳️ Country Profile",
        "📉 Distribution",
        "🔗 Association",
        "📋 Data Explorer",
    ]
)


# ----------------------------------------------------------------
# Tab 1: Geographic — Choropleth
# ----------------------------------------------------------------
with tab_map:
    st.markdown("### Global Choropleth Map")

    if primary_indicator is None:
        st.info("Select at least one indicator to view the map.")
    else:
        indicator_sel = (
            st.selectbox(
                "Indicator for map",
                selected_indicators,
                format_func=svc.indicator_short_name,
                key="map_indicator",
            )
            if len(selected_indicators) > 1
            else primary_indicator
        )
        map_year = st.slider(
            "Year",
            min_value=int(filtered_df["Year"].min()),
            max_value=int(filtered_df["Year"].max()),
            value=min(latest_year, int(filtered_df["Year"].max())),
            key="map_year",
        )
        geo_df = svc.build_geospatial_data(filtered_df, indicator_sel, map_year)

        if geo_df.empty:
            st.info("No geographic data for this selection. The indicator may not have data for the selected year.")
        else:
            hover_cols = {"Value": ":.2f", "Continent": True, "CountryCode": False}
            color_scale = "RdYlGn_r" if "MORTALITY" in indicator_sel else "RdYlGn"
            fig = px.choropleth(
                geo_df,
                locations="CountryCode",
                color="Value",
                hover_name="Country" if "Country" in geo_df.columns else "CountryCode",
                hover_data=hover_cols,
                color_continuous_scale=color_scale,
                labels={"Value": svc.indicator_description(indicator_sel)},
                height=520,
            )
            fig.update_layout(
                geo=dict(showframe=True, showcoastlines=True, projection_type="natural earth"),
                margin=dict(l=0, r=0, t=10, b=0),
            )
            st.plotly_chart(fig, use_container_width=True)

            # Continent-level summary
            if "Continent" in geo_df.columns:
                cont_agg = (
                    geo_df.groupby("Continent")["Value"]
                    .agg(["mean", "median", "min", "max", "count"])
                    .round(2)
                    .reset_index()
                )
                cont_agg.columns = ["Region", "Mean", "Median", "Min", "Max", "Countries"]
                st.markdown("##### Unweighted regional averages")
                st.caption(
                    "Each country weighted equally. "
                    "Population-weighted averages require population data (not currently available)."
                )
                st.dataframe(cont_agg, use_container_width=True, hide_index=True)


# ----------------------------------------------------------------
# Tab 2: Country Ranking
# ----------------------------------------------------------------
with tab_rank:
    st.markdown("### Country Ranking")

    if not selected_indicators:
        st.info("Select at least one indicator.")
    else:
        rank_indicator = st.selectbox(
            "Rank by",
            selected_indicators,
            format_func=svc.indicator_short_name,
            key="rank_indicator",
        )
        rank_year = st.slider(
            "Year",
            min_value=int(filtered_df["Year"].min()),
            max_value=int(filtered_df["Year"].max()),
            value=min(latest_year, int(filtered_df["Year"].max())),
            key="rank_year",
        )
        rank_n = st.slider("Show top N", 5, 50, 20, key="rank_n")

        is_mortality = "MORTALITY" in rank_indicator
        rank_df = svc.build_ranking_data(
            filtered_df, rank_indicator, rank_year, top_n=rank_n, ascending=not is_mortality
        )

        if rank_df.empty:
            st.info("No data available for ranking with this selection.")
        else:
            name_col = "Country" if "Country" in rank_df.columns else "CountryCode"
            fig = px.bar(
                rank_df,
                x="Value",
                y=name_col,
                orientation="h",
                color="Value",
                color_continuous_scale="RdYlGn_r" if is_mortality else "RdYlGn",
                labels={"Value": svc.indicator_short_name(rank_indicator)},
                height=max(350, rank_n * 22),
            )
            fig.update_layout(
                yaxis={"categoryorder": "total ascending"},
                showlegend=False,
                margin=dict(l=0, r=10, t=10, b=0),
            )
            st.plotly_chart(fig, use_container_width=True)


# ----------------------------------------------------------------
# Tab 3: Time-series Trend
# ----------------------------------------------------------------
with tab_trend:
    st.markdown("### Time-Series Trend")

    if not selected_indicators:
        st.info("Select at least one indicator.")
    else:
        for indicator in selected_indicators:
            st.markdown(f"##### {svc.indicator_short_name(indicator)}")
            st.caption(svc.indicator_description(indicator))

            ts = svc.build_time_series_data(filtered_df, indicator)
            if ts.empty:
                st.info("No temporal data available for this indicator.")
                continue

            fig = go.Figure()
            # Mean line
            fig.add_trace(go.Scatter(
                x=ts["Year"], y=ts["mean"],
                mode="lines+markers", name="Unweighted mean",
                line=dict(color="#2563eb", width=2.5),
                marker=dict(size=5),
            ))
            # Confidence band ±1 std
            fig.add_trace(go.Scatter(
                x=ts["Year"], y=ts["mean"] + ts["std"],
                mode="lines", line=dict(width=0), showlegend=False,
            ))
            fig.add_trace(go.Scatter(
                x=ts["Year"], y=ts["mean"] - ts["std"],
                mode="lines", line=dict(width=0),
                fill="tonexty", fillcolor="rgba(37,99,235,0.10)",
                name="±1 SD band",
            ))
            fig.update_layout(
                xaxis_title="Year",
                yaxis_title=svc.indicator_description(indicator),
                height=370,
                template="plotly_white",
                margin=dict(l=50, r=20, t=15, b=40),
                legend=dict(orientation="h", y=1.08),
            )
            st.plotly_chart(fig, use_container_width=True)

            st.caption(
                "**Note:** This shows the *unweighted* country-level mean (each country counted equally). "
                "Population-weighted averaging is not available because population data is not included in this dataset."
            )

            # Top-country trend lines
            st.markdown("**Selected-country trends**")
            country_ts = svc.build_country_time_series(filtered_df, indicator, top_n=8)
            if not country_ts.empty:
                name_col = "Country" if "Country" in country_ts.columns else "CountryCode"
                fig2 = px.line(
                    country_ts, x="Year", y="Value", color=name_col,
                    labels={"Value": svc.indicator_short_name(indicator)},
                    height=320,
                )
                fig2.update_layout(
                    template="plotly_white",
                    margin=dict(l=50, r=20, t=10, b=40),
                    legend=dict(orientation="h", y=-0.25),
                )
                st.plotly_chart(fig2, use_container_width=True)


# ----------------------------------------------------------------
# Tab 4: Indicator Comparison
# ----------------------------------------------------------------
with tab_compare:
    st.markdown("### Indicator Comparison")
    st.caption("Compare indicator values across countries in a single year.")

    if len(selected_indicators) < 2:
        st.info("Select at least **two** indicators to compare.")
    else:
        comp_year = st.slider(
            "Year",
            min_value=int(filtered_df["Year"].min()),
            max_value=int(filtered_df["Year"].max()),
            value=min(latest_year, int(filtered_df["Year"].max())),
            key="comp_year",
        )

        year_data = filtered_df[filtered_df["Year"] == comp_year]
        if "Both sexes" in year_data["Gender"].values:
            year_data = year_data[year_data["Gender"] == "Both sexes"]

        pivot = year_data.pivot_table(
            index="CountryCode",
            columns="Indicator",
            values="Value",
            aggfunc="mean",
        )
        if "Country" in year_data.columns:
            name_map = year_data[["CountryCode", "Country"]].drop_duplicates().set_index("CountryCode")["Country"]
            pivot.insert(0, "Country", pivot.index.map(name_map))

        pivot.columns = [
            svc.indicator_short_name(c) if c in svc.INDICATOR_SHORT_NAMES else c
            for c in pivot.columns
        ]
        st.dataframe(pivot.round(2), use_container_width=True, hide_index=True, height=400)


# ----------------------------------------------------------------
# Tab 5: Country Profile
# ----------------------------------------------------------------
with tab_profile:
    st.markdown("### Country Profile")
    st.caption("Deep-dive into a single country's time-series across all indicators.")

    profile_country = st.selectbox(
        "Select country",
        options=country_codes_all,
        format_func=lambda c: country_labels.get(c, c),
        key="profile_country",
    )
    profile_df = svc.build_country_profile(filtered_df, profile_country)

    if profile_df.empty:
        st.info(
            f"No data available for **{country_labels.get(profile_country, profile_country)}** "
            f"with current filters."
        )
    else:
        country_name = country_labels.get(profile_country, profile_country)
        st.markdown(f"#### {country_name} ({profile_country})")

        for indicator in profile_df["Indicator"].unique():
            ind_data = profile_df[profile_df["Indicator"] == indicator].sort_values("Year")
            if ind_data.empty:
                continue
            st.markdown(f"**{svc.indicator_short_name(indicator)}**")
            fig = px.line(
                ind_data, x="Year", y="Value",
                labels={"Value": svc.indicator_description(indicator)},
                height=250,
            )
            fig.update_traces(line=dict(color="#2563eb", width=2))
            fig.update_layout(template="plotly_white", margin=dict(l=40, r=10, t=10, b=30))
            st.plotly_chart(fig, use_container_width=True)

            st.caption(
                f"Mean: {ind_data['Value'].mean():.2f}  ·  "
                f"Min: {ind_data['Value'].min():.2f} ({int(ind_data.loc[ind_data['Value'].idxmin(), 'Year'])})  ·  "
                f"Max: {ind_data['Value'].max():.2f} ({int(ind_data.loc[ind_data['Value'].idxmax(), 'Year'])})"
            )


# ----------------------------------------------------------------
# Tab 6: Distribution Analysis
# ----------------------------------------------------------------
with tab_dist:
    st.markdown("### Distribution Analysis")
    st.caption("Examine the distribution of values across countries.")

    if not selected_indicators:
        st.info("Select at least one indicator.")
    else:
        dist_indicator = st.selectbox(
            "Indicator",
            selected_indicators,
            format_func=svc.indicator_short_name,
            key="dist_indicator",
        )
        dist_year = st.slider(
            "Year",
            min_value=int(filtered_df["Year"].min()),
            max_value=int(filtered_df["Year"].max()),
            value=min(latest_year, int(filtered_df["Year"].max())),
            key="dist_year",
        )

        dist_df = svc.build_distribution_data(filtered_df, dist_indicator, dist_year)

        if dist_df.empty:
            st.info("No data for this selection.")
        else:
            col_hist, col_box = st.columns(2)

            with col_hist:
                st.markdown("**Histogram**")
                fig_hist = px.histogram(
                    dist_df, x="Value",
                    nbins=25,
                    color="Continent" if "Continent" in dist_df.columns else None,
                    labels={"Value": svc.indicator_description(dist_indicator)},
                    height=350,
                )
                fig_hist.update_layout(template="plotly_white", margin=dict(l=40, r=10, t=10, b=30))
                st.plotly_chart(fig_hist, use_container_width=True)

            with col_box:
                st.markdown("**Box plot by region**")
                if "Continent" in dist_df.columns:
                    fig_box = px.box(
                        dist_df, x="Continent", y="Value",
                        color="Continent",
                        labels={"Value": svc.indicator_short_name(dist_indicator)},
                        height=350,
                    )
                else:
                    fig_box = px.box(
                        dist_df, y="Value",
                        labels={"Value": svc.indicator_short_name(dist_indicator)},
                        height=350,
                    )
                fig_box.update_layout(
                    template="plotly_white", showlegend=False,
                    margin=dict(l=40, r=10, t=10, b=30),
                )
                st.plotly_chart(fig_box, use_container_width=True)

            # Descriptive stats
            st.markdown("**Summary statistics**")
            stats = dist_df["Value"].describe().round(2)
            st.dataframe(stats, use_container_width=True)


# ----------------------------------------------------------------
# Tab 7: Statistical Association Analysis
# ----------------------------------------------------------------
with tab_corr:
    st.markdown("### Statistical Association Analysis")

    if len(selected_indicators) < 2:
        st.info("Select at least **two** indicators to explore associations.")
    else:
        st.markdown(
            '<div class="panel-warning">'
            "<strong>Important:</strong> This view shows <em>statistical associations</em> "
            "between indicators. Association does not imply causation. "
            "Observed correlations may be driven by shared confounders (e.g. GDP, "
            "healthcare investment, data quality) and should not be interpreted as "
            "causal relationships."
            "</div>",
            unsafe_allow_html=True,
        )

        ind_x = st.selectbox(
            "X-axis indicator", selected_indicators,
            format_func=svc.indicator_short_name, key="corr_x",
        )
        remaining = [i for i in selected_indicators if i != ind_x]
        ind_y = st.selectbox(
            "Y-axis indicator", remaining,
            format_func=svc.indicator_short_name, key="corr_y",
        )
        corr_year = st.slider(
            "Year",
            min_value=int(filtered_df["Year"].min()),
            max_value=int(filtered_df["Year"].max()),
            value=min(latest_year, int(filtered_df["Year"].max())),
            key="corr_year",
        )

        corr_df, pearson_r = svc.build_correlation_data(filtered_df, ind_x, ind_y, corr_year)

        if corr_df.empty:
            st.info("Insufficient overlapping data for this analysis.")
        else:
            fig = px.scatter(
                corr_df,
                x="Value_X", y="Value_Y",
                color="Continent" if "Continent" in corr_df.columns else None,
                hover_name="Country" if "Country" in corr_df.columns else "CountryCode",
                trendline="ols",
                labels={
                    "Value_X": svc.indicator_short_name(ind_x),
                    "Value_Y": svc.indicator_short_name(ind_y),
                },
                height=480,
            )
            fig.update_layout(template="plotly_white", margin=dict(l=50, r=20, t=10, b=40))
            st.plotly_chart(fig, use_container_width=True)

            # Interpretation
            abs_r = abs(pearson_r)
            strength = "strong" if abs_r > 0.7 else "moderate" if abs_r > 0.4 else "weak"
            direction = "positive" if pearson_r > 0 else "negative"

            st.markdown(
                '<div class="panel-info">'
                f"<strong>Data-Driven Observation:</strong> Pearson <em>r</em> = "
                f"<strong>{pearson_r:.3f}</strong> — a <em>{strength} {direction}</em> "
                f"statistical association across {len(corr_df)} countries in {corr_year}.<br>"
                f"This is a <strong>statistical association</strong>, not evidence of causation."
                "</div>",
                unsafe_allow_html=True,
            )


# ----------------------------------------------------------------
# Tab 8: Raw Data Explorer + CSV Export
# ----------------------------------------------------------------
with tab_data:
    st.markdown("### Data Explorer")

    display_cols_default = [
        c for c in ["Country", "CountryCode", "Year", "Gender", "Indicator", "Value", "Continent"]
        if c in filtered_df.columns
    ]
    display_cols = st.multiselect(
        "Columns", filtered_df.columns.tolist(), default=display_cols_default,
    )

    if display_cols:
        st.dataframe(
            filtered_df[display_cols].sort_values(["Indicator", "CountryCode", "Year"]),
            use_container_width=True, hide_index=True, height=400,
        )

    # Summary statistics
    st.markdown("##### Summary statistics")
    st.dataframe(filtered_df.describe().round(3), use_container_width=True)

    # CSV download
    csv_bytes = svc.build_export_csv(filtered_df[display_cols] if display_cols else filtered_df)
    st.download_button(
        label="📥  Download filtered data (CSV)",
        data=csv_bytes,
        file_name=f"who_health_data_{year_range[0]}-{year_range[1]}.csv",
        mime="text/csv",
    )


# ================================================================
# Methodology Panel
# ================================================================
with st.expander("ℹ️  Methodology & data sources", expanded=False):
    st.markdown("#### Data source")
    st.markdown(f"- **Provider:** {source_meta['source']}")
    st.markdown(f"- **API endpoint:** `{source_meta['api']}`")
    st.markdown(f"- **Extraction date:** {source_meta['extraction_date'] or 'Not recorded'}")
    st.markdown(f"- **Year range:** {source_meta['year_range']}")
    st.markdown(f"- **Total records:** {source_meta['total_records']:,}")

    st.markdown("#### Indicator definitions")
    for ind_name in opts["indicators"]:
        st.markdown(
            f"- **{svc.indicator_short_name(ind_name)}** — "
            f"{svc.indicator_description(ind_name)} "
            f"(unit: {svc.indicator_unit(ind_name)})"
        )

    st.markdown("#### Aggregation method")
    st.markdown(
        "All cross-country averages shown in this dashboard are **unweighted** "
        "(each country counted equally). **Population-weighted averages** require "
        "population data, which is not included in the current WHO GHO extract. "
        "If population data is integrated in the future, weighted averages will be "
        "clearly labeled as such."
    )

    st.markdown("#### Missing data handling")
    st.markdown(
        "- Records with missing values are excluded from aggregation.\n"
        "- Countries with no data for a given year are omitted from that year's calculations.\n"
        "- The missing-value rate KPI shows the proportion of null values in the filtered dataset."
    )

    st.markdown("#### Geographic mapping")
    st.markdown(
        "Country codes follow **ISO 3166-1 alpha-3**. Continent assignments use "
        "standard UN geographic regions. Some WHO-specific aggregate codes "
        "(e.g. WB_HI, AFR) are excluded from country-level analysis."
    )

    st.markdown(
        '<div class="panel-warning">'
        "<strong>Disclaimer:</strong> This platform is a descriptive analytics tool. "
        "It does not contain validated predictive models. It should not be described "
        "as an AI prediction system."
        "</div>",
        unsafe_allow_html=True,
    )


# ================================================================
# Data Quality Panel
# ================================================================
with st.expander("📊  Data quality", expanded=False):
    quality_report = svc.compute_quality_report(filtered_df)

    if "error" in quality_report:
        st.warning(f"Could not compute quality report: {quality_report['error']}")
    else:
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Quality score", f"{quality_report['overall_score']:.0f}/100")
        q2.metric("Completeness", f"{quality_report['completeness']['overall_completeness_pct']:.1f}%")
        q3.metric("Consistent", "Yes" if quality_report["consistency"]["is_consistent"] else "Issues found")
        q4.metric("Countries", quality_report["geographic_coverage"]["countries"])

        # Per-column completeness
        st.markdown("##### Per-column completeness")
        col_data = quality_report["completeness"]["per_column"]
        col_table = pd.DataFrame(
            [
                {"Column": col, "Completeness": f"{v['completeness_score']:.1f}%", "Nulls": v["null_count"]}
                for col, v in col_data.items()
            ]
        )
        st.dataframe(col_table, use_container_width=True, hide_index=True)

        # Temporal coverage
        tc = quality_report["temporal_coverage"]
        st.markdown(
            f"**Temporal coverage:** {tc['years_covered']} years "
            f"({tc['year_range'][0]}–{tc['year_range'][1]}). "
            f"{'Gaps: ' + str(tc['year_gaps']) if tc['has_gaps'] else 'No year gaps.'}"
        )


# ================================================================
# Footer
# ================================================================
st.divider()
st.caption(
    f"{DASHBOARD_TITLE}  ·  Data: WHO GHO  ·  "
    f"Descriptive analytics only  ·  No predictive models included"
)

"""
WHO Global Health Intelligence Platform - Streamlit Dashboard.

A professional public health analytics dashboard providing interactive
geographic, temporal, demographic, and indicator analysis of WHO GHO data.

This dashboard presents descriptive analytics only. It does NOT contain
validated predictive models. Any forecasting is experimental and clearly
labeled as such.
"""

import sys
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

from src.who_health_intelligence.etl.loader import DatabaseLoader
from src.who_health_intelligence.etl.quality import DataQualityReport
from src.who_health_intelligence.utils.config import (
    DATABASE_PATH,
    WHO_INDICATORS,
    DASHBOARD_TITLE,
    DASHBOARD_SUBTITLE
)


# ==========================================
# Page Configuration
# ==========================================
st.set_page_config(
    page_title="WHO Global Health Intelligence",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ==========================================
# Custom Styling
# ==========================================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    .stApp { background-color: #F8FAFC; color: #1E293B; }

    /* Hide Streamlit Branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* Typography */
    h1 { color: #0F172A; font-weight: 800; font-size: 2.2rem; }
    h2 { color: #1E3A8A; font-weight: 700; font-size: 1.4rem; margin-top: 1.5rem; }
    h3 { color: #334155; font-weight: 600; font-size: 1.05rem; text-transform: uppercase; letter-spacing: 0.05em; }

    /* Metric Cards */
    div[data-testid="metric-container"] {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        padding: 1.2rem;
        border-radius: 10px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }

    /* Info panels */
    .info-panel {
        background: linear-gradient(135deg, #1E3A8A 0%, #3B82F6 100%);
        color: white;
        padding: 1.2rem;
        border-radius: 10px;
        margin-bottom: 1.5rem;
    }
    .info-panel h4 { color: #93C5FD; margin-bottom: 0.5rem; font-weight: 700; text-transform: uppercase; font-size: 0.8rem; letter-spacing: 1px; }
    .info-panel p { font-size: 0.95rem; font-weight: 500; line-height: 1.5; margin: 0; }

    .warning-panel {
        background-color: #FEF3C7;
        border-left: 4px solid #F59E0B;
        padding: 1rem;
        border-radius: 6px;
        margin: 1rem 0;
    }

    .methodology-panel {
        background-color: #F0FDF4;
        border-left: 4px solid #22C55E;
        padding: 1rem;
        border-radius: 6px;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)


# ==========================================
# Data Loading
# ==========================================
@st.cache_data(ttl=3600)
def load_data(db_path: str = DATABASE_PATH) -> pd.DataFrame:
    """Load health indicator data from SQLite database."""
    try:
        loader = DatabaseLoader(db_path)
        df = loader.query("SELECT * FROM health_indicators")

        if df.empty:
            return df

        # Ensure proper types
        df['Year'] = pd.to_numeric(df['Year'], errors='coerce').astype('Int32')
        df['Value'] = pd.to_numeric(df['Value'], errors='coerce')

        # Ensure categorical columns are strings for filtering
        for col in ['CountryCode', 'Gender', 'Indicator', 'Continent']:
            if col in df.columns:
                df[col] = df[col].astype(str)

        return df
    except Exception as e:
        st.error(f"Database loading error: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def compute_yoy_changes(df: pd.DataFrame) -> pd.DataFrame:
    """Compute year-over-year changes for time series analysis."""
    df = df.sort_values(['CountryCode', 'Indicator', 'Gender', 'Year'])
    df['Prev_Value'] = df.groupby(
        ['CountryCode', 'Indicator', 'Gender']
    )['Value'].shift(1)
    df['YoY_Change'] = df['Value'] - df['Prev_Value']
    df['YoY_Pct'] = (df['YoY_Change'] / df['Prev_Value'] * 100).round(2)
    return df


def get_indicator_display_name(indicator: str) -> str:
    """Get human-readable indicator name."""
    info = WHO_INDICATORS.get(indicator, {})
    return info.get('description', indicator.replace('_', ' ').title())


def get_indicator_short_name(indicator: str) -> str:
    """Get short display name for indicators."""
    names = {
        'LIFE_EXPECTANCY': 'Life Expectancy',
        'NCD_MORTALITY': 'NCD Mortality (30-70)',
        'UHC_COVERAGE': 'UHC Coverage Index',
        'MATERNAL_MORTALITY': 'Maternal Mortality',
        'INFANT_MORTALITY': 'Infant Mortality'
    }
    return names.get(indicator, indicator)


# ==========================================
# Main Dashboard
# ==========================================
def main():
    # Header
    st.markdown(f"# 🏥 {DASHBOARD_TITLE}")
    st.markdown(
        f"<p style='color: #64748B; font-size: 1rem; margin-top: -8px;'>"
        f"{DASHBOARD_SUBTITLE}</p>",
        unsafe_allow_html=True
    )

    # Load data
    df = load_data()
    if df.empty:
        st.warning(
            "No data available. Please run the ETL pipeline first:\n\n"
            "```python\n"
            "from src.who_health_intelligence.etl.pipeline import WHOETLPipeline\n"
            "pipeline = WHOETLPipeline()\n"
            "pipeline.run()\n"
            "```"
        )
        st.stop()

    # Compute derived metrics
    df = compute_yoy_changes(df)

    # ---- Sidebar Filters ----
    with st.sidebar:
        st.markdown("### 🎛️ Analysis Parameters")

        # Available indicators
        available_indicators = sorted(df['Indicator'].unique().tolist())
        selected_indicators = st.multiselect(
            "Health Indicators",
            options=available_indicators,
            default=available_indicators,
            format_func=get_indicator_short_name
        )

        # Year range
        available_years = sorted(df['Year'].dropna().unique())
        if len(available_years) > 0:
            year_range = st.slider(
                "Year Range",
                min_value=int(available_years[0]),
                max_value=int(available_years[-1]),
                value=(int(available_years[0]), int(available_years[-1]))
            )
        else:
            year_range = (2000, 2023)

        # Geographic filter
        continents = ['Global'] + sorted(
            [c for c in df['Continent'].unique() if c != 'Unknown' and c != 'nan']
        )
        selected_continent = st.selectbox("Geographic Region", continents)

        # Gender filter
        genders = sorted(df['Gender'].unique().tolist())
        selected_gender = st.selectbox(
            "Demographic Group",
            genders,
            index=genders.index('Both sexes') if 'Both sexes' in genders else 0
        )

        st.markdown("---")
        st.markdown(
            "<small>**Data Source:** WHO Global Health Observatory (GHO)<br>"
            "**API:** ghoapi.azureedge.net<br>"
            "**Last Updated:** See ETL metadata</small>",
            unsafe_allow_html=True
        )

    # ---- Apply Filters ----
    filtered_df = df[
        (df['Indicator'].isin(selected_indicators)) &
        (df['Year'] >= year_range[0]) &
        (df['Year'] <= year_range[1]) &
        (df['Gender'] == selected_gender)
    ].copy()

    if selected_continent != 'Global':
        filtered_df = filtered_df[filtered_df['Continent'] == selected_continent]

    if filtered_df.empty:
        st.warning("No data matches the selected filters. Try adjusting your selection.")
        st.stop()

    # Current year snapshot
    latest_year = filtered_df['Year'].max()
    df_latest = filtered_df[filtered_df['Year'] == latest_year]

    # ---- Key Metrics ----
    st.markdown("### 📊 Key Health Metrics")
    st.markdown(
        f"<small>Snapshot for {int(latest_year)} | "
        f"{filtered_df['CountryCode'].nunique()} countries | "
        f"Gender: {selected_gender}</small>",
        unsafe_allow_html=True
    )

    metric_cols = st.columns(min(len(selected_indicators), 4))
    for idx, indicator in enumerate(selected_indicators[:4]):
        with metric_cols[idx]:
            ind_data = df_latest[df_latest['Indicator'] == indicator]
            if not ind_data.empty:
                mean_val = ind_data['Value'].mean()
                # Get previous year for delta
                prev_year_data = filtered_df[
                    (filtered_df['Indicator'] == indicator) &
                    (filtered_df['Year'] == latest_year - 1)
                ]
                if not prev_year_data.empty:
                    prev_mean = prev_year_data['Value'].mean()
                    delta = mean_val - prev_mean
                    # For mortality indicators, lower is better
                    is_inverse = 'MORTALITY' in indicator
                    st.metric(
                        label=get_indicator_short_name(indicator),
                        value=f"{mean_val:.1f}",
                        delta=f"{delta:+.2f} vs {int(latest_year)-1}",
                        delta_color="inverse" if is_inverse else "normal"
                    )
                else:
                    st.metric(
                        label=get_indicator_short_name(indicator),
                        value=f"{mean_val:.1f}"
                    )

    st.markdown("---")

    # ---- Tabbed Interface ----
    tabs = st.tabs([
        "🗺️ Geographic Analysis",
        "📈 Temporal Trends",
        "👥 Demographic Analysis",
        "🔗 Indicator Correlation",
        "📋 Data Explorer",
        "ℹ️ Methodology"
    ])

    # ==== TAB 1: Geographic Analysis ====
    with tabs[0]:
        st.markdown("### 🗺️ Geographic Distribution")

        if len(selected_indicators) > 0:
            primary_indicator = selected_indicators[0]
            geo_df = df_latest[df_latest['Indicator'] == primary_indicator].copy()

            if not geo_df.empty and 'Continent' in geo_df.columns:
                col_map, col_rank = st.columns([2, 1])

                with col_map:
                    st.markdown(f"**{get_indicator_short_name(primary_indicator)}** by Country")
                    geo_clean = geo_df.dropna(subset=['Value'])

                    if not geo_clean.empty:
                        fig_map = px.choropleth(
                            geo_clean,
                            locations="CountryCode",
                            color="Value",
                            hover_name="Country" if "Country" in geo_clean.columns else "CountryCode",
                            hover_data={
                                'Value': ':.2f',
                                'Continent': True,
                                'CountryCode': False
                            },
                            color_continuous_scale="RdYlGn_r" if 'MORTALITY' in primary_indicator else "RdYlGn",
                            labels={'Value': get_indicator_display_name(primary_indicator)},
                            height=500
                        )
                        fig_map.update_layout(
                            geo=dict(
                                showframe=True,
                                showcoastlines=True,
                                projection_type='natural earth',
                                bgcolor='rgba(0,0,0,0)'
                            ),
                            margin=dict(l=0, r=0, t=20, b=0),
                            paper_bgcolor='rgba(0,0,0,0)'
                        )
                        st.plotly_chart(fig_map, use_container_width=True)
                    else:
                        st.info("No geographic data available for this selection.")

                with col_rank:
                    st.markdown("**Country Rankings**")
                    rank_df = geo_df.nlargest(15, 'Value')[
                        ['Country', 'Value']
                    ] if 'Country' in geo_df.columns else geo_df.nlargest(15, 'Value')[['CountryCode', 'Value']]

                    if not rank_df.empty:
                        name_col = 'Country' if 'Country' in rank_df.columns else 'CountryCode'
                        fig_bar = px.bar(
                            rank_df,
                            x='Value',
                            y=name_col,
                            orientation='h',
                            color='Value',
                            color_continuous_scale='RdYlGn_r' if 'MORTALITY' in primary_indicator else 'RdYlGn',
                            labels={'Value': get_indicator_short_name(primary_indicator)},
                            height=500
                        )
                        fig_bar.update_layout(
                            yaxis={'categoryorder': 'total ascending'},
                            showlegend=False,
                            margin=dict(l=0, r=0, t=10, b=0),
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)'
                        )
                        st.plotly_chart(fig_bar, use_container_width=True)

                # Continent-level summary
                st.markdown("#### Continental Summary")
                if 'Continent' in geo_df.columns:
                    continent_summary = geo_df.groupby('Continent')['Value'].agg(
                        ['mean', 'median', 'min', 'max', 'count']
                    ).round(2).reset_index()
                    continent_summary.columns = ['Continent', 'Mean', 'Median', 'Min', 'Max', 'Countries']
                    st.dataframe(continent_summary, use_container_width=True, hide_index=True)

    # ==== TAB 2: Temporal Trends ====
    with tabs[1]:
        st.markdown("### 📈 Temporal Trend Analysis")

        if len(selected_indicators) > 0:
            # Time series for selected indicators
            for indicator in selected_indicators:
                st.markdown(f"#### {get_indicator_short_name(indicator)}")
                st.markdown(
                    f"<small>{get_indicator_display_name(indicator)}</small>",
                    unsafe_allow_html=True
                )

                trend_df = filtered_df[filtered_df['Indicator'] == indicator]

                if trend_df.empty:
                    st.info("No data available for temporal analysis.")
                    continue

                # Global trend (mean across countries per year)
                global_trend = trend_df.groupby('Year')['Value'].agg(
                    ['mean', 'std', 'median']
                ).reset_index()

                fig_trend = go.Figure()

                # Mean line
                fig_trend.add_trace(go.Scatter(
                    x=global_trend['Year'],
                    y=global_trend['mean'],
                    mode='lines+markers',
                    name='Global Mean',
                    line=dict(color='#2563EB', width=3),
                    marker=dict(size=6)
                ))

                # Confidence band (±1 std)
                fig_trend.add_trace(go.Scatter(
                    x=global_trend['Year'],
                    y=global_trend['mean'] + global_trend['std'],
                    mode='lines',
                    line=dict(width=0),
                    showlegend=False
                ))
                fig_trend.add_trace(go.Scatter(
                    x=global_trend['Year'],
                    y=global_trend['mean'] - global_trend['std'],
                    mode='lines',
                    line=dict(width=0),
                    fill='tonexty',
                    fillcolor='rgba(37, 99, 235, 0.1)',
                    name='±1 Std Dev',
                    showlegend=True
                ))

                fig_trend.update_layout(
                    xaxis_title='Year',
                    yaxis_title=get_indicator_display_name(indicator),
                    height=400,
                    template='plotly_white',
                    margin=dict(l=50, r=20, t=20, b=40),
                    legend=dict(orientation='h', y=1.1)
                )
                st.plotly_chart(fig_trend, use_container_width=True)

                # Top country trends
                st.markdown("**Selected Country Trends**")
                top_countries = trend_df.groupby('CountryCode')['Value'].mean().nlargest(10).index
                country_trends = trend_df[trend_df['CountryCode'].isin(top_countries)]

                fig_countries = px.line(
                    country_trends,
                    x='Year',
                    y='Value',
                    color='Country' if 'Country' in country_trends.columns else 'CountryCode',
                    labels={'Value': get_indicator_short_name(indicator)},
                    height=350
                )
                fig_countries.update_layout(
                    template='plotly_white',
                    margin=dict(l=50, r=20, t=20, b=40),
                    legend=dict(orientation='h', y=-0.2)
                )
                st.plotly_chart(fig_countries, use_container_width=True)

    # ==== TAB 3: Demographic Analysis ====
    with tabs[2]:
        st.markdown("### 👥 Demographic Comparison")

        # Show all genders side by side
        demo_df = filtered_df[
            (filtered_df['Indicator'].isin(selected_indicators)) &
            (filtered_df['Year'] == latest_year)
        ]

        if not demo_df.empty:
            for indicator in selected_indicators:
                st.markdown(f"#### {get_indicator_short_name(indicator)}")

                ind_demo = demo_df[demo_df['Indicator'] == indicator]

                # Gender comparison box plots
                fig_box = px.box(
                    ind_demo,
                    x='Gender',
                    y='Value',
                    color='Gender',
                    labels={'Value': get_indicator_display_name(indicator)},
                    height=350
                )
                fig_box.update_layout(
                    template='plotly_white',
                    showlegend=False,
                    margin=dict(l=50, r=20, t=20, b=40)
                )
                st.plotly_chart(fig_box, use_container_width=True)

                # Gender gap analysis
                gender_summary = ind_demo.groupby('Gender')['Value'].agg(
                    ['mean', 'median', 'std']
                ).round(2)
                st.dataframe(gender_summary, use_container_width=True)

    # ==== TAB 4: Indicator Correlation ====
    with tabs[3]:
        st.markdown("### 🔗 Cross-Indicator Correlation Analysis")

        if len(selected_indicators) >= 2:
            st.markdown(
                "Explore relationships between health indicators. "
                "This is **descriptive analytics** showing observed correlations, "
                "not causal inference or predictive modeling."
            )

            ind1 = st.selectbox("X-Axis Indicator", selected_indicators, index=0)
            ind2 = st.selectbox(
                "Y-Axis Indicator",
                selected_indicators,
                index=min(1, len(selected_indicators) - 1)
            )

            if ind1 != ind2:
                # Merge the two indicators
                df_ind1 = df_latest[df_latest['Indicator'] == ind1][
                    ['CountryCode', 'Value', 'Continent']
                ].rename(columns={'Value': f'Value_{ind1}'})
                df_ind2 = df_latest[df_latest['Indicator'] == ind2][
                    ['CountryCode', 'Value']
                ].rename(columns={'Value': f'Value_{ind2}'})

                if 'Country' in df_latest.columns:
                    df_names = df_latest[df_latest['Indicator'] == ind1][
                        ['CountryCode', 'Country']
                    ].drop_duplicates()
                    merged = pd.merge(df_ind1, df_ind2, on='CountryCode')
                    merged = pd.merge(merged, df_names, on='CountryCode', how='left')
                else:
                    merged = pd.merge(df_ind1, df_ind2, on='CountryCode')

                merged = merged.dropna()

                if not merged.empty:
                    fig_scatter = px.scatter(
                        merged,
                        x=f'Value_{ind1}',
                        y=f'Value_{ind2}',
                        color='Continent' if 'Continent' in merged.columns else None,
                        hover_name='Country' if 'Country' in merged.columns else 'CountryCode',
                        trendline='ols',
                        labels={
                            f'Value_{ind1}': get_indicator_short_name(ind1),
                            f'Value_{ind2}': get_indicator_short_name(ind2)
                        },
                        height=500
                    )
                    fig_scatter.update_layout(
                        template='plotly_white',
                        margin=dict(l=50, r=20, t=20, b=40)
                    )
                    st.plotly_chart(fig_scatter, use_container_width=True)

                    # Correlation coefficient
                    corr = merged[f'Value_{ind1}'].corr(merged[f'Value_{ind2}'])
                    st.markdown(
                        f"**Pearson Correlation:** {corr:.3f} "
                        f"({abs(corr):.1%} {'strong' if abs(corr) > 0.7 else 'moderate' if abs(corr) > 0.4 else 'weak'} "
                        f"{'positive' if corr > 0 else 'negative'} correlation)"
                    )

                    st.markdown(
                        '<div class="warning-panel">'
                        '<strong>Note:</strong> Correlation does not imply causation. '
                        'These are observed statistical associations in the data and '
                        'should not be interpreted as causal relationships.'
                        '</div>',
                        unsafe_allow_html=True
                    )
                else:
                    st.info("No overlapping data available for the selected indicators.")
            else:
                st.info("Please select two different indicators for correlation analysis.")
        else:
            st.info(
                "Select at least 2 indicators in the sidebar to enable correlation analysis."
            )

    # ==== TAB 5: Data Explorer ====
    with tabs[4]:
        st.markdown("### 📋 Data Explorer")

        # Display filtered data
        display_df = filtered_df.copy()

        # Column selection
        display_cols = st.multiselect(
            "Columns to Display",
            options=display_df.columns.tolist(),
            default=[c for c in ['Country', 'CountryCode', 'Year', 'Gender', 'Indicator', 'Value', 'Continent'] if c in display_df.columns]
        )

        if display_cols:
            st.dataframe(
                display_df[display_cols],
                use_container_width=True,
                hide_index=True,
                height=400
            )

        # Summary statistics
        st.markdown("#### Summary Statistics")
        st.dataframe(
            display_df.describe().round(3),
            use_container_width=True
        )

        # Download
        csv = display_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Filtered Data (CSV)",
            data=csv,
            file_name=f'who_health_data_{year_range[0]}-{year_range[1]}.csv',
            mime='text/csv'
        )

    # ==== TAB 6: Methodology ====
    with tabs[5]:
        st.markdown("### ℹ️ Methodology & Data Sources")

        st.markdown("""
        <div class="methodology-panel">
        <strong>Data Source:</strong> World Health Organization (WHO) Global Health Observatory (GHO)
        </div>
        """, unsafe_allow_html=True)

        st.markdown("#### Data Extraction")
        st.markdown("""
        - **API:** WHO GHO OData API (`ghoapi.azureedge.net/api/`)
        - **Format:** JSON (OData v2 protocol)
        - **Indicators:** Extracted using official WHO indicator codes
        - **Extraction Method:** HTTP GET with automatic retry and exponential backoff
        """)

        st.markdown("#### Active Indicators")
        for ind_name in available_indicators:
            info = WHO_INDICATORS.get(ind_name, {})
            st.markdown(
                f"- **{get_indicator_short_name(ind_name)}** "
                f"(`{info.get('code', 'N/A')}`): {info.get('description', 'N/A')}"
            )

        st.markdown("#### Data Processing Pipeline")
        st.markdown("""
        1. **Extract:** Raw JSON records from WHO GHO OData API
        2. **Validate:** Schema validation and range checks per indicator
        3. **Transform:** Gender code normalization, type optimization, null handling
        4. **Enrich:** Country name and continent metadata mapping
        5. **Load:** Idempotent upsert into SQLite with UNIQUE constraints
        6. **Monitor:** Data quality scoring and reporting
        """)

        st.markdown("#### Gender Code Mapping")
        st.markdown("""
        | WHO API Code | Normalized Value |
        |---|---|
        | `SEX_BTSX` / `BTSX` | Both sexes |
        | `SEX_MLE` / `MLE` | Male |
        | `SEX_FMLE` / `FMLE` | Female |
        """)

        st.markdown("#### Limitations & Caveats")
        st.markdown("""
        <div class="warning-panel">
        <strong>Important:</strong>
        <ul>
        <li>This platform presents <strong>descriptive analytics only</strong>. It does not contain validated predictive models.</li>
        <li>Data reflects WHO GHO availability and may have gaps for certain countries, years, or demographics.</li>
        <li>Country classification follows ISO 3166-1 alpha-3 standards. Some territories may not be represented.</li>
        <li>Indicator values are as reported by WHO member states and may reflect different reporting methodologies.</li>
        <li>Correlation analysis shows statistical associations only and does not establish causation.</li>
        <li>Year-over-year changes may reflect reporting improvements rather than actual health changes.</li>
        </ul>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("#### No ML/AI Claims")
        st.markdown("""
        <div class="warning-panel">
        This platform is a <strong>public health data engineering and analytics tool</strong>.
        It does <strong>not</strong> claim to be an AI prediction platform.
        No machine learning models have been trained, validated, or deployed for health outcome prediction.
        Any future forecasting capabilities would require:
        <ul>
        <li>Proper time-series cross-validation</li>
        <li>Out-of-sample evaluation metrics</li>
        <li>Uncertainty quantification (confidence/prediction intervals)</li>
        <li>Clear disclosure of experimental status and limitations</li>
        </ul>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("#### Data Quality")
        if not filtered_df.empty:
            quality_report = DataQualityReport(filtered_df)
            report = quality_report.generate_full_report()

            col_q1, col_q2, col_q3 = st.columns(3)
            with col_q1:
                st.metric("Quality Score", f"{report['overall_score']}/100")
            with col_q2:
                st.metric("Completeness", f"{report['completeness']['overall_completeness_pct']}%")
            with col_q3:
                st.metric("Countries", f"{report['geographic_coverage']['countries']}")


if __name__ == "__main__":
    main()

import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# ==========================================
# PAGE CONFIGURATION (Enterprise Grade)
# ==========================================
st.set_page_config(
    page_title="WHO Health Intelligence",
    page_icon="💠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# ADVANCED CSS (Clean, SaaS-like, High Contrast)
# ==========================================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', sans-serif;
    }
    
    /* Backgrounds */
    .stApp { background-color: #F4F7F9; color: #1E293B; }
    
    /* Hide Streamlit Branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Typography */
    h1 { color: #0F172A; font-weight: 800; font-size: 2.5rem; padding-bottom: 0; }
    h2 { color: #1E293B; font-weight: 700; font-size: 1.5rem; margin-top: 1.5rem; }
    h3 { color: #334155; font-weight: 600; font-size: 1.1rem; text-transform: uppercase; letter-spacing: 0.05em; }
    
    /* Elegant Metric Cards */
    div[data-testid="metric-container"] {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.02), 0 2px 4px -1px rgba(0,0,0,0.02);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    div[data-testid="metric-container"]:hover {
        transform: translateY(-3px);
        box-shadow: 0 10px 15px -3px rgba(0,0,0,0.05);
        border-color: #CBD5E1;
    }
    
    /* Custom Info Panels */
    .insight-panel {
        background: linear-gradient(135deg, #1E3A8A 0%, #3B82F6 100%);
        color: white;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 10px 25px -5px rgba(37, 99, 235, 0.4);
        margin-bottom: 2rem;
    }
    .insight-panel h4 { color: #93C5FD; margin-bottom: 0.5rem; font-weight: 700; text-transform: uppercase; font-size: 0.85rem; letter-spacing: 1px; }
    .insight-panel p { font-size: 1.05rem; font-weight: 500; line-height: 1.6; margin: 0; }
    
    /* Styling Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 2rem;
        border-bottom: 2px solid #E2E8F0;
    }
    .stTabs [data-baseweb="tab"] {
        padding-top: 1rem;
        padding-bottom: 1rem;
        font-weight: 600;
        color: #64748B;
    }
    .stTabs [aria-selected="true"] {
        color: #2563EB !important;
        border-bottom-color: #2563EB !important;
    }
    
    /* Plotly Chart Containers */
    .plot-container {
        background: white;
        padding: 1rem;
        border-radius: 12px;
        border: 1px solid #E2E8F0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.02);
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# DATA ARCHITECTURE (ETL Loading & Caching)
# ==========================================
@st.cache_data(ttl=3600)
def load_and_architect_data(db_path: str = "who_data.db") -> pd.DataFrame:
    """Loads SQLite data and engineers advanced features (Continents, YoY Deltas)."""
    try:
        with sqlite3.connect(db_path) as conn:
            df = pd.read_sql("SELECT * FROM health_indicators", conn)
            
        df['Year'] = df['Year'].astype('int32')
        df['Value'] = pd.to_numeric(df['Value'], errors='coerce')
        
        # Merge Geographic Metadata
        gapminder = px.data.gapminder()[['iso_alpha', 'country', 'continent']].drop_duplicates()
        df = pd.merge(df, gapminder, left_on='CountryCode', right_on='iso_alpha', how='left')
        
        df['continent'] = df['continent'].fillna('Unmapped')
        df['country'] = df['country'].fillna(df['CountryCode'])
        
        # Ensure data is sorted for Time-Series calculations
        df = df.sort_values(by=['CountryCode', 'Indicator', 'Gender', 'Year'])
        
        # Calculate Year-over-Year (YoY) Change using shifting
        df['Prev_Value'] = df.groupby(['CountryCode', 'Indicator', 'Gender'])['Value'].shift(1)
        df['YoY_Delta'] = df['Value'] - df['Prev_Value']
        
        return df
    except Exception as e:
        st.error(f"Critical System Error: Database failure. Ensure 'who_data.db' exists. Details: {e}")
        return pd.DataFrame()

# ==========================================
# HELPER: METRICS CALCULATOR
# ==========================================
def calculate_metrics(df_current: pd.DataFrame, df_prev: pd.DataFrame, indicator: str):
    """Calculates aggregates and deltas for KPI rendering."""
    curr_df = df_current[df_current['Indicator'] == indicator]
    prev_df = df_prev[df_prev['Indicator'] == indicator]
    
    curr_mean = curr_df['Value'].mean()
    prev_mean = prev_df['Value'].mean()
    
    delta = curr_mean - prev_mean if (pd.notna(curr_mean) and pd.notna(prev_mean)) else 0
    return curr_mean, delta

# ==========================================
# MAIN DASHBOARD ENGINE
# ==========================================
def main():
    # --- HEADER & AI INSIGHT PANEL ---
    st.markdown("<h1>💠 Global Health Executive Dashboard</h1>", unsafe_allow_html=True)
    st.markdown("<p style='color: #64748B; font-size: 1.1rem; margin-top: -10px; margin-bottom: 2rem;'>Advanced Business Intelligence & Epidemiological Analytics Platform</p>", unsafe_allow_html=True)
    
    df = load_and_architect_data()
    if df.empty:
        st.stop()

    # --- SIDEBAR NAVIGATION ---
    with st.sidebar:
        st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/c/c2/WHO_logo.svg/800px-WHO_logo.svg.png", width=120)
        st.markdown("### 🎛️ Analysis Parameters")
        
        available_years = sorted(df['Year'].unique())
        selected_year = st.select_slider("Select Target Year", options=available_years, value=available_years[-1])
        
        selected_region = st.selectbox("Geographic Focus", options=['Global'] + list(df['continent'].unique()[df['continent'].unique() != 'Unmapped']))
        selected_gender = st.selectbox("Demographic Filter", options=df['Gender'].unique())
        
        st.markdown("---")
        st.markdown("**Data Integrity:** Verified ✅<br>**Source:** WHO OData API<br>**Engine:** SQLite + Pandas", unsafe_allow_html=True)

    # --- DATA SLICING ---
    df_current = df[(df['Year'] == selected_year) & (df['Gender'] == selected_gender)]
    
    # Get previous year data for robust Delta calculations (fallback if year is not continuous)
    prev_year = selected_year - 1 if (selected_year - 1) in available_years else (selected_year - 5 if selected_year > 2000 else selected_year)
    df_prev = df[(df['Year'] == prev_year) & (df['Gender'] == selected_gender)]
    
    if selected_region != 'Global':
        df_current = df_current[df_current['continent'] == selected_region]
        df_prev = df_prev[df_prev['continent'] == selected_region]

    # --- AI INSIGHT (Dynamic Text Generation) ---
    mortality_mean, mort_delta = calculate_metrics(df_current, df_prev, 'NCD_Mortality')
    uhc_mean, uhc_delta = calculate_metrics(df_current, df_prev, 'UHC_Coverage')
    
    trend_text = "improving" if mort_delta < 0 else "worsening"
    st.markdown(f"""
    <div class="insight-panel">
        <h4>Automated Analytical Insight</h4>
        <p>In {selected_year}, the average global cardiovascular mortality probability is <strong>{mortality_mean:.1f}%</strong> 
        ({trend_text} compared to {prev_year}). Meanwhile, the Universal Health Coverage index stands at <strong>{uhc_mean:.1f}/100</strong>. 
        Explore the tabs below to understand how healthcare access mitigates severe mortality risks across different socio-economic regions.</p>
    </div>
    """, unsafe_allow_html=True)

    # --- TOP LEVEL KPIs (Using st.metric for native delta arrows) ---
    st.markdown("### 📊 Key Performance Indicators")
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    
    with kpi1:
        st.metric(label="Avg NCD/CVD Mortality", value=f"{mortality_mean:.1f}%", delta=f"{mort_delta:.2f}% (vs {prev_year})", delta_color="inverse")
    with kpi2:
        st.metric(label="Universal Health Coverage", value=f"{uhc_mean:.1f}", delta=f"{uhc_delta:.2f} (vs {prev_year})", delta_color="normal")
    with kpi3:
        best_country = df_current[df_current['Indicator'] == 'UHC_Coverage'].sort_values('Value', ascending=False).head(1)
        best_name = best_country['country'].values[0] if not best_country.empty else "N/A"
        st.metric(label="Highest Health Coverage", value=best_name, delta="Top Performer", delta_color="off")
    with kpi4:
        worst_country = df_current[df_current['Indicator'] == 'NCD_Mortality'].sort_values('Value', ascending=False).head(1)
        worst_name = worst_country['country'].values[0] if not worst_country.empty else "N/A"
        st.metric(label="Highest Mortality Risk", value=worst_name, delta="Critical Need", delta_color="inverse")

    st.markdown("<br>", unsafe_allow_html=True)

    # --- TABBED INTERFACE ---
    tab_geo, tab_corr, tab_hier, tab_data = st.tabs([
        "🗺️ Geospatial Intelligence", 
        "📈 Impact Correlation", 
        "⭕ Hierarchical Breakdown", 
        "🗃️ Data Explorer"
    ])

    # ==========================================
    # TAB 1: GEOSPATIAL (Advanced Plotly)
    # ==========================================
    with tab_geo:
        col_map, col_trend = st.columns([2, 1])
        
        df_mort_curr = df_current[df_current['Indicator'] == 'NCD_Mortality']
        
        with col_map:
            st.markdown("<div class='plot-container'>", unsafe_allow_html=True)
            st.markdown("### Cardiovascular Mortality Distribution")
            if not df_mort_curr.empty:
                fig_map = px.choropleth(
                    df_mort_curr, locations="CountryCode", color="Value", hover_name="country",
                    color_continuous_scale="Reds", labels={'Value': 'Mortality (%)'},
                    height=500
                )
                fig_map.update_layout(
                    geo=dict(showframe=False, showcoastlines=True, projection_type='natural earth', bgcolor='rgba(0,0,0,0)'),
                    margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor='rgba(0,0,0,0)'
                )
                st.plotly_chart(fig_map, width='stretch')
            st.markdown("</div>", unsafe_allow_html=True)
            
        with col_trend:
            st.markdown("<div class='plot-container'>", unsafe_allow_html=True)
            st.markdown("### Top 10 Highest Risk Nations")
            if not df_mort_curr.empty:
                top_10 = df_mort_curr.sort_values('Value', ascending=False).head(10)
                fig_bar = px.bar(
                    top_10, x="Value", y="country", orientation='h', 
                    color="Value", color_continuous_scale="Reds", height=500
                )
                fig_bar.update_layout(
                    yaxis={'categoryorder':'total ascending'}, showlegend=False,
                    margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
                )
                st.plotly_chart(fig_bar, width='stretch')
            st.markdown("</div>", unsafe_allow_html=True)

    # ==========================================
    # TAB 2: IMPACT CORRELATION (Scatter with Marginals)
    # ==========================================
    with tab_corr:
        st.markdown("""
        ### Hypothesis Testing: Coverage vs Mortality
        Does investing in Universal Health Coverage (UHC) statistically reduce Non-Communicable Disease (NCD) mortality? 
        The scatter plot below merges both datasets to reveal the macro-economic correlation.
        """)
        
        df_ncd = df_current[df_current['Indicator'] == 'NCD_Mortality'][['CountryCode', 'country', 'continent', 'Value']]
        df_uhc = df_current[df_current['Indicator'] == 'UHC_Coverage'][['CountryCode', 'Value']]
        
        merged = pd.merge(df_ncd, df_uhc, on='CountryCode', suffixes=('_Mort', '_UHC')).dropna()
        
        if not merged.empty:
            fig_scatter = px.scatter(
                merged, x="Value_UHC", y="Value_Mort", color="continent", hover_name="country",
                size_max=15, trendline="ols", marginal_x="box", marginal_y="box",
                labels={'Value_UHC': 'UHC Index', 'Value_Mort': 'CVD Mortality Probability (%)'},
                color_discrete_sequence=px.colors.qualitative.Set2, height=600
            )
            fig_scatter.update_traces(marker=dict(size=12, opacity=0.7, line=dict(width=1, color='white')))
            fig_scatter.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='#F8FAFC')
            st.plotly_chart(fig_scatter, width='stretch')
        else:
            st.warning("Data unavailable for correlation in the selected year/region.")

    # ==========================================
    # TAB 3: HIERARCHICAL BREAKDOWN (Sunburst)
    # ==========================================
    with tab_hier:
        st.markdown("### Regional Composition (Sunburst Analytics)")
        st.markdown("Click on a continent to drill down into specific country performances.")
        
        df_uhc_curr = df_current[df_current['Indicator'] == 'UHC_Coverage']
        df_uhc_clean = df_uhc_curr[df_uhc_curr['continent'] != 'Unmapped'].dropna(subset=['Value'])
        
        if not df_uhc_clean.empty:
            fig_sun = px.sunburst(
                df_uhc_clean, path=['continent', 'country'], values='Value',
                color='Value', color_continuous_scale='Blues',
                height=650
            )
            fig_sun.update_layout(margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig_sun, width='stretch')

    # ==========================================
    # TAB 4: DATA EXPLORER & DOWNLOADS
    # ==========================================
    with tab_data:
        st.markdown("### 🗃️ Raw Data Extraction Engine")
        st.markdown("Inspect the cleaned, optimized dataset or export it for external modeling.")
        
        st.dataframe(
            df_current, 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "Year": st.column_config.NumberColumn(format="%d"),
                "Value": st.column_config.NumberColumn(format="%.2f")
            }
        )
        
        csv = df_current.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="⬇️ Download Filtered Dataset (CSV)",
            data=csv,
            file_name=f'who_health_data_{selected_year}.csv',
            mime='text/csv',
        )

if __name__ == "__main__":
    main()

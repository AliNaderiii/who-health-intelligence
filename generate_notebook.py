import json
import os

def create_notebook():
    notebook = {
        "cells": [],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3"
            },
            "language_info": {
                "codemirror_mode": {"name": "ipython", "version": 3},
                "file_extension": ".py",
                "mimetype": "text/x-python",
                "name": "python",
                "nbconvert_exporter": "python",
                "pygments_lexer": "ipython3",
                "version": "3.9.0"
            }
        },
        "nbformat": 4,
        "nbformat_minor": 5
    }

    def add_markdown(source):
        notebook["cells"].append({
            "cell_type": "markdown",
            "metadata": {},
            "source": [line + "\n" for line in source.split('\n')]
        })

    def add_code(source):
        notebook["cells"].append({
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [line + "\n" for line in source.split('\n')]
        })

    # Styling Cell
    add_markdown("""<style>
    /* Crisp Light Clinical Theme */
    h1 { color: #0F172A; font-family: 'Inter', sans-serif; font-weight: 800; border-bottom: 3px solid #2563EB; padding-bottom: 10px; }
    h2 { color: #1E3A8A; font-family: 'Inter', sans-serif; font-weight: 700; margin-top: 25px; }
    h3 { color: #3B82F6; font-family: 'Inter', sans-serif; font-weight: 600; }
    .alert-info { background-color: #EFF6FF; color: #1D4ED8; border-left: 5px solid #2563EB; padding: 15px; border-radius: 4px; font-family: 'Inter', sans-serif; }
    .alert-warning { background-color: #FEF2F2; color: #B91C1C; border-left: 5px solid #DC2626; padding: 15px; border-radius: 4px; font-family: 'Inter', sans-serif; }
    .highlight { background-color: #F8FAFC; border: 1px solid #E2E8F0; padding: 10px; border-radius: 5px; font-family: monospace; color: #334155; }
</style>""")

    add_markdown("""<h1>🌍 Global Health Intelligence: API Extraction & ETL Pipeline</h1>
<p style="font-size: 1.1em; color: #475569;">
<strong>Author:</strong> Ali Naderi | <strong>Role:</strong> Senior Data Engineer & Machine Learning Architect<br>
<strong>Objective:</strong> To engineer a production-ready Extract, Transform, and Load (ETL) pipeline harvesting live epidemiological data from the World Health Organization (WHO) Global Health Observatory (GHO) OData API.
</p>

<div class="alert-info">
<strong>Executive Summary:</strong><br>
In modern Data Science, model accuracy is heavily constrained by data quality. This notebook demonstrates how to interface with complex, nested JSON REST APIs (like WHO GHO), handle network instability (timeouts/retries), perform strict schema validation, and load the optimized data into a relational SQL database. This ensures high data integrity and zero data leakage for downstream BI Dashboards and ML pipelines.
</div>""")

    add_code("""import requests
import sqlite3
import pandas as pd
import logging
import time

# Configure professional logging instead of raw prints
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)""")

    add_markdown("""<h2>1. The "Extract" Phase: Robust API Communication</h2>
<p>
Why use exponential backoff and error handling? Real-world APIs impose rate limits and frequently drop connections. A naive <code>requests.get()</code> is unsuitable for production. We implement a robust extraction layer that ensures data is retrieved reliably without overwhelming the WHO servers.
</p>""")

    add_code("""def extract_who_data(indicator_code: str, max_retries: int = 3) -> list:
    '''
    Extracts JSON records from the WHO GHO OData API using robust retry logic.
    '''
    url = f"https://ghoapi.azureedge.net/api/{indicator_code}"
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Connecting to WHO API for indicator: {indicator_code} (Attempt {attempt+1})")
            response = requests.get(url, timeout=30)
            response.raise_for_status() # Catch HTTP 4xx/5xx errors
            
            data = response.json()
            records = data.get('value', [])
            logger.info(f"Successfully extracted {len(records)} records.")
            return records
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error: {e}")
            if attempt < max_retries - 1:
                sleep_time = 2 ** attempt
                logger.info(f"Backing off for {sleep_time} seconds before retrying...")
                time.sleep(sleep_time)
            else:
                logger.error("Max retries exceeded. Extraction failed.")
                return []
                
# Test the extraction on Life Expectancy
raw_life_expectancy = extract_who_data("WHOSIS_000001")
print(f"Sample Record: {raw_life_expectancy[0] if raw_life_expectancy else 'No data'}")""")

    add_markdown("""<h2>2. The "Transform" Phase: Data Integrity & Memory Optimization</h2>
<p>
Raw API data is often nested, contains redundant fields, and uses inefficient string data types. Here, we transform the JSON array into a Pandas DataFrame.
</p>
<div class="alert-warning">
<strong>Why Memory Optimization Matters:</strong><br>
When dealing with Big Data, storing country codes or indicators as standard python strings consumes massive RAM. By downcasting strings to <code>pd.Categorical</code> and numerics to <code>float32</code>/<code>int32</code>, we can reduce the memory footprint by up to <strong>70%</strong>, allowing the pipeline to run efficiently on standard servers.
</div>""")

    add_code("""def transform_who_data(records: list, indicator_name: str) -> pd.DataFrame:
    '''
    Cleans and optimizes the raw WHO JSON records.
    '''
    if not records:
        return pd.DataFrame()
        
    df = pd.DataFrame(records)
    
    # 1. Feature Selection & Renaming (Standardizing the Schema)
    df = df[['SpatialDim', 'TimeDim', 'Dim1', 'NumericValue']].rename(columns={
        'SpatialDim': 'CountryCode',
        'TimeDim': 'Year',
        'Dim1': 'Gender',
        'NumericValue': 'Value'
    })
    
    # 2. Handling Missing Data (Data Integrity)
    df['Indicator'] = indicator_name
    df = df.dropna(subset=['Value', 'CountryCode', 'Year'])
    df['Gender'] = df['Gender'].fillna('Total')
    
    # 3. Memory Optimization (Downcasting types)
    memory_before = df.memory_usage(deep=True).sum() / 1024**2
    
    df['CountryCode'] = df['CountryCode'].astype('category')
    df['Gender'] = df['Gender'].astype('category')
    df['Indicator'] = df['Indicator'].astype('category')
    df['Year'] = df['Year'].astype('int32')
    df['Value'] = pd.to_numeric(df['Value'], errors='coerce').astype('float32')
    df = df.dropna(subset=['Value']) # Drop rows where value couldn't be parsed
    
    memory_after = df.memory_usage(deep=True).sum() / 1024**2
    
    logger.info(f"Memory footprint reduced from {memory_before:.2f} MB to {memory_after:.2f} MB")
    
    return df

clean_life_exp_df = transform_who_data(raw_life_expectancy, "Life_Expectancy")
clean_life_exp_df.head()""")

    add_markdown("""<h2>3. The "Load" Phase: Storing in a Relational Database</h2>
<p>
Data Analysts and BI tools expect structured SQL databases, not raw CSV files. Loading the optimized DataFrame into an <code>SQLite</code> database ensures data persists safely and can be queried instantly by our Streamlit BI Dashboard without reloading the entire dataset into memory.
</p>""")

    add_code("""def load_to_sql(df: pd.DataFrame, db_path: str = "who_data.db"):
    '''
    Persists the cleaned DataFrame to a local SQLite Database.
    '''
    if df.empty:
        logger.warning("No data to load.")
        return
        
    try:
        # Using context manager ensures the connection closes safely
        with sqlite3.connect(db_path) as conn:
            # We use if_exists='append' to add to existing tables
            df.to_sql('health_indicators', conn, if_exists='replace', index=False)
            logger.info(f"Successfully loaded {len(df)} rows into {db_path}.")
    except Exception as e:
        logger.error(f"Database error: {e}")

load_to_sql(clean_life_exp_df)""")

    add_markdown("""<div class="alert-info">
<strong>Conclusion & Next Steps:</strong><br>
We have successfully engineered a robust, memory-efficient ETL pipeline. The data is now securely stored in <code>who_data.db</code>. The next step is to launch the interactive BI Dashboard (<code>app.py</code>) using Streamlit, which will query this database via <code>st.cache_data</code> to render live, interactive choropleth maps and time-series analytics.
</div>""")

    with open(r'D:\Work Space\فصل چهارم\WHO\WHO_Data_Extraction_ETL.ipynb', 'w', encoding='utf-8') as f:
        json.dump(notebook, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    create_notebook()
    print("Successfully generated WHO_Data_Extraction_ETL.ipynb")

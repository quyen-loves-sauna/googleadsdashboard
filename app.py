import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from datetime import datetime, timedelta
import yaml
import tempfile
import os
import re

# Page config
st.set_page_config(
    page_title="Google Ads Performance Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 1rem;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        text-align: center;
    }
    .metric-value {
        font-size: 2rem;
        font-weight: bold;
        color: #1f77b4;
    }
    .metric-label {
        font-size: 0.9rem;
        color: #555;
        margin-top: 0.5rem;
    }
    .positive-change {
        color: #28a745;
        font-weight: bold;
    }
    .negative-change {
        color: #dc3545;
        font-weight: bold;
    }
    div[data-testid="stHorizontalBlock"] {
        overflow-x: auto;
    }
    .dataframe-container {
        overflow-x: auto;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'client' not in st.session_state:
    st.session_state.client = None
if 'customer_id' not in st.session_state:
    st.session_state.customer_id = None
if 'data_loaded' not in st.session_state:
    st.session_state.data_loaded = False
if 'aggregate_data' not in st.session_state:
    st.session_state.aggregate_data = None
if 'campaign_data' not in st.session_state:
    st.session_state.campaign_data = None
if 'product_data' not in st.session_state:
    st.session_state.product_data = None
if 'daily_data' not in st.session_state:
    st.session_state.daily_data = None
if 'daily_data_camp' not in st.session_state:
    st.session_state.daily_data_camp = None
if 'change_history_data' not in st.session_state:
    st.session_state.change_history_data = None
if 'daily_data_comparison' not in st.session_state:
    st.session_state.daily_data_comparison = None
if 'daily_data_camp_comparison' not in st.session_state:
    st.session_state.daily_data_camp_comparison = None

# Helper Functions
def create_google_ads_client(developer_token, client_id, client_secret, refresh_token, login_customer_id=None):
    """Create Google Ads API client from credentials"""
    try:
        config_dict = {
            "developer_token": developer_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "use_proto_plus": True
        }
        
        if login_customer_id:
            config_dict["login_customer_id"] = login_customer_id
        
        # Create temporary yaml file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config_dict, f)
            config_file = f.name
        
        client = GoogleAdsClient.load_from_dict(config_dict)
        
        # Clean up temp file
        os.unlink(config_file)
        
        return client
    except Exception as e:
        st.error(f"Error creating Google Ads client: {str(e)}")
        return None

def format_date_for_query(date_obj):
    """Format date for Google Ads query"""
    return date_obj.strftime('%Y-%m-%d')

def calculate_metrics(row):
    """Calculate derived metrics"""
    metrics = {}
    
    # Basic metrics
    metrics['cost'] = row.get('cost', 0) / 1_000_000  # Convert micros to currency
    metrics['clicks'] = row.get('clicks', 0)
    metrics['impressions'] = row.get('impressions', 0)
    metrics['conversions'] = row.get('conversions', 0)
    metrics['conversions_value'] = row.get('conversions_value', 0)
    
    # Calculated metrics
    metrics['cpc'] = metrics['cost'] / metrics['clicks'] if metrics['clicks'] > 0 else 0
    metrics['ctr'] = (metrics['clicks'] / metrics['impressions'] * 100) if metrics['impressions'] > 0 else 0
    metrics['cost_per_conv'] = metrics['cost'] / metrics['conversions'] if metrics['conversions'] > 0 else 0
    metrics['conv_value_cost'] = metrics['conversions_value'] / metrics['cost'] if metrics['cost'] > 0 else 0
    metrics['aov'] = metrics['conversions_value'] / metrics['conversions'] if metrics['conversions'] > 0 else 0
    
    return metrics

def fetch_campaign_performance(client, customer_id, start_date, end_date):
    """Fetch campaign performance data with budget"""
    try:
        ga_service = client.get_service("GoogleAdsService")
        
        query = f"""
            SELECT
                campaign.id,
                campaign.name,
                campaign.status,
                campaign_budget.amount_micros,
                metrics.cost_micros,
                metrics.clicks,
                metrics.impressions,
                metrics.conversions,
                metrics.conversions_value,
                metrics.ctr,
                metrics.average_cpc
            FROM campaign
            WHERE segments.date BETWEEN '{format_date_for_query(start_date)}' 
                AND '{format_date_for_query(end_date)}'
                AND campaign.status != 'REMOVED'
            ORDER BY metrics.cost_micros DESC
        """
        
        response = ga_service.search(customer_id=customer_id, query=query)
        
        data = []
        for row in response:
            # Get budget amount (convert from micros)
            budget = 0
            if hasattr(row, 'campaign_budget') and hasattr(row.campaign_budget, 'amount_micros'):
                budget = row.campaign_budget.amount_micros / 1_000_000
            
            campaign_data = {
                'campaign_id': row.campaign.id,
                'campaign_name': row.campaign.name,
                'campaign_status': row.campaign.status.name,
                'budget': budget,
                'cost': row.metrics.cost_micros,
                'clicks': row.metrics.clicks,
                'impressions': row.metrics.impressions,
                'conversions': row.metrics.conversions,
                'conversions_value': row.metrics.conversions_value,
            }
            data.append(campaign_data)
        
        return pd.DataFrame(data)
    
    except GoogleAdsException as ex:
        st.error(f"Google Ads API error: {ex}")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error fetching campaign data: {str(e)}")
        return pd.DataFrame()

def fetch_product_performance(client, customer_id, start_date, end_date):
    """Fetch product-level performance data"""
    try:
        ga_service = client.get_service("GoogleAdsService")
        
        query = f"""
            SELECT
                campaign.name,
                segments.product_title,
                segments.product_item_id,
                metrics.cost_micros,
                metrics.clicks,
                metrics.impressions,
                metrics.conversions,
                metrics.conversions_value
            FROM shopping_performance_view
            WHERE segments.date BETWEEN '{format_date_for_query(start_date)}' 
                AND '{format_date_for_query(end_date)}'
            ORDER BY metrics.cost_micros DESC
        """
        
        response = ga_service.search(customer_id=customer_id, query=query)
        
        data = []
        for row in response:
            product_data = {
                'campaign_name': row.campaign.name,
                'product_title': row.segments.product_title,
                'product_item_id': row.segments.product_item_id,
                'cost': row.metrics.cost_micros,
                'clicks': row.metrics.clicks,
                'impressions': row.metrics.impressions,
                'conversions': row.metrics.conversions,
                'conversions_value': row.metrics.conversions_value,
            }
            data.append(product_data)
        
        return pd.DataFrame(data)
    
    except GoogleAdsException as ex:
        st.error(f"Google Ads API error: {ex}")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error fetching product data: {str(e)}")
        return pd.DataFrame()

def process_dataframe(df):
    """Process dataframe to add calculated metrics"""
    if df.empty:
        return df
    
    df['cost'] = df['cost'] / 1_000_000  # Convert micros to currency
    df['cpc'] = df.apply(lambda x: x['cost'] / x['clicks'] if x['clicks'] > 0 else 0, axis=1)
    df['ctr'] = df.apply(lambda x: (x['clicks'] / x['impressions'] * 100) if x['impressions'] > 0 else 0, axis=1)
    df['cost_per_conv'] = df.apply(lambda x: x['cost'] / x['conversions'] if x['conversions'] > 0 else 0, axis=1)
    df['conv_value_cost'] = df.apply(lambda x: x['conversions_value'] / x['cost'] if x['cost'] > 0 else 0, axis=1)
    df['aov'] = df.apply(lambda x: x['conversions_value'] / x['conversions'] if x['conversions'] > 0 else 0, axis=1)
    
    return df

def recalculate_metrics(df):
    """Recalculate derived metrics from already-converted cost values"""
    if df.empty:
        return df
    
    # DO NOT convert cost again - it's already in currency units
    df['cpc'] = df.apply(lambda x: x['cost'] / x['clicks'] if x['clicks'] > 0 else 0, axis=1)
    df['ctr'] = df.apply(lambda x: (x['clicks'] / x['impressions'] * 100) if x['impressions'] > 0 else 0, axis=1)
    df['cost_per_conv'] = df.apply(lambda x: x['cost'] / x['conversions'] if x['conversions'] > 0 else 0, axis=1)
    df['conv_value_cost'] = df.apply(lambda x: x['conversions_value'] / x['cost'] if x['cost'] > 0 else 0, axis=1)
    df['aov'] = df.apply(lambda x: x['conversions_value'] / x['conversions'] if x['conversions'] > 0 else 0, axis=1)
    
    return df

def calculate_share_metrics(df):
    """Calculate Share of Cost (SoC), Share of Revenue (SoR), and their ratio"""
    if df.empty:
        return df
    
    total_cost = df['cost'].sum()
    total_revenue = df['conversions_value'].sum()
    
    # Calculate share percentages
    if total_cost > 0:
        df['soc'] = (df['cost'] / total_cost * 100)
    else:
        df['soc'] = 0
    
    if total_revenue > 0:
        df['sor'] = (df['conversions_value'] / total_revenue * 100)
    else:
        df['sor'] = 0
    
    # Calculate ratio (SoC/SoR - lower is better, means more revenue share than cost share)
    df['soc_sor_ratio'] = df.apply(
        lambda row: row['soc'] / row['sor'] if row['sor'] > 0 else 0,
        axis=1
    )
    
    return df

def calculate_last_3_days_metrics(daily_df, campaign_budgets=None):
    """Calculate last 3 days vs previous 3 days metrics for campaigns"""
    if daily_df is None or daily_df.empty:
        return pd.DataFrame()
    
    try:
        # Use the actual date range from the data, not today
        max_date = daily_df['date'].max()
        min_date = daily_df['date'].min()
        
        # Last 3 days of the dataset
        last_3_start = max_date - timedelta(days=2)  # Last 3 days including max_date
        
        # Previous 3 days before that
        prev_3_end = last_3_start - timedelta(days=1)
        prev_3_start = prev_3_end - timedelta(days=2)
        
        # Check if we have enough data
        if (max_date - min_date).days < 5:
            # Not enough data for comparison
            return pd.DataFrame()
        
        # Filter data for last 3 days and previous 3 days
        last_3 = daily_df[daily_df['date'] >= last_3_start].copy()
        prev_3 = daily_df[(daily_df['date'] >= prev_3_start) & (daily_df['date'] <= prev_3_end)].copy()
        
        if last_3.empty or prev_3.empty:
            return pd.DataFrame()
        
        # Aggregate by campaign
        last_3_agg = last_3.groupby('campaign_name').agg({
            'cost': 'sum',
            'conversions_value': 'sum'
        }).reset_index()
        last_3_agg.columns = ['campaign_name', 'cost_last3', 'revenue_last3']
        
        prev_3_agg = prev_3.groupby('campaign_name').agg({
            'cost': 'sum',
            'conversions_value': 'sum'
        }).reset_index()
        prev_3_agg.columns = ['campaign_name', 'cost_prev3', 'revenue_prev3']
        
        # Merge
        merged = last_3_agg.merge(prev_3_agg, on='campaign_name', how='outer')
        merged = merged.fillna(0)
        
        # Calculate deltas (% change)
        merged['spend_delta_3d'] = merged.apply(
            lambda x: ((x['cost_last3'] - x['cost_prev3']) / x['cost_prev3'] * 100) if x['cost_prev3'] > 0 else 0,
            axis=1
        )
        
        merged['revenue_delta_3d'] = merged.apply(
            lambda x: ((x['revenue_last3'] - x['revenue_prev3']) / x['revenue_prev3'] * 100) if x['revenue_prev3'] > 0 else 0,
            axis=1
        )
        
        # Calculate delta ratio (revenue delta / spend delta)
        merged['delta_ratio_3d'] = merged.apply(
            lambda x: x['revenue_delta_3d'] / x['spend_delta_3d'] if abs(x['spend_delta_3d']) > 0.1 else 0,
            axis=1
        )
        
        # Add budget % spent if budgets provided
        if campaign_budgets is not None and not campaign_budgets.empty:
            merged = merged.merge(campaign_budgets[['campaign_name', 'budget']], on='campaign_name', how='left')
            merged['budget_spent_3d_pct'] = merged.apply(
                lambda x: (x['cost_last3'] / x['budget'] * 100) if x.get('budget', 0) > 0 else 0,
                axis=1
            )
        
        # Keep only needed columns
        result_cols = ['campaign_name', 'cost_last3', 'spend_delta_3d', 'revenue_delta_3d', 'delta_ratio_3d']
        if 'budget_spent_3d_pct' in merged.columns:
            result_cols.append('budget_spent_3d_pct')
        
        return merged[result_cols]
        
    except Exception as e:
        print(f"Error calculating last 3 days metrics: {e}")
        return pd.DataFrame()

def format_delta_html(value, reverse_colors=False):
    """Format delta with colored arrow for HTML display"""
    if abs(value) < 0.1:
        return "0.0%"
    
    arrow = "▲" if value > 0 else "▼"
    
    # Determine color based on direction and context
    if reverse_colors:
        # For costs - lower is better (green), higher is worse (red)
        color = "#dc2626" if value > 0 else "#059669"
    else:
        # For revenue - higher is better (green), lower is worse (red)
        color = "#059669" if value > 0 else "#dc2626"
    
    return f'<span style="color: {color}; font-weight: 600;">{arrow} {abs(value):.1f}%</span>'

def fetch_daily_performance(client, customer_id, start_date, end_date):
    """Fetch daily performance data for time-series charts"""
    try:
        ga_service = client.get_service("GoogleAdsService")
        
        query = f"""
            SELECT
                segments.date,
                campaign.name,
                metrics.cost_micros,
                metrics.clicks,
                metrics.impressions,
                metrics.conversions,
                metrics.conversions_value
            FROM campaign
            WHERE segments.date BETWEEN '{format_date_for_query(start_date)}' 
                AND '{format_date_for_query(end_date)}'
                AND campaign.status != 'REMOVED'
            ORDER BY segments.date
        """
        
        response = ga_service.search(customer_id=customer_id, query=query)
        
        data = []
        for row in response:
            daily_data = {
                'date': row.segments.date,
                'campaign_name': row.campaign.name,
                'cost': row.metrics.cost_micros / 1_000_000,
                'clicks': row.metrics.clicks,
                'impressions': row.metrics.impressions,
                'conversions': row.metrics.conversions,
                'conversions_value': row.metrics.conversions_value,
            }
            data.append(daily_data)
        
        df = pd.DataFrame(data)
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            # Calculate derived metrics
            df['cpc'] = df.apply(lambda x: x['cost'] / x['clicks'] if x['clicks'] > 0 else 0, axis=1)
            df['ctr'] = df.apply(lambda x: (x['clicks'] / x['impressions'] * 100) if x['impressions'] > 0 else 0, axis=1)
            df['cost_per_conv'] = df.apply(lambda x: x['cost'] / x['conversions'] if x['conversions'] > 0 else 0, axis=1)
            df['conv_value_cost'] = df.apply(lambda x: x['conversions_value'] / x['cost'] if x['cost'] > 0 else 0, axis=1)
            df['aov'] = df.apply(lambda x: x['conversions_value'] / x['conversions'] if x['conversions'] > 0 else 0, axis=1)
        
        return df
    
    except Exception as e:
        st.error(f"Error fetching daily data: {str(e)}")
        return pd.DataFrame()

def fetch_change_history(client, customer_id, start_date, end_date):
    """Fetch campaign-level change history for budget and bid strategy changes"""
    try:
        ga_service = client.get_service("GoogleAdsService")
        
        # Format datetime for query (need full datetime, not just date)
        start_datetime = f"{format_date_for_query(start_date)} 00:00:00"
        end_datetime = f"{format_date_for_query(end_date)} 23:59:59"
        
        query = f"""
            SELECT
                change_event.change_date_time,
                change_event.change_resource_type,
                change_event.resource_change_operation,
                change_event.change_resource_name,
                change_event.old_resource,
                change_event.new_resource,
                campaign.name,
                campaign.id
            FROM change_event
            WHERE change_event.change_date_time >= '{start_datetime}'
              AND change_event.change_date_time <= '{end_datetime}'
              AND change_event.change_resource_type IN ('CAMPAIGN', 'CAMPAIGN_BUDGET')
            ORDER BY change_event.change_date_time DESC
            LIMIT 1000
        """
        
        response = ga_service.search(customer_id=customer_id, query=query)
        
        data = []
        for row in response:
            # Convert to strings
            resource_type_str = str(row.change_event.change_resource_type)
            resource_name = str(row.change_event.change_resource_name).lower()
            operation = str(row.change_event.resource_change_operation)
            
            # Get old and new resource as strings
            old_resource = str(row.change_event.old_resource) if hasattr(row.change_event, 'old_resource') else ''
            new_resource = str(row.change_event.new_resource) if hasattr(row.change_event, 'new_resource') else ''
            
            # Combine for searching
            change_content = f"{old_resource} {new_resource} {resource_name}".lower()
            
            # Check if it's a budget change
            is_budget = (
                'BUDGET' in resource_type_str.upper() or 
                'budget' in resource_name or
                'amount_micros' in change_content or
                'budget_amount' in change_content
            )
            
            # Check if it's a bid strategy change
            is_bid_strategy = any(keyword in change_content for keyword in [
                'bidding_strategy', 'bid_strategy', 'maximize_conversions', 
                'maximize_conversion_value', 'target_cpa', 'target_roas', 
                'manual_cpc', 'manual_cpm', 'target_spend', 'target_impression_share',
                'percent_cpc', 'commission'
            ])
            
            # Only include budget or bid strategy changes
            if not (is_budget or is_bid_strategy):
                continue
            
            # Determine change type
            change_type = 'Budget Change' if is_budget else 'Bid Strategy Change'
            
            # Extract change details
            change_details = extract_change_details(old_resource, new_resource, is_budget, is_bid_strategy)
            
            change_data = {
                'change_datetime': row.change_event.change_date_time,
                'resource_type': resource_type_str,
                'operation': operation,
                'resource_name': row.change_event.change_resource_name,
                'campaign_name': row.campaign.name if hasattr(row, 'campaign') and hasattr(row.campaign, 'name') else 'Unknown',
                'campaign_id': str(row.campaign.id) if hasattr(row, 'campaign') and hasattr(row.campaign, 'id') else '',
                'change_type': change_type,
                'change_details': change_details,
                'old_resource': old_resource,
                'new_resource': new_resource
            }
            
            data.append(change_data)
        
        df = pd.DataFrame(data)
        
        if not df.empty:
            # Parse datetime
            df['change_datetime'] = pd.to_datetime(df['change_datetime'])
            df['date'] = df['change_datetime'].dt.date
            df['time'] = df['change_datetime'].dt.strftime('%H:%M:%S')
            
            # Clean up operation names
            df['operation'] = df['operation'].replace({
                'CREATE': 'Created',
                'UPDATE': 'Updated',
                'REMOVE': 'Removed'
            })
        
        return df
    
    except GoogleAdsException as ex:
        st.error(f"Google Ads API error fetching change history: {ex}")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error fetching change history: {str(e)}")
        return pd.DataFrame()

def extract_change_details(old_resource, new_resource, is_budget, is_bid_strategy):
    """Extract human-readable change details from old and new resource strings"""
    try:
        details = []
        
        if is_budget:
            # Extract budget amounts
            old_amount = extract_budget_amount(old_resource)
            new_amount = extract_budget_amount(new_resource)
            
            if old_amount and new_amount:
                # Convert micros to currency
                old_value = old_amount / 1_000_000
                new_value = new_amount / 1_000_000
                
                if old_value != new_value:
                    change_direction = "increased" if new_value > old_value else "decreased"
                    details.append(f"Budget {change_direction} from {old_value:.2f} to {new_value:.2f}")
            elif new_amount:
                new_value = new_amount / 1_000_000
                details.append(f"Budget set to {new_value:.2f}")
            elif old_amount:
                details.append(f"Budget removed")
        
        if is_bid_strategy:
            # Extract bid strategy changes
            old_strategy = extract_bid_strategy(old_resource)
            new_strategy = extract_bid_strategy(new_resource)
            
            if old_strategy and new_strategy and old_strategy != new_strategy:
                details.append(f"Strategy changed from {old_strategy} to {new_strategy}")
            elif new_strategy:
                details.append(f"Strategy set to {new_strategy}")
            
            # Extract Target CPA
            old_cpa = extract_target_cpa(old_resource)
            new_cpa = extract_target_cpa(new_resource)
            if old_cpa and new_cpa and old_cpa != new_cpa:
                old_val = old_cpa / 1_000_000
                new_val = new_cpa / 1_000_000
                change_dir = "increased" if new_val > old_val else "decreased"
                details.append(f"Target CPA {change_dir} from {old_val:.2f} to {new_val:.2f}")
            
            # Extract Target ROAS
            old_roas = extract_target_roas(old_resource)
            new_roas = extract_target_roas(new_resource)
            if old_roas and new_roas and old_roas != new_roas:
                old_pct = old_roas * 100
                new_pct = new_roas * 100
                change_dir = "increased" if new_roas > old_roas else "decreased"
                details.append(f"Target ROAS {change_dir} from {old_pct:.0f}% to {new_pct:.0f}%")
        
        return " | ".join(details) if details else "Change detected"
    
    except Exception as e:
        return "Change detected"

def extract_budget_amount(resource_str):
    """Extract budget amount in micros from resource string"""
    try:
        # Look for amount_micros: <value>
        match = re.search(r'amount_micros:\s*(\d+)', resource_str)
        if match:
            return int(match.group(1))
    except:
        pass
    return None

def extract_bid_strategy(resource_str):
    """Extract bid strategy name from resource string"""
    try:
        if 'maximize_conversions' in resource_str.lower():
            return 'Maximize Conversions'
        elif 'maximize_conversion_value' in resource_str.lower():
            return 'Maximize Conversion Value'
        elif 'target_cpa' in resource_str.lower():
            return 'Target CPA'
        elif 'target_roas' in resource_str.lower():
            return 'Target ROAS'
        elif 'target_spend' in resource_str.lower():
            return 'Target Spend'
        elif 'manual_cpc' in resource_str.lower():
            return 'Manual CPC'
        elif 'manual_cpm' in resource_str.lower():
            return 'Manual CPM'
        elif 'percent_cpc' in resource_str.lower():
            return 'Commission'
    except:
        pass
    return None

def extract_target_cpa(resource_str):
    """Extract target CPA in micros from resource string"""
    try:
        # Look for target_cpa_micros: <value>
        match = re.search(r'target_cpa_micros:\s*(\d+)', resource_str)
        if match:
            return int(match.group(1))
    except:
        pass
    return None

def extract_target_roas(resource_str):
    """Extract target ROAS as decimal from resource string"""
    try:
        # Look for target_roas: <value>
        match = re.search(r'target_roas:\s*([\d.]+)', resource_str)
        if match:
            return float(match.group(1))
    except:
        pass
    return None

def create_time_series_chart(df, metric, metric_label):
    """Create beautiful time-series chart similar to the uploaded image"""
    
    # Aggregate by date
    daily_agg = df.groupby('date')[metric].sum().reset_index()
    
    # Create figure
    fig = go.Figure()
    
    # Add main line with gradient color
    fig.add_trace(go.Scatter(
        x=daily_agg['date'],
        y=daily_agg[metric],
        mode='lines',
        name=metric_label,
        line=dict(
            color='rgb(0, 204, 204)',  # Teal/cyan color
            width=3,
            shape='spline'  # Smooth curves
        ),
        fill='tozeroy',
        fillcolor='rgba(0, 204, 204, 0.1)'
    ))
    
    # Update layout for clean appearance
    fig.update_layout(
        title=dict(
            text=f"{metric_label} Over Time",
            font=dict(size=20, color='#333')
        ),
        xaxis=dict(
            title="",
            showgrid=True,
            gridcolor='rgba(200, 200, 200, 0.2)',
            showline=True,
            linecolor='rgba(200, 200, 200, 0.5)'
        ),
        yaxis=dict(
            title="",
            showgrid=True,
            gridcolor='rgba(200, 200, 200, 0.2)',
            showline=False
        ),
        plot_bgcolor='white',
        paper_bgcolor='white',
        hovermode='x unified',
        height=400,
        margin=dict(l=50, r=50, t=80, b=50),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.2,
            xanchor="center",
            x=0.5,
            font=dict(size=12)
        )
    )
    
    return fig

def create_multi_metric_chart(df_current, df_comparison, selected_metrics, metric_labels, show_comparison=False):
    """
    Create chart with up to 3 metrics and optional comparison period
    """
    
    fig = go.Figure()
    
    # Colors for current period metrics
    colors = ['#1e88e5', '#43a047', '#e53935']  # Blue, Green, Red
    # Colors for comparison period (lighter versions)
    comparison_colors = ['#90caf9', '#81c784', '#e57373']
    
    # Add current period metrics
    for idx, metric in enumerate(selected_metrics):
        # Aggregate daily data
        daily_agg = df_current.groupby('date')[metric].sum().reset_index()
        
        # Determine which y-axis to use
        yaxis_ref = 'y' if idx == 0 else f'y{idx+1}'
        
        fig.add_trace(go.Scatter(
            x=daily_agg['date'],
            y=daily_agg[metric],
            mode='lines+markers',
            name=f"{metric_labels[metric]}",
            line=dict(color=colors[idx], width=3),
            marker=dict(size=6),
            yaxis=yaxis_ref,
            showlegend=True
        ))
    
    # Add comparison period metrics if requested and available
    if show_comparison and df_comparison is not None and not df_comparison.empty:
        for idx, metric in enumerate(selected_metrics):
            daily_agg_comp = df_comparison.groupby('date')[metric].sum().reset_index()
            
            yaxis_ref = 'y' if idx == 0 else f'y{idx+1}'
            
            fig.add_trace(go.Scatter(
                x=daily_agg_comp['date'],
                y=daily_agg_comp[metric],
                mode='lines',
                name=f"{metric_labels[metric]} (Comparison)",
                line=dict(color=comparison_colors[idx], width=2, dash='dash'),
                yaxis=yaxis_ref,
                showlegend=True,
                opacity=0.7
            ))
    
    # Configure layout with multiple y-axes
    layout_config = {
        'title': dict(
            text="Performance Over Time",
            font=dict(size=24, color='#111827', family='Arial, sans-serif', weight=700)
        ),
        'xaxis': dict(
            title=dict(
                text="Date",
                font=dict(size=16, color='#374151', weight=600)
            ),
            showgrid=True,
            gridcolor='rgba(200, 200, 200, 0.2)',
            tickfont=dict(size=13)
        ),
        'yaxis': dict(
            title=dict(
                text=metric_labels[selected_metrics[0]],
                font=dict(size=16, color='#374151', weight=600)
            ),
            showgrid=True,
            gridcolor='rgba(200, 200, 200, 0.2)',
            side='left',
            tickfont=dict(size=13)
        ),
        'plot_bgcolor': 'white',
        'paper_bgcolor': 'white',
        'hovermode': 'x unified',
        'height': 500,
        'legend': dict(
            orientation="h",
            yanchor="bottom",
            y=-0.25,
            xanchor="center",
            x=0.5,
            font=dict(size=13, weight=600)
        ),
        'margin': dict(l=60, r=60, t=80, b=100)
    }
    
    # Add secondary y-axes for additional metrics
    if len(selected_metrics) > 1:
        layout_config['yaxis2'] = dict(
            title=dict(
                text=metric_labels[selected_metrics[1]],
                font=dict(size=16, color='#374151', weight=600)
            ),
            overlaying='y',
            side='right',
            showgrid=False,
            tickfont=dict(size=13)
        )
    
    if len(selected_metrics) > 2:
        layout_config['yaxis3'] = dict(
            title=dict(
                text=metric_labels[selected_metrics[2]],
                font=dict(size=16, color='#374151', weight=600)
            ),
            overlaying='y',
            side='right',
            anchor='free',
            position=0.97,
            showgrid=False,
            tickfont=dict(size=13)
        )
    
    fig.update_layout(**layout_config)
    
    return fig

def extract_percentage_change(details_str):
    """Extract percentage change from change details string"""
    try:
        # Look for patterns like "from X to Y"
        match = re.search(r'from ([\d.]+)\D* to ([\d.]+)', details_str)
        if match:
            old_val = float(match.group(1))
            new_val = float(match.group(2))
            if old_val > 0:
                pct_change = abs((new_val - old_val) / old_val * 100)
                return pct_change
    except:
        pass
    return 0

def add_change_annotations(fig, df_changes, campaign_name, date_range, min_budget_pct=0, min_bid_pct=0):
    """
    Add change markers and annotations to campaign performance chart
    """
    
    # Return early if no change data
    if df_changes is None or df_changes.empty:
        return fig
    
    # Check if required columns exist
    required_cols = ['campaign_name', 'date', 'change_type', 'change_details']
    if not all(col in df_changes.columns for col in required_cols):
        return fig
    
    try:
        # Filter changes for this campaign and date range
        campaign_changes = df_changes[
            (df_changes['campaign_name'] == campaign_name) &
            (df_changes['date'] >= date_range[0]) &
            (df_changes['date'] <= date_range[1])
        ].copy()
        
        if campaign_changes.empty:
            return fig
        
        shapes = []
        annotations = []
        
        for idx, change in campaign_changes.iterrows():
            change_date = change['date']
            change_type = change['change_type']
            details = change['change_details']
            
            # Determine if we should show this annotation
            show_annotation = False
            color = '#6b7280'  # Default gray
            
            if change_type == 'Budget Change':
                pct_change = extract_percentage_change(details)
                # Always show if budget was set/removed, or if it meets threshold
                if 'set to' in details or 'removed' in details or pct_change >= min_budget_pct:
                    show_annotation = True
                    color = '#f59e0b'  # Orange for budget
            
            elif change_type == 'Bid Strategy Change':
                # Always show if strategy type completely changed
                if 'Strategy changed' in details:
                    show_annotation = True
                else:
                    # Check percentage threshold for target adjustments
                    pct_change = extract_percentage_change(details)
                    if pct_change >= min_bid_pct:
                        show_annotation = True
                color = '#8b5cf6'  # Purple for bid strategy
            
            if not show_annotation:
                continue
            
            # Add vertical dashed line
            shapes.append(dict(
                type="line",
                xref="x",
                yref="paper",
                x0=change_date,
                x1=change_date,
                y0=0,
                y1=1,
                line=dict(color=color, width=2, dash="dot"),
                opacity=0.6
            ))
            
            # Add annotation with arrow
            # Truncate details if too long
            short_details = details[:40] + "..." if len(details) > 40 else details
            
            annotations.append(dict(
                x=change_date,
                y=1.02,
                xref="x",
                yref="paper",
                text=f"<b>{change_type.split()[0]}</b><br>{short_details}",
                showarrow=True,
                arrowhead=2,
                arrowsize=1,
                arrowwidth=2,
                arrowcolor=color,
                ax=0,
                ay=-50,
                bgcolor="rgba(255, 255, 255, 0.9)",
                bordercolor=color,
                borderwidth=2,
                borderpad=4,
                font=dict(size=9, color="#111827"),
                align="center"
            ))
        
        # Update figure with annotations
        fig.update_layout(
            shapes=shapes,
            annotations=annotations
        )
    except Exception as e:
        # If there's any error, just return the figure without annotations
        pass
    
    return fig

def calculate_comparison(current_df, comparison_df):
    """Calculate percentage changes between two dataframes"""
    if comparison_df.empty:
        return current_df
    
    # Calculate totals for current
    current_totals = {
        'cost': current_df['cost'].sum(),
        'clicks': current_df['clicks'].sum(),
        'impressions': current_df['impressions'].sum(),
        'conversions': current_df['conversions'].sum(),
        'conversions_value': current_df['conversions_value'].sum(),
    }
    
    # Calculate totals for comparison
    comparison_totals = {
        'cost': comparison_df['cost'].sum(),
        'clicks': comparison_df['clicks'].sum(),
        'impressions': comparison_df['impressions'].sum(),
        'conversions': comparison_df['conversions'].sum(),
        'conversions_value': comparison_df['conversions_value'].sum(),
    }
    
    # Calculate derived metrics
    current_totals['cpc'] = current_totals['cost'] / current_totals['clicks'] if current_totals['clicks'] > 0 else 0
    current_totals['ctr'] = (current_totals['clicks'] / current_totals['impressions'] * 100) if current_totals['impressions'] > 0 else 0
    current_totals['cost_per_conv'] = current_totals['cost'] / current_totals['conversions'] if current_totals['conversions'] > 0 else 0
    current_totals['conv_value_cost'] = current_totals['conversions_value'] / current_totals['cost'] if current_totals['cost'] > 0 else 0
    current_totals['aov'] = current_totals['conversions_value'] / current_totals['conversions'] if current_totals['conversions'] > 0 else 0
    
    comparison_totals['cpc'] = comparison_totals['cost'] / comparison_totals['clicks'] if comparison_totals['clicks'] > 0 else 0
    comparison_totals['ctr'] = (comparison_totals['clicks'] / comparison_totals['impressions'] * 100) if comparison_totals['impressions'] > 0 else 0
    comparison_totals['cost_per_conv'] = comparison_totals['cost'] / comparison_totals['conversions'] if comparison_totals['conversions'] > 0 else 0
    comparison_totals['conv_value_cost'] = comparison_totals['conversions_value'] / comparison_totals['cost'] if comparison_totals['cost'] > 0 else 0
    comparison_totals['aov'] = comparison_totals['conversions_value'] / comparison_totals['conversions'] if comparison_totals['conversions'] > 0 else 0
    
    # Calculate percentage changes
    changes = {}
    for metric in current_totals.keys():
        if comparison_totals[metric] != 0:
            changes[f'{metric}_change'] = ((current_totals[metric] - comparison_totals[metric]) / comparison_totals[metric]) * 100
        else:
            changes[f'{metric}_change'] = 0
    
    return current_totals, comparison_totals, changes

def format_metric_with_change(value, change, metric_type='currency', inverse=False):
    """Format metric with change indicator"""
    if metric_type == 'currency':
        formatted_value = f"${value:,.2f}"
    elif metric_type == 'percentage':
        formatted_value = f"{value:.2f}%"
    elif metric_type == 'number':
        formatted_value = f"{value:,.0f}"
    else:
        formatted_value = f"{value:.2f}"
    
    if change != 0:
        arrow = "↑" if change > 0 else "↓"
        change_class = "positive-change" if (change > 0 and not inverse) or (change < 0 and inverse) else "negative-change"
        change_text = f'<span class="{change_class}">{arrow} {abs(change):.1f}%</span>'
        return f"{formatted_value} {change_text}"
    else:
        return formatted_value

def display_metric_card(label, value, change=None, metric_type='currency', inverse=False):
    """Display a metric card with optional comparison"""
    if change is not None:
        html = f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{format_metric_with_change(value, change, metric_type, inverse)}</div>
        </div>
        """
    else:
        if metric_type == 'currency':
            formatted = f"${value:,.2f}"
        elif metric_type == 'percentage':
            formatted = f"{value:.2f}%"
        elif metric_type == 'number':
            formatted = f"{value:,.0f}"
        else:
            formatted = f"{value:.2f}"
        
        html = f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{formatted}</div>
        </div>
        """
    
    return html

# Main App
def main():
    
    # Custom CSS for BIGGER tabs
    st.markdown("""
    <style>
    /* Force tabs to be much bigger */
    .stTabs [data-baseweb="tab-list"] {
        gap: 24px !important;
        padding: 20px 0 !important;
        margin-bottom: 30px !important;
    }
    
    .stTabs [data-baseweb="tab"] {
        padding: 20px 40px !important;
        font-size: 20px !important;
        font-weight: 600 !important;
        border-radius: 10px !important;
    }
    
    .stTabs [data-baseweb="tab"]:hover {
        background-color: #f3f4f6 !important;
    }
    
    .stTabs [aria-selected="true"] {
        background-color: #eff6ff !important;
        color: #1e40af !important;
        font-size: 22px !important;
        font-weight: 700 !important;
    }
    
    /* Also target the button element inside */
    .stTabs button {
        font-size: 20px !important;
        font-weight: 600 !important;
    }
    
    .stTabs button[aria-selected="true"] {
        font-size: 22px !important;
        font-weight: 700 !important;
    }
    
    /* Target paragraph text inside tabs */
    .stTabs [data-baseweb="tab"] p {
        font-size: 20px !important;
        font-weight: 600 !important;
    }
    
    .stTabs [aria-selected="true"] p {
        font-size: 22px !important;
        font-weight: 700 !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Tab navigation
    if not st.session_state.authenticated:
        tab_list = ["🏠 Welcome & Setup"]
    else:
        tab_list = ["🏠 Welcome & Setup", "📊 Aggregate Overview", "📈 Campaign Breakdown", "🛍️ Product Breakdown", "📜 Change History"]
    
    tabs = st.tabs(tab_list)
    
    # Tab 0: Welcome & Authentication
    with tabs[0]:
        st.markdown('<p class="main-header">Google Ads Performance Dashboard</p>', unsafe_allow_html=True)
        
        if not st.session_state.authenticated:
            st.markdown("""
            ### Welcome to the Google Ads Performance Dashboard!
            
            This application provides comprehensive performance analytics for your Google Ads campaigns:
            
            #### 📊 Features:
            - **Aggregate Overview**: View total performance across all campaigns with filtering options
            - **Campaign Breakdown**: Detailed metrics for each campaign
            - **Product Breakdown**: Product-level performance analysis with filtering
            - **Change History**: Track budget and bid strategy changes at campaign level
            - **Date Comparisons**: Compare performance across different time periods
            - **Interactive Visualizations**: Beautiful charts and metrics cards
            
            #### 🔑 What You'll Need:
            
            To get started, you'll need your Google Ads API credentials:
            
            1. **Developer Token**: Your Google Ads API developer token
            2. **Client ID**: OAuth 2.0 client ID
            3. **Client Secret**: OAuth 2.0 client secret
            4. **Refresh Token**: OAuth 2.0 refresh token
            5. **Customer ID**: Your Google Ads customer ID (without hyphens)
            6. **Login Customer ID** (Optional): Manager account ID if using MCC
            
            #### 📚 How to Get Your Credentials:
            
            1. **Developer Token**: 
               - Go to [Google Ads API Center](https://ads.google.com/aw/apicenter)
               - Request a developer token (standard access is sufficient for most use cases)
            
            2. **OAuth Credentials**:
               - Visit [Google Cloud Console](https://console.cloud.google.com/)
               - Create a new project or select an existing one
               - Enable the Google Ads API
               - Create OAuth 2.0 credentials (Desktop app type)
               - Download the client secret JSON file
            
            3. **Refresh Token**:
               - Use the OAuth Playground or run the authentication script
               - Follow the [authentication guide](https://developers.google.com/google-ads/api/docs/oauth/overview)
            
            ---
            
            ### 🔐 Enter Your Credentials
            """)
            
            with st.form("credentials_form"):
                st.subheader("Google Ads API Credentials")
                
                developer_token = st.text_input(
                    "Developer Token",
                    type="password",
                    help="Your Google Ads API developer token"
                )
                
                col1, col2 = st.columns(2)
                with col1:
                    client_id = st.text_input(
                        "Client ID",
                        help="OAuth 2.0 Client ID"
                    )
                with col2:
                    client_secret = st.text_input(
                        "Client Secret",
                        type="password",
                        help="OAuth 2.0 Client Secret"
                    )
                
                refresh_token = st.text_input(
                    "Refresh Token",
                    type="password",
                    help="OAuth 2.0 Refresh Token"
                )
                
                col1, col2 = st.columns(2)
                with col1:
                    customer_id = st.text_input(
                        "Customer ID",
                        help="Your Google Ads Customer ID (without hyphens, e.g., 1234567890)"
                    )
                with col2:
                    login_customer_id = st.text_input(
                        "Login Customer ID (Optional)",
                        help="Manager account ID if using MCC"
                    )
                
                submitted = st.form_submit_button("🚀 Connect to Google Ads", type="primary")
                
                if submitted:
                    if not all([developer_token, client_id, client_secret, refresh_token, customer_id]):
                        st.error("Please fill in all required fields!")
                    else:
                        with st.spinner("Connecting to Google Ads API..."):
                            client = create_google_ads_client(
                                developer_token,
                                client_id,
                                client_secret,
                                refresh_token,
                                login_customer_id if login_customer_id else None
                            )
                            
                            if client:
                                st.session_state.client = client
                                st.session_state.customer_id = customer_id
                                st.session_state.authenticated = True
                                st.success("✅ Successfully connected to Google Ads!")
                                st.rerun()
                            else:
                                st.error("❌ Failed to connect. Please check your credentials.")
        
        else:
            st.success("✅ Connected to Google Ads API")
            st.info(f"Customer ID: {st.session_state.customer_id}")
            
            if st.button("🔓 Disconnect", type="secondary"):
                st.session_state.authenticated = False
                st.session_state.client = None
                st.session_state.customer_id = None
                st.session_state.data_loaded = False
                st.rerun()
            
            st.markdown("""
            ---
            ### 📊 Navigate to Other Tabs
            
            Use the tabs above to access:
            - **Aggregate Overview**: Total performance metrics
            - **Campaign Breakdown**: Campaign-level analysis
            - **Product Breakdown**: Product-level insights
            - **Change History**: Budget and bid strategy changes
            """)
    
    # Tabs 1-3: Only show if authenticated
    if st.session_state.authenticated:
        
        # Tab 1: Aggregate Overview
        with tabs[1]:
            st.header("📊 Aggregate Overview")
            
            # Date range selector
            col1, col2, col3 = st.columns([2, 2, 1])
            
            with col1:
                start_date = st.date_input(
                    "Start Date",
                    value=datetime.now() - timedelta(days=30),
                    key="agg_start_date"
                )
            
            with col2:
                end_date = st.date_input(
                    "End Date",
                    value=datetime.now(),
                    key="agg_end_date"
                )
            
            with col3:
                compare_option = st.selectbox(
                    "Compare to",
                    ["None", "Previous Period", "Previous Week", "Previous Month", "Previous Year", "Custom"],
                    key="agg_compare"
                )
            
            # Custom comparison dates if selected
            if compare_option == "Custom":
                col1, col2 = st.columns(2)
                with col1:
                    compare_start = st.date_input("Compare Start Date", key="agg_comp_start")
                with col2:
                    compare_end = st.date_input("Compare End Date", key="agg_comp_end")
            
            # Campaign filter
            st.markdown("---")
            col1, col2 = st.columns([4, 1])
            with col1:
                campaign_filter = st.text_input(
                    "Filter by Campaign Name (Optional)",
                    placeholder="Type campaign name...",
                    help="Filter campaigns by name",
                    key="agg_campaign_filter"
                )
            with col2:
                st.write("")  # Spacing
                exact_match = st.checkbox("Exact match", value=False, key="agg_exact_match")
            
            if st.button("📥 Load Data", key="load_agg_data", type="primary"):
                with st.spinner("Fetching data from Google Ads..."):
                    # Fetch current period data
                    campaign_df = fetch_campaign_performance(
                        st.session_state.client,
                        st.session_state.customer_id,
                        start_date,
                        end_date
                    )
                    
                    # Fetch daily data for charts
                    daily_df = fetch_daily_performance(
                        st.session_state.client,
                        st.session_state.customer_id,
                        start_date,
                        end_date
                    )
                    
                    if not campaign_df.empty:
                        campaign_df = process_dataframe(campaign_df)
                        st.session_state.campaign_data = campaign_df
                        st.session_state.daily_data = daily_df
                        
                        # Update campaign filter options
                        campaign_names = ["All Campaigns"] + campaign_df['campaign_name'].unique().tolist()
                        
                        # Fetch comparison data if needed
                        comparison_df = pd.DataFrame()
                        if compare_option != "None":
                            days_diff = (end_date - start_date).days
                            
                            if compare_option == "Previous Period":
                                comp_end = start_date - timedelta(days=1)
                                comp_start = comp_end - timedelta(days=days_diff)
                            elif compare_option == "Previous Week":
                                comp_end = start_date - timedelta(days=1)
                                comp_start = comp_end - timedelta(days=6)
                            elif compare_option == "Previous Month":
                                comp_end = start_date - timedelta(days=1)
                                comp_start = comp_end - timedelta(days=29)
                            elif compare_option == "Previous Year":
                                comp_start = start_date - timedelta(days=365)
                                comp_end = end_date - timedelta(days=365)
                            elif compare_option == "Custom":
                                comp_start = compare_start
                                comp_end = compare_end
                            
                            comparison_df = fetch_campaign_performance(
                                st.session_state.client,
                                st.session_state.customer_id,
                                comp_start,
                                comp_end
                            )
                            
                            if not comparison_df.empty:
                                comparison_df = process_dataframe(comparison_df)
                        
                        st.session_state.aggregate_data = {
                            'current': campaign_df,
                            'comparison': comparison_df,
                            'compare_option': compare_option
                        }
                        st.session_state.data_loaded = True
                        st.success("✅ Data loaded successfully!")
                    else:
                        st.warning("No data found for the selected date range.")
            
            # Display aggregate metrics
            if st.session_state.data_loaded and st.session_state.aggregate_data:
                st.markdown("---")
                
                current_df = st.session_state.aggregate_data['current']
                comparison_df = st.session_state.aggregate_data['comparison']
                compare_opt = st.session_state.aggregate_data['compare_option']
                
                # Filter by campaign if specified
                if campaign_filter and campaign_filter.strip():
                    # Use exact or partial matching based on checkbox
                    if exact_match:
                        current_df = current_df[current_df['campaign_name'] == campaign_filter.strip()]
                        if not comparison_df.empty:
                            comparison_df = comparison_df[comparison_df['campaign_name'] == campaign_filter.strip()]
                    else:
                        current_df = current_df[current_df['campaign_name'].str.contains(campaign_filter, case=False, na=False)]
                        if not comparison_df.empty:
                            comparison_df = comparison_df[comparison_df['campaign_name'].str.contains(campaign_filter, case=False, na=False)]
                    
                    if current_df.empty:
                        st.warning(f"No campaigns found matching '{campaign_filter}'")
                        st.stop()
                    else:
                        match_type = "exactly matching" if exact_match else "containing"
                        st.info(f"Showing data for campaigns {match_type}: '{campaign_filter}' ({len(current_df)} campaign(s))")
                
                # Calculate totals and changes
                if not comparison_df.empty:
                    current_totals, comparison_totals, changes = calculate_comparison(current_df, comparison_df)
                else:
                    current_totals = {
                        'cost': current_df['cost'].sum(),
                        'clicks': current_df['clicks'].sum(),
                        'impressions': current_df['impressions'].sum(),
                        'conversions': current_df['conversions'].sum(),
                        'conversions_value': current_df['conversions_value'].sum(),
                    }
                    current_totals['cpc'] = current_totals['cost'] / current_totals['clicks'] if current_totals['clicks'] > 0 else 0
                    current_totals['ctr'] = (current_totals['clicks'] / current_totals['impressions'] * 100) if current_totals['impressions'] > 0 else 0
                    current_totals['cost_per_conv'] = current_totals['cost'] / current_totals['conversions'] if current_totals['conversions'] > 0 else 0
                    current_totals['conv_value_cost'] = current_totals['conversions_value'] / current_totals['cost'] if current_totals['cost'] > 0 else 0
                    current_totals['aov'] = current_totals['conversions_value'] / current_totals['conversions'] if current_totals['conversions'] > 0 else 0
                    changes = {k: 0 for k in [f'{m}_change' for m in current_totals.keys()]}
                
                # Display metrics in grid
                st.subheader("Key Performance Metrics")
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.markdown(display_metric_card(
                        "Cost",
                        current_totals['cost'],
                        changes['cost_change'],
                        'currency',
                        inverse=True
                    ), unsafe_allow_html=True)
                
                with col2:
                    st.markdown(display_metric_card(
                        "CPC",
                        current_totals['cpc'],
                        changes['cpc_change'],
                        'currency',
                        inverse=True
                    ), unsafe_allow_html=True)
                
                with col3:
                    st.markdown(display_metric_card(
                        "Conv Value/Cost",
                        current_totals['conv_value_cost'],
                        changes['conv_value_cost_change'],
                        'number'
                    ), unsafe_allow_html=True)
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.markdown(display_metric_card(
                        "CTR",
                        current_totals['ctr'],
                        changes['ctr_change'],
                        'percentage'
                    ), unsafe_allow_html=True)
                
                with col2:
                    st.markdown(display_metric_card(
                        "Clicks",
                        current_totals['clicks'],
                        changes['clicks_change'],
                        'number'
                    ), unsafe_allow_html=True)
                
                with col3:
                    st.markdown(display_metric_card(
                        "Impressions",
                        current_totals['impressions'],
                        changes['impressions_change'],
                        'number'
                    ), unsafe_allow_html=True)
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.markdown(display_metric_card(
                        "Conv Value",
                        current_totals['conversions_value'],
                        changes['conversions_value_change'],
                        'currency'
                    ), unsafe_allow_html=True)
                
                with col2:
                    st.markdown(display_metric_card(
                        "Cost/Conv",
                        current_totals['cost_per_conv'],
                        changes['cost_per_conv_change'],
                        'currency',
                        inverse=True
                    ), unsafe_allow_html=True)
                
                with col3:
                    st.markdown(display_metric_card(
                        "AOV",
                        current_totals['aov'],
                        changes['aov_change'],
                        'currency'
                    ), unsafe_allow_html=True)
                
                # NEW: Add Conversions metric
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.markdown(display_metric_card(
                        "Conversions",
                        current_totals['conversions'],
                        changes['conversions_change'],
                        'number'
                    ), unsafe_allow_html=True)
                
                # Time-series charts section
                if st.session_state.daily_data is not None and not st.session_state.daily_data.empty:
                    st.markdown("---")
                    st.subheader("📈 Performance Over Time")
                    
                    daily_data = st.session_state.daily_data
                    
                    # Filter daily data by campaign if needed
                    if campaign_filter and campaign_filter.strip():
                        if exact_match:
                            daily_data = daily_data[daily_data['campaign_name'] == campaign_filter.strip()]
                        else:
                            daily_data = daily_data[daily_data['campaign_name'].str.contains(campaign_filter, case=False, na=False)]
                    
                    if not daily_data.empty:
                        # Metric selector
                        col1, col2 = st.columns([3, 1])
                        
                        with col1:
                            metric_options = {
                                'cost': 'Cost',
                                'clicks': 'Clicks',
                                'impressions': 'Impressions',
                                'conversions': 'Conversions',
                                'conversions_value': 'Conversion Value',
                                'ctr': 'CTR (%)',
                                'cpc': 'CPC',
                                'conv_value_cost': 'Conv Value/Cost',
                                'cost_per_conv': 'Cost per Conversion',
                                'aov': 'Average Order Value'
                            }
                            
                            selected_metric = st.selectbox(
                                "Select Metric to Visualize",
                                options=list(metric_options.keys()),
                                format_func=lambda x: metric_options[x],
                                key="agg_metric_selector"
                            )
                        
                        # Create and display chart
                        fig = create_time_series_chart(
                            daily_data,
                            selected_metric,
                            metric_options[selected_metric]
                        )
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("No daily data available for the selected campaign filter.")
        
        # Tab 2: Campaign Breakdown
        with tabs[2]:
            st.header("📈 Campaign Breakdown")
            
            # Date range selector
            col1, col2, col3 = st.columns([2, 2, 1])
            
            with col1:
                start_date_camp = st.date_input(
                    "Start Date",
                    value=datetime.now() - timedelta(days=30),
                    key="camp_start_date"
                )
            
            with col2:
                end_date_camp = st.date_input(
                    "End Date",
                    value=datetime.now(),
                    key="camp_end_date"
                )
            
            with col3:
                compare_option_camp = st.selectbox(
                    "Compare to",
                    ["None", "Previous Period", "Previous Week", "Previous Month", "Previous Year", "Custom"],
                    key="camp_compare"
                )
            
            if compare_option_camp == "Custom":
                col1, col2 = st.columns(2)
                with col1:
                    compare_start_camp = st.date_input("Compare Start Date", key="camp_comp_start")
                with col2:
                    compare_end_camp = st.date_input("Compare End Date", key="camp_comp_end")
            
            # Campaign filter
            st.markdown("---")
            col1, col2 = st.columns([4, 1])
            with col1:
                campaign_filter_camp = st.text_input(
                    "Filter by Campaign Name (Optional)",
                    placeholder="Type campaign name...",
                    help="Filter campaigns by name",
                    key="camp_campaign_filter"
                )
            with col2:
                st.write("")  # Spacing
                exact_match_camp = st.checkbox("Exact match", value=False, key="camp_exact_match")
            
            if st.button("📥 Load Campaign Data", key="load_camp_data", type="primary"):
                with st.spinner("Fetching campaign data..."):
                    campaign_df = fetch_campaign_performance(
                        st.session_state.client,
                        st.session_state.customer_id,
                        start_date_camp,
                        end_date_camp
                    )
                    
                    # Fetch daily data
                    daily_df_camp = fetch_daily_performance(
                        st.session_state.client,
                        st.session_state.customer_id,
                        start_date_camp,
                        end_date_camp
                    )
                    
                    # Fetch change history for annotations
                    try:
                        change_history_df = fetch_change_history(
                            st.session_state.client,
                            st.session_state.customer_id,
                            start_date_camp,
                            end_date_camp
                        )
                        st.session_state.change_history_data = change_history_df if not change_history_df.empty else None
                    except:
                        st.session_state.change_history_data = None
                    
                    if not campaign_df.empty:
                        campaign_df = process_dataframe(campaign_df)
                        
                        # Fetch comparison if needed
                        comparison_df = pd.DataFrame()
                        daily_comparison_df_camp = pd.DataFrame()
                        if compare_option_camp != "None":
                            days_diff = (end_date_camp - start_date_camp).days
                            
                            if compare_option_camp == "Previous Period":
                                comp_end = start_date_camp - timedelta(days=1)
                                comp_start = comp_end - timedelta(days=days_diff)
                            elif compare_option_camp == "Previous Week":
                                comp_end = start_date_camp - timedelta(days=1)
                                comp_start = comp_end - timedelta(days=6)
                            elif compare_option_camp == "Previous Month":
                                comp_end = start_date_camp - timedelta(days=1)
                                comp_start = comp_end - timedelta(days=29)
                            elif compare_option_camp == "Previous Year":
                                comp_start = start_date_camp - timedelta(days=365)
                                comp_end = end_date_camp - timedelta(days=365)
                            elif compare_option_camp == "Custom":
                                comp_start = compare_start_camp
                                comp_end = compare_end_camp
                            
                            comparison_df = fetch_campaign_performance(
                                st.session_state.client,
                                st.session_state.customer_id,
                                comp_start,
                                comp_end
                            )
                            
                            # Fetch daily comparison data
                            daily_comparison_df_camp = fetch_daily_performance(
                                st.session_state.client,
                                st.session_state.customer_id,
                                comp_start,
                                comp_end
                            )
                            
                            if not comparison_df.empty:
                                comparison_df = process_dataframe(comparison_df)
                        
                        # Merge with comparison data
                        if not comparison_df.empty:
                            # Calculate changes for each campaign
                            merged_df = campaign_df.merge(
                                comparison_df[['campaign_name', 'cost', 'cpc', 'ctr', 'clicks', 'impressions', 
                                             'conversions', 'conversions_value', 'cost_per_conv', 'conv_value_cost', 'aov']],
                                on='campaign_name',
                                how='left',
                                suffixes=('', '_comp')
                            )
                            
                            # Calculate percentage changes
                            for metric in ['cost', 'cpc', 'ctr', 'clicks', 'impressions', 'conversions', 
                                         'conversions_value', 'cost_per_conv', 'conv_value_cost', 'aov']:
                                merged_df[f'{metric}_change'] = merged_df.apply(
                                    lambda x: ((x[metric] - x[f'{metric}_comp']) / x[f'{metric}_comp'] * 100) 
                                    if pd.notna(x[f'{metric}_comp']) and x[f'{metric}_comp'] != 0 else 0,
                                    axis=1
                                )
                            
                            campaign_df = merged_df
                        
                        st.session_state.campaign_data = campaign_df
                        st.session_state.daily_data_camp = daily_df_camp
                        st.session_state.daily_data_camp_comparison = daily_comparison_df_camp
                        st.success("✅ Campaign data loaded!")
            
            # Display campaign table
            if st.session_state.campaign_data is not None and not st.session_state.campaign_data.empty:
                st.markdown("---")
                
                # HERO CAMPAIGN PERFORMANCE INSIGHTS
                st.subheader("🏆 Campaign Performance Insights")
                
                df_all_campaigns = st.session_state.campaign_data.copy()
                
                # Only show hero section if we have data
                if len(df_all_campaigns) >= 1:
                    # Get top campaigns (top 1 for each category)
                    top_revenue_camp = df_all_campaigns.nlargest(1, 'conversions_value').iloc[0]
                    top_spend_camp = df_all_campaigns.nlargest(1, 'cost').iloc[0]
                    best_roas_camp = df_all_campaigns.nlargest(1, 'conv_value_cost').iloc[0]
                    
                    # Display KPI cards
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.markdown(f"""
                        <div style="background: white; padding: 20px; border-radius: 8px; 
                                    box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #e5e7eb;">
                            <div style="font-size: 13px; font-weight: 500; color: #6b7280; 
                                        text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">
                                🥇 TOP REVENUE CAMPAIGN
                            </div>
                            <div style="font-size: 28px; font-weight: 700; color: #111827; margin-bottom: 8px;">
                                ${top_revenue_camp['conversions_value']:,.2f}
                            </div>
                            <div style="font-size: 14px; color: #6b7280; margin-bottom: 4px; 
                                        overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                                {top_revenue_camp['campaign_name'][:50]}{'...' if len(top_revenue_camp['campaign_name']) > 50 else ''}
                            </div>
                            <div style="font-size: 13px; color: #9ca3af;">
                                {top_revenue_camp['conversions']:.0f} conversions
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    with col2:
                        st.markdown(f"""
                        <div style="background: white; padding: 20px; border-radius: 8px; 
                                    box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #e5e7eb;">
                            <div style="font-size: 13px; font-weight: 500; color: #6b7280; 
                                        text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">
                                💰 HIGHEST SPEND CAMPAIGN
                            </div>
                            <div style="font-size: 28px; font-weight: 700; color: #111827; margin-bottom: 8px;">
                                ${top_spend_camp['cost']:,.2f}
                            </div>
                            <div style="font-size: 14px; color: #6b7280; margin-bottom: 4px; 
                                        overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                                {top_spend_camp['campaign_name'][:50]}{'...' if len(top_spend_camp['campaign_name']) > 50 else ''}
                            </div>
                            <div style="font-size: 13px; color: #9ca3af;">
                                {top_spend_camp['clicks']:.0f} clicks
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    with col3:
                        st.markdown(f"""
                        <div style="background: white; padding: 20px; border-radius: 8px; 
                                    box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #e5e7eb;">
                            <div style="font-size: 13px; font-weight: 500; color: #6b7280; 
                                        text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">
                                🎯 BEST ROAS CAMPAIGN
                            </div>
                            <div style="font-size: 28px; font-weight: 700; color: #111827; margin-bottom: 8px;">
                                {best_roas_camp['conv_value_cost']:.2f}x
                            </div>
                            <div style="font-size: 14px; color: #6b7280; margin-bottom: 4px; 
                                        overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                                {best_roas_camp['campaign_name'][:50]}{'...' if len(best_roas_camp['campaign_name']) > 50 else ''}
                            </div>
                            <div style="font-size: 13px; color: #9ca3af;">
                                ${best_roas_camp['conversions_value']:,.2f} revenue
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    # Top 5 campaigns chart
                    st.markdown("### 📊 Top 5 Campaigns Performance")
                    
                    top_5_campaigns = df_all_campaigns.nlargest(5, 'conversions_value')
                    
                    # Multi-metric selector for campaigns
                    campaign_metric_options = {
                        'cost': 'Cost',
                        'conversions': 'Conversions',
                        'conversions_value': 'Revenue',
                        'conv_value_cost': 'ROAS',
                        'clicks': 'Clicks',
                        'cpc': 'CPC'
                    }
                    
                    selected_campaign_metrics = st.multiselect(
                        "Select metrics to compare across top campaigns",
                        options=list(campaign_metric_options.keys()),
                        default=['conversions_value', 'cost'],
                        max_selections=3,
                        format_func=lambda x: campaign_metric_options[x],
                        key="hero_campaign_metrics_selector"
                    )
                    
                    if selected_campaign_metrics:
                        # Create grouped bar chart
                        fig = go.Figure()
                        
                        colors = ['#1e88e5', '#43a047', '#e53935']
                        
                        # Truncate campaign names for readability
                        campaign_names = [name[:30] + '...' if len(name) > 30 else name 
                                        for name in top_5_campaigns['campaign_name']]
                        
                        for idx, metric in enumerate(selected_campaign_metrics):
                            fig.add_trace(go.Bar(
                                name=campaign_metric_options[metric],
                                x=campaign_names,
                                y=top_5_campaigns[metric],
                                marker_color=colors[idx],
                                text=top_5_campaigns[metric].round(2),
                                textposition='auto'
                            ))
                        
                        fig.update_layout(
                            barmode='group',
                            title="Top 5 Campaigns by Revenue",
                            xaxis_title="Campaign",
                            yaxis_title="Value",
                            height=450,
                            plot_bgcolor='white',
                            paper_bgcolor='white',
                            hovermode='x unified',
                            legend=dict(
                                orientation="h",
                                yanchor="bottom",
                                y=-0.3,
                                xanchor="center",
                                x=0.5
                            )
                        )
                        
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("Select at least one metric to visualize top campaigns")
                    
                    st.markdown("---")
                
                df_display = st.session_state.campaign_data.copy()
                
                # Apply campaign filter
                if campaign_filter_camp and campaign_filter_camp.strip():
                    if exact_match_camp:
                        df_display = df_display[df_display['campaign_name'] == campaign_filter_camp.strip()]
                    else:
                        df_display = df_display[df_display['campaign_name'].str.contains(campaign_filter_camp, case=False, na=False)]
                    
                    if df_display.empty:
                        st.warning(f"No campaigns found matching '{campaign_filter_camp}'")
                    else:
                        match_type = "exactly matching" if exact_match_camp else "containing"
                        st.info(f"Showing {len(df_display)} campaign(s) {match_type}: '{campaign_filter_camp}'")
                
                if not df_display.empty:
                    # Calculate share metrics (SoC, SoR, ratio)
                    df_display = calculate_share_metrics(df_display)
                    
                    # Calculate last 3 days metrics if daily data available
                    if hasattr(st.session_state, 'daily_data_camp') and st.session_state.daily_data_camp is not None:
                        # Prepare budget data for last 3 days calculation
                        budget_df = df_display[['campaign_name', 'budget']].copy() if 'budget' in df_display.columns else None
                        
                        # Calculate last 3 days metrics
                        last_3d_metrics = calculate_last_3_days_metrics(st.session_state.daily_data_camp, budget_df)
                        
                        if not last_3d_metrics.empty:
                            # Merge with display dataframe
                            df_display = df_display.merge(last_3d_metrics, on='campaign_name', how='left')
                            
                            # Fill NaN values
                            for col in ['cost_last3', 'spend_delta_3d', 'revenue_delta_3d', 'delta_ratio_3d', 'budget_spent_3d_pct']:
                                if col in df_display.columns:
                                    df_display[col] = df_display[col].fillna(0)
                        else:
                            # Not enough data for last 3 days comparison
                            date_range_days = (st.session_state.daily_data_camp['date'].max() - st.session_state.daily_data_camp['date'].min()).days
                            if date_range_days < 6:
                                st.warning(f"⚠️ Last 3 days metrics require at least 6 days of data. Current range: {date_range_days} days. Please select a longer date range.")
                    
                    # Format the display
                    display_cols = ['campaign_name', 'budget', 'cost', 'soc', 'conversions_value', 'sor', 'soc_sor_ratio']
                    
                    # Add last 3 days columns if available
                    if 'cost_last3' in df_display.columns:
                        display_cols.extend(['cost_last3', 'budget_spent_3d_pct', 'spend_delta_3d', 'revenue_delta_3d', 'delta_ratio_3d'])
                    
                    # Add remaining metrics
                    display_cols.extend(['conv_value_cost', 'cpc', 'ctr', 'clicks', 
                                       'impressions', 'conversions', 'cost_per_conv', 'aov'])
                    
                    if 'cost_change' in df_display.columns:
                        # Add change columns
                        for metric in ['cost', 'cpc', 'conv_value_cost', 'ctr', 'clicks', 
                                      'impressions', 'conversions', 'conversions_value', 'cost_per_conv', 'aov']:
                            if f'{metric}_change' in df_display.columns:
                                display_cols.append(f'{metric}_change')
                    
                    # Keep only existing columns
                    display_cols = [col for col in display_cols if col in df_display.columns]
                    df_display_table = df_display[display_cols].copy()
                    
                    # Show delta summary if last 3 days data available
                    if 'spend_delta_3d' in df_display.columns and 'revenue_delta_3d' in df_display.columns:
                        # Show date range used for calculations
                        if hasattr(st.session_state, 'daily_data_camp') and st.session_state.daily_data_camp is not None:
                            max_date = st.session_state.daily_data_camp['date'].max()
                            last_3_start = max_date - timedelta(days=2)
                            prev_3_end = last_3_start - timedelta(days=1)
                            prev_3_start = prev_3_end - timedelta(days=2)
                            
                            st.info(f"📅 **Last 3 Days Analysis:** {last_3_start.strftime('%b %d')} - {max_date.strftime('%b %d, %Y')} vs Previous 3 Days: {prev_3_start.strftime('%b %d')} - {prev_3_end.strftime('%b %d, %Y')}")
                        
                        st.markdown("#### 📊 Last 3 Days Performance Overview")
                        
                        # Calculate aggregates
                        total_spend_delta = df_display['spend_delta_3d'].mean()
                        total_revenue_delta = df_display['revenue_delta_3d'].mean()
                        
                        # Calculate delta ratio correctly from portfolio-level deltas
                        if abs(total_spend_delta) > 0.1:
                            avg_delta_ratio = total_revenue_delta / total_spend_delta
                        else:
                            avg_delta_ratio = 0
                        
                        # Determine if performance is good based on delta directions
                        # Best case: spend down, revenue up (ratio is negative but performance is excellent)
                        # Good case: both up, revenue faster (ratio > 1)
                        # Warning: spend up faster than revenue (ratio < 1)
                        # Bad: spend up, revenue down (ratio is negative and bad)
                        
                        if total_spend_delta < 0 and total_revenue_delta > 0:
                            # Spend decreased, revenue increased - EXCELLENT
                            performance_good = True
                            ratio_interpretation = "✅ Optimal efficiency (lower spend, higher revenue)"
                        elif total_spend_delta > 0 and total_revenue_delta < 0:
                            # Spend increased, revenue decreased - TERRIBLE
                            performance_good = False
                            ratio_interpretation = "🚨 Critical issue (higher spend, lower revenue)"
                        elif avg_delta_ratio >= 1:
                            # Both same sign, revenue growing faster
                            performance_good = True
                            ratio_interpretation = "✅ Revenue growing faster"
                        else:
                            # Both same sign, spend growing faster
                            performance_good = False
                            ratio_interpretation = "⚠️ Monitor closely"
                        
                        col1, col2, col3 = st.columns(3)
                        
                        with col1:
                            spend_arrow = "▲" if total_spend_delta > 0 else "▼"
                            spend_color = "#dc2626" if total_spend_delta > 0 else "#059669"
                            st.markdown(f"""
                            <div style="background: white; padding: 16px; border-radius: 8px; 
                                        box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #e5e7eb;">
                                <div style="font-size: 12px; color: #6b7280; margin-bottom: 4px;">
                                    AVG SPEND CHANGE (3D)
                                </div>
                                <div style="font-size: 24px; font-weight: 700; color: {spend_color};">
                                    {spend_arrow} {abs(total_spend_delta):.1f}%
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                        
                        with col2:
                            rev_arrow = "▲" if total_revenue_delta > 0 else "▼"
                            rev_color = "#059669" if total_revenue_delta > 0 else "#dc2626"
                            st.markdown(f"""
                            <div style="background: white; padding: 16px; border-radius: 8px; 
                                        box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #e5e7eb;">
                                <div style="font-size: 12px; color: #6b7280; margin-bottom: 4px;">
                                    AVG REVENUE CHANGE (3D)
                                </div>
                                <div style="font-size: 24px; font-weight: 700; color: {rev_color};">
                                    {rev_arrow} {abs(total_revenue_delta):.1f}%
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                        
                        with col3:
                            ratio_color = "#059669" if performance_good else "#dc2626"
                            st.markdown(f"""
                            <div style="background: white; padding: 16px; border-radius: 8px; 
                                        box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #e5e7eb;">
                                <div style="font-size: 12px; color: #6b7280; margin-bottom: 4px;">
                                    AVG DELTA RATIO (3D)
                                </div>
                                <div style="font-size: 24px; font-weight: 700; color: {ratio_color};">
                                    {abs(avg_delta_ratio):.2f}x
                                </div>
                                <div style="font-size: 14px; font-weight: 600; color: {ratio_color}; margin-top: 4px;">
                                    {ratio_interpretation}
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                        
                        st.markdown("---")
                    
                    # Rename columns for display
                    df_display_table.columns = df_display_table.columns.str.replace('_', ' ').str.title()
                    df_display_table = df_display_table.rename(columns={
                        'Campaign Name': 'Campaign',
                        'Budget': 'Daily Budget',
                        'Conv Value Cost': 'ROAS',
                        'Conversions Value': 'Revenue',
                        'Cost Per Conv': 'Cost/Conv',
                        'Soc': 'SoC %',
                        'Sor': 'SoR %',
                        'Soc Sor Ratio': 'SoC/SoR',
                        'Cost Last3': 'Last 3d Spend',
                        'Budget Spent 3D Pct': 'Budget % (3d)',
                        'Spend Delta 3D': 'Δ Spend %',
                        'Revenue Delta 3D': 'Δ Revenue %',
                        'Delta Ratio 3D': 'Δ Ratio'
                    })
                    
                    # Apply styling with conditional formatting
                    def color_soc_sor_ratio(val):
                        """Green if < 1, Red if > 1, Grey if = 1"""
                        try:
                            if val < 1.0:
                                return 'background-color: #d1fae5; color: #065f46'  # Green
                            elif val > 1.0:
                                return 'background-color: #fee2e2; color: #991b1b'  # Red
                            else:
                                return 'background-color: #f3f4f6; color: #6b7280'  # Grey
                        except:
                            return ''
                    
                    def color_delta_ratio(val):
                        """Green if positive, Red if negative"""
                        try:
                            if val > 0.1:
                                return 'background-color: #d1fae5; color: #065f46'  # Green
                            elif val < -0.1:
                                return 'background-color: #fee2e2; color: #991b1b'  # Red
                            else:
                                return 'background-color: #f3f4f6; color: #6b7280'  # Grey
                        except:
                            return ''
                    
                    # Apply conditional formatting
                    styled_df = df_display_table.style.applymap(
                        color_soc_sor_ratio,
                        subset=['SoC/SoR'] if 'SoC/SoR' in df_display_table.columns else []
                    ).applymap(
                        color_delta_ratio,
                        subset=['Δ Ratio'] if 'Δ Ratio' in df_display_table.columns else []
                    ).set_properties(**{
                        'font-weight': 'bold',
                        'background-color': '#f9fafb',
                        'border': '1px solid #e5e7eb'
                    }, subset=df_display_table.columns[:1]  # Bold first column (Campaign)
                    ).set_table_styles([
                        {'selector': 'thead th', 'props': [
                            ('background-color', '#1f2937'),
                            ('color', 'white'),
                            ('font-weight', 'bold'),
                            ('font-size', '14px'),
                            ('text-align', 'center'),
                            ('padding', '12px'),
                            ('border', '1px solid #374151')
                        ]},
                        {'selector': 'tbody td', 'props': [
                            ('padding', '10px'),
                            ('border', '1px solid #e5e7eb'),
                            ('text-align', 'right')
                        ]},
                        {'selector': 'tbody tr:hover', 'props': [
                            ('background-color', '#f3f4f6')
                        ]}
                    ]).format({
                        col: '{:.2f}' for col in df_display_table.select_dtypes(include=['float64']).columns
                    })
                    
                    st.dataframe(
                        styled_df,
                        use_container_width=True,
                        height=600
                    )
                    
                    # Time-series charts
                    if hasattr(st.session_state, 'daily_data_camp') and st.session_state.daily_data_camp is not None and not st.session_state.daily_data_camp.empty:
                        st.markdown("---")
                        st.subheader("📈 Campaign Performance Over Time")
                        
                        daily_data_camp = st.session_state.daily_data_camp.copy()
                        
                        # Filter by campaign if needed
                        if campaign_filter_camp and campaign_filter_camp.strip():
                            if exact_match_camp:
                                daily_data_camp = daily_data_camp[daily_data_camp['campaign_name'] == campaign_filter_camp.strip()]
                            else:
                                daily_data_camp = daily_data_camp[daily_data_camp['campaign_name'].str.contains(campaign_filter_camp, case=False, na=False)]
                        
                        if not daily_data_camp.empty:
                            # Check if single campaign for change annotations
                            unique_campaigns = daily_data_camp['campaign_name'].unique()
                            is_single_campaign = len(unique_campaigns) == 1
                            
                            # Show info about change annotations
                            if is_single_campaign:
                                st.info(f"📍 Single campaign selected: **{unique_campaigns[0]}**. Change history markers will appear on the chart.")
                                
                                # Change threshold filters
                                col1, col2 = st.columns(2)
                                with col1:
                                    min_budget_pct = st.slider(
                                        "Min Budget Change %",
                                        0, 100, 10, 5,
                                        help="Show budget changes above this %",
                                        key="camp_min_budget"
                                    )
                                with col2:
                                    min_bid_pct = st.slider(
                                        "Min Bid Strategy Change %",
                                        0, 100, 10, 5,
                                        help="Show bid changes above this %",
                                        key="camp_min_bid"
                                    )
                            else:
                                st.info(f"💡 Viewing {len(unique_campaigns)} campaigns. Filter to one campaign to see change history markers.")
                                min_budget_pct = 0
                                min_bid_pct = 0
                            
                            # Multi-metric selector
                            metric_options = {
                                'cost': 'Cost',
                                'clicks': 'Clicks',
                                'impressions': 'Impressions',
                                'conversions': 'Conversions',
                                'conversions_value': 'Conversion Value',
                                'ctr': 'CTR (%)',
                                'cpc': 'CPC',
                                'conv_value_cost': 'Conv Value/Cost',
                                'cost_per_conv': 'Cost per Conversion',
                                'aov': 'Average Order Value'
                            }
                            
                            selected_metrics = st.multiselect(
                                "Select up to 3 metrics to visualize",
                                options=list(metric_options.keys()),
                                default=['cost', 'conversions'],
                                max_selections=3,
                                format_func=lambda x: metric_options[x],
                                key="camp_metrics"
                            )
                            
                            if selected_metrics:
                                # Get comparison data if available
                                daily_comp = st.session_state.daily_data_camp_comparison if hasattr(st.session_state, 'daily_data_camp_comparison') else None
                                if daily_comp is not None and not daily_comp.empty:
                                    # Filter comparison by same campaign filter
                                    if campaign_filter_camp and campaign_filter_camp.strip():
                                        if exact_match_camp:
                                            daily_comp = daily_comp[daily_comp['campaign_name'] == campaign_filter_camp.strip()]
                                        else:
                                            daily_comp = daily_comp[daily_comp['campaign_name'].str.contains(campaign_filter_camp, case=False, na=False)]
                                    
                                    show_comp = st.checkbox("Show comparison", value=True, key="camp_show_comp")
                                else:
                                    daily_comp = None
                                    show_comp = False
                                
                                # Create chart
                                fig = create_multi_metric_chart(
                                    daily_data_camp,
                                    daily_comp if show_comp else None,
                                    selected_metrics,
                                    metric_options,
                                    show_comp
                                )
                                
                                # Add change annotations if single campaign
                                if is_single_campaign and st.session_state.change_history_data is not None:
                                    try:
                                        fig = add_change_annotations(
                                            fig,
                                            st.session_state.change_history_data,
                                            unique_campaigns[0],
                                            (start_date_camp, end_date_camp),
                                            min_budget_pct,
                                            min_bid_pct
                                        )
                                    except:
                                        pass  # Chart still shows without annotations
                                
                                st.plotly_chart(fig, use_container_width=True)
                                
                                # Show change table if single campaign
                                if is_single_campaign and st.session_state.change_history_data is not None:
                                    try:
                                        changes = st.session_state.change_history_data[
                                            st.session_state.change_history_data['campaign_name'] == unique_campaigns[0]
                                        ]
                                        if not changes.empty:
                                            with st.expander(f"📋 View {len(changes)} change(s) for this campaign"):
                                                st.dataframe(changes[['date', 'time', 'change_type', 'change_details']], use_container_width=True)
                                    except:
                                        pass
                            else:
                                st.warning("Please select at least one metric to visualize")
        
        # Tab 3: Product Breakdown
        with tabs[3]:
            st.header("🛍️ Product Breakdown")
            
            # Date range selector
            col1, col2, col3 = st.columns([2, 2, 1])
            
            with col1:
                start_date_prod = st.date_input(
                    "Start Date",
                    value=datetime.now() - timedelta(days=30),
                    key="prod_start_date"
                )
            
            with col2:
                end_date_prod = st.date_input(
                    "End Date",
                    value=datetime.now(),
                    key="prod_end_date"
                )
            
            with col3:
                compare_option_prod = st.selectbox(
                    "Compare to",
                    ["None", "Previous Period", "Previous Week", "Previous Month", "Previous Year", "Custom"],
                    key="prod_compare"
                )
            
            if compare_option_prod == "Custom":
                col1, col2 = st.columns(2)
                with col1:
                    compare_start_prod = st.date_input("Compare Start Date", key="prod_comp_start")
                with col2:
                    compare_end_prod = st.date_input("Compare End Date", key="prod_comp_end")
            
            # Filters
            st.markdown("---")
            
            col1, col2 = st.columns(2)
            with col1:
                campaign_filter_prod_load = st.text_input(
                    "Filter by Campaign (Optional - applies before loading)",
                    placeholder="Type campaign name...",
                    help="Filter products by campaign before aggregation",
                    key="prod_campaign_filter_load"
                )
            with col2:
                st.write("")  # Spacing
                exact_match_prod_load = st.checkbox("Exact match", value=False, key="prod_exact_match_load")
            
            if st.button("📥 Load Product Data", key="load_prod_data", type="primary"):
                with st.spinner("Fetching product data..."):
                    product_df = fetch_product_performance(
                        st.session_state.client,
                        st.session_state.customer_id,
                        start_date_prod,
                        end_date_prod
                    )
                    
                    if not product_df.empty:
                        product_df = process_dataframe(product_df)
                        
                        # Filter by campaign BEFORE aggregation if specified
                        if campaign_filter_prod_load and campaign_filter_prod_load.strip():
                            if exact_match_prod_load:
                                product_df = product_df[product_df['campaign_name'] == campaign_filter_prod_load.strip()]
                            else:
                                product_df = product_df[product_df['campaign_name'].str.contains(campaign_filter_prod_load, case=False, na=False)]
                            
                            if product_df.empty:
                                st.warning(f"No products found for campaign matching '{campaign_filter_prod_load}'")
                                st.stop()
                            else:
                                match_type = "exactly matching" if exact_match_prod_load else "containing"
                                st.info(f"Loaded products from campaigns {match_type}: '{campaign_filter_prod_load}'")
                        
                        # Aggregate by product (sum across campaigns)
                        agg_product_df = product_df.groupby('product_title').agg({
                            'cost': 'sum',
                            'clicks': 'sum',
                            'impressions': 'sum',
                            'conversions': 'sum',
                            'conversions_value': 'sum'
                        }).reset_index()
                        
                        # Recalculate derived metrics (cost already converted, don't divide again!)
                        agg_product_df = recalculate_metrics(agg_product_df)
                        
                        # Sort by cost
                        agg_product_df = agg_product_df.sort_values('cost', ascending=False)
                        
                        st.session_state.product_data = agg_product_df
                        st.success("✅ Product data loaded!")
            
            # Display product table with filters
            if st.session_state.product_data is not None and not st.session_state.product_data.empty:
                st.markdown("---")
                
                # PRODUCT OVERVIEW KPIs
                st.subheader("🏆 Product Performance Insights")
                
                df_products = st.session_state.product_data.copy()
                
                # Get top products
                top_revenue_product = df_products.nlargest(1, 'conversions_value').iloc[0]
                top_spend_product = df_products.nlargest(1, 'cost').iloc[0]
                best_roas_product = df_products.nlargest(1, 'conv_value_cost').iloc[0]
                
                # Display KPI cards
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.markdown(f"""
                    <div style="background: white; padding: 20px; border-radius: 8px; 
                                box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #e5e7eb;">
                        <div style="font-size: 13px; font-weight: 500; color: #6b7280; 
                                    text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">
                            🥇 TOP REVENUE PRODUCT
                        </div>
                        <div style="font-size: 28px; font-weight: 700; color: #111827; margin-bottom: 8px;">
                            ${top_revenue_product['conversions_value']:,.2f}
                        </div>
                        <div style="font-size: 14px; color: #6b7280; margin-bottom: 4px; 
                                    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                            {top_revenue_product['product_title'][:50]}{'...' if len(top_revenue_product['product_title']) > 50 else ''}
                        </div>
                        <div style="font-size: 13px; color: #9ca3af;">
                            {top_revenue_product['conversions']:.0f} conversions
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col2:
                    st.markdown(f"""
                    <div style="background: white; padding: 20px; border-radius: 8px; 
                                box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #e5e7eb;">
                        <div style="font-size: 13px; font-weight: 500; color: #6b7280; 
                                    text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">
                            💰 HIGHEST SPEND PRODUCT
                        </div>
                        <div style="font-size: 28px; font-weight: 700; color: #111827; margin-bottom: 8px;">
                            ${top_spend_product['cost']:,.2f}
                        </div>
                        <div style="font-size: 14px; color: #6b7280; margin-bottom: 4px; 
                                    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                            {top_spend_product['product_title'][:50]}{'...' if len(top_spend_product['product_title']) > 50 else ''}
                        </div>
                        <div style="font-size: 13px; color: #9ca3af;">
                            {top_spend_product['clicks']:.0f} clicks
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col3:
                    st.markdown(f"""
                    <div style="background: white; padding: 20px; border-radius: 8px; 
                                box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid #e5e7eb;">
                        <div style="font-size: 13px; font-weight: 500; color: #6b7280; 
                                    text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px;">
                            🎯 BEST ROAS PRODUCT
                        </div>
                        <div style="font-size: 28px; font-weight: 700; color: #111827; margin-bottom: 8px;">
                            {best_roas_product['conv_value_cost']:.2f}x
                        </div>
                        <div style="font-size: 14px; color: #6b7280; margin-bottom: 4px; 
                                    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                            {best_roas_product['product_title'][:50]}{'...' if len(best_roas_product['product_title']) > 50 else ''}
                        </div>
                        <div style="font-size: 13px; color: #9ca3af;">
                            ${best_roas_product['conversions_value']:,.2f} revenue
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                
                # Chart for top products
                st.markdown("### 📊 Top 5 Products Performance")
                
                top_5_products = df_products.nlargest(5, 'conversions_value')
                
                # Multi-metric selector for products
                product_metric_options = {
                    'cost': 'Cost',
                    'conversions': 'Conversions',
                    'conversions_value': 'Revenue',
                    'conv_value_cost': 'ROAS',
                    'clicks': 'Clicks',
                    'cpc': 'CPC'
                }
                
                selected_product_metrics = st.multiselect(
                    "Select metrics to compare across top products",
                    options=list(product_metric_options.keys()),
                    default=['conversions_value', 'cost'],
                    max_selections=3,
                    format_func=lambda x: product_metric_options[x],
                    key="product_metrics_selector"
                )
                
                if selected_product_metrics:
                    # Create grouped bar chart
                    fig = go.Figure()
                    
                    colors = ['#1e88e5', '#43a047', '#e53935']
                    
                    # Truncate product names for readability
                    product_names = [name[:30] + '...' if len(name) > 30 else name 
                                    for name in top_5_products['product_title']]
                    
                    for idx, metric in enumerate(selected_product_metrics):
                        fig.add_trace(go.Bar(
                            name=product_metric_options[metric],
                            x=product_names,
                            y=top_5_products[metric],
                            marker_color=colors[idx],
                            text=top_5_products[metric].round(2),
                            textposition='auto'
                        ))
                    
                    fig.update_layout(
                        barmode='group',
                        title="Top 5 Products by Revenue",
                        xaxis_title="Product",
                        yaxis_title="Value",
                        height=450,
                        plot_bgcolor='white',
                        paper_bgcolor='white',
                        hovermode='x unified',
                        legend=dict(
                            orientation="h",
                            yanchor="bottom",
                            y=-0.3,
                            xanchor="center",
                            x=0.5
                        )
                    )
                    
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Select at least one metric to visualize top products")
                
                st.markdown("---")
                
                # Filters for display
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    product_title_filter = st.text_input("Filter by Product Title", key="prod_title_filter")
                
                with col2:
                    min_spend = st.number_input("Min Spend ($)", min_value=0.0, value=0.0, key="min_spend")
                
                with col3:
                    min_aov = st.number_input("Min AOV ($)", min_value=0.0, value=0.0, key="min_aov")
                
                # Apply filters
                df_filtered = st.session_state.product_data.copy()
                
                if product_title_filter:
                    df_filtered = df_filtered[df_filtered['product_title'].str.contains(product_title_filter, case=False, na=False)]
                
                if min_spend > 0:
                    df_filtered = df_filtered[df_filtered['cost'] >= min_spend]
                
                if min_aov > 0:
                    df_filtered = df_filtered[df_filtered['aov'] >= min_aov]
                
                # Show top 50 by default with option to expand
                show_all = st.checkbox("Show all products", value=False, key="show_all_products")
                
                if not show_all:
                    df_display = df_filtered.head(50)
                    st.info(f"Showing top 50 of {len(df_filtered)} products by spend. Check 'Show all products' to see more.")
                else:
                    df_display = df_filtered
                
                # Calculate share metrics (SoC, SoR, ratio) for filtered products
                df_display = calculate_share_metrics(df_display)
                
                # Format display
                display_cols = ['product_title', 'cost', 'soc', 'conversions_value', 'sor', 'soc_sor_ratio',
                               'conv_value_cost', 'cpc', 'ctr', 'clicks', 
                               'impressions', 'conversions', 'cost_per_conv', 'aov']
                
                df_display = df_display[display_cols]
                
                # Rename columns
                df_display.columns = df_display.columns.str.replace('_', ' ').str.title()
                df_display = df_display.rename(columns={
                    'Conv Value Cost': 'ROAS',
                    'Conversions Value': 'Revenue',
                    'Cost Per Conv': 'Cost/Conv',
                    'Soc': 'SoC %',
                    'Sor': 'SoR %',
                    'Soc Sor Ratio': 'SoC/SoR'
                })
                
                # Apply styling with conditional formatting
                def color_soc_sor_ratio(val):
                    """Green if < 1, Red if > 1, Grey if = 1"""
                    try:
                        if val < 1.0:
                            return 'background-color: #d1fae5; color: #065f46'  # Green
                        elif val > 1.0:
                            return 'background-color: #fee2e2; color: #991b1b'  # Red
                        else:
                            return 'background-color: #f3f4f6; color: #6b7280'  # Grey
                    except:
                        return ''
                
                # Apply conditional formatting
                styled_df_prod = df_display.style.applymap(
                    color_soc_sor_ratio,
                    subset=['SoC/SoR'] if 'SoC/SoR' in df_display.columns else []
                ).set_properties(**{
                    'font-weight': 'bold',
                    'background-color': '#f9fafb',
                    'border': '1px solid #e5e7eb'
                }, subset=df_display.columns[:1]  # Bold first column (Product)
                ).set_table_styles([
                    {'selector': 'thead th', 'props': [
                        ('background-color', '#1f2937'),
                        ('color', 'white'),
                        ('font-weight', 'bold'),
                        ('font-size', '14px'),
                        ('text-align', 'center'),
                        ('padding', '12px'),
                        ('border', '1px solid #374151')
                    ]},
                    {'selector': 'tbody td', 'props': [
                        ('padding', '10px'),
                        ('border', '1px solid #e5e7eb'),
                        ('text-align', 'right')
                    ]},
                    {'selector': 'tbody tr:hover', 'props': [
                        ('background-color', '#f3f4f6')
                    ]}
                ]).format({
                    col: '{:.2f}' for col in df_display.select_dtypes(include=['float64']).columns
                })
                
                st.dataframe(
                    styled_df_prod,
                    use_container_width=True,
                    height=600
                )
                
                # Download button
                csv = df_filtered.to_csv(index=False)
                st.download_button(
                    label="📥 Download Product Data CSV",
                    data=csv,
                    file_name=f"product_performance_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv"
                )
        
        # Tab 4: Change History
        with tabs[4]:
            st.header("📜 Change History")
            
            st.markdown("""
            Track budget and bid strategy changes at the campaign level. Monitor when changes were made
            to help correlate performance shifts with account modifications.
            """)
            
            # Date range selector
            col1, col2 = st.columns(2)
            
            with col1:
                start_date_history = st.date_input(
                    "Start Date",
                    value=datetime.now() - timedelta(days=7),
                    key="history_start_date"
                )
            
            with col2:
                end_date_history = st.date_input(
                    "End Date",
                    value=datetime.now(),
                    key="history_end_date"
                )
            
            # Campaign filter and change type filter
            st.markdown("---")
            col1, col2, col3 = st.columns([3, 2, 1])
            
            with col1:
                campaign_filter_history = st.text_input(
                    "Filter by Campaign Name (Optional)",
                    placeholder="Type campaign name...",
                    help="Filter changes by campaign name",
                    key="history_campaign_filter"
                )
            
            with col2:
                change_type_filter = st.selectbox(
                    "Change Type",
                    ["All Changes", "Budget Changes Only", "Bid Strategy Changes Only"],
                    key="history_change_type"
                )
            
            with col3:
                st.write("")  # Spacing
                exact_match_history = st.checkbox("Exact match", value=False, key="history_exact_match")
            
            if st.button("📥 Load Change History", key="load_history_data", type="primary"):
                with st.spinner("Fetching change history..."):
                    history_df = fetch_change_history(
                        st.session_state.client,
                        st.session_state.customer_id,
                        start_date_history,
                        end_date_history
                    )
                    
                    if not history_df.empty:
                        st.session_state.change_history_data = history_df
                        st.success(f"✅ Found {len(history_df)} change(s)!")
                    else:
                        st.session_state.change_history_data = None
                        st.info("No budget or bid strategy changes found in the selected date range.")
            
            # Display change history
            if st.session_state.change_history_data is not None and not st.session_state.change_history_data.empty:
                st.markdown("---")
                
                df_history = st.session_state.change_history_data.copy()
                
                # Apply campaign filter
                if campaign_filter_history and campaign_filter_history.strip():
                    if exact_match_history:
                        df_history = df_history[df_history['campaign_name'] == campaign_filter_history.strip()]
                    else:
                        df_history = df_history[df_history['campaign_name'].str.contains(campaign_filter_history, case=False, na=False)]
                    
                    if df_history.empty:
                        st.warning(f"No changes found for campaigns matching '{campaign_filter_history}'")
                    else:
                        match_type = "exactly matching" if exact_match_history else "containing"
                        st.info(f"Showing changes for campaigns {match_type}: '{campaign_filter_history}'")
                
                # Apply change type filter
                if change_type_filter == "Budget Changes Only":
                    df_history = df_history[df_history['change_type'] == 'Budget Change']
                elif change_type_filter == "Bid Strategy Changes Only":
                    df_history = df_history[df_history['change_type'] == 'Bid Strategy Change']
                
                if not df_history.empty:
                    # Summary statistics
                    st.subheader("📊 Change Summary")
                    
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        total_changes = len(df_history)
                        st.metric("Total Changes", total_changes)
                    
                    with col2:
                        budget_changes = len(df_history[df_history['change_type'] == 'Budget Change'])
                        st.metric("Budget Changes", budget_changes)
                    
                    with col3:
                        bid_changes = len(df_history[df_history['change_type'] == 'Bid Strategy Change'])
                        st.metric("Bid Strategy Changes", bid_changes)
                    
                    # Changes by operation type
                    st.markdown("---")
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        created = len(df_history[df_history['operation'] == 'Created'])
                        st.metric("Created", created)
                    
                    with col2:
                        updated = len(df_history[df_history['operation'] == 'Updated'])
                        st.metric("Updated", updated)
                    
                    with col3:
                        removed = len(df_history[df_history['operation'] == 'Removed'])
                        st.metric("Removed", removed)
                    
                    # Detailed changes table
                    st.markdown("---")
                    st.subheader("📋 Detailed Changes")
                    
                    # Format display - show change details instead of operation
                    display_cols = ['date', 'time', 'campaign_name', 'change_type', 'change_details']
                    df_display = df_history[display_cols].copy()
                    
                    # Rename columns
                    df_display.columns = ['Date', 'Time', 'Campaign', 'Change Type', 'Details']
                    
                    # Sort by date descending (most recent first)
                    df_display = df_display.sort_values('Date', ascending=False)
                    
                    st.dataframe(
                        df_display,
                        use_container_width=True,
                        height=600
                    )
                    
                    # Download button
                    csv = df_history.to_csv(index=False)
                    st.download_button(
                        label="📥 Download Change History CSV",
                        data=csv,
                        file_name=f"change_history_{datetime.now().strftime('%Y%m%d')}.csv",
                        mime="text/csv"
                    )
                    
                    # Additional info section
                    with st.expander("ℹ️ About Change History"):
                        st.markdown("""
                        ### How Change History Works
                        
                        This tab tracks **campaign-level changes** for:
                        - **Budget Changes**: Any modifications to campaign budgets
                        - **Bid Strategy Changes**: Changes to bidding strategies (Manual CPC, Target CPA, Maximize Conversions, etc.)
                        
                        ### Change Operations
                        - **Created**: New campaign or budget created
                        - **Updated**: Existing campaign or budget modified
                        - **Removed**: Campaign or budget deleted
                        
                        ### Tips
                        - Default shows last 7 days of changes
                        - Use campaign filter to focus on specific campaigns
                        - Filter by change type to see only budget or bid strategy changes
                        - Export to CSV for further analysis or record-keeping
                        
                        ### Limitations
                        - Only shows campaign-level changes (not ad group or keyword changes)
                        - Change history retained for up to 2 years
                        - Very recent changes (< 1 hour) may not appear immediately
                        """)
                else:
                    st.info("No changes match the selected filters.")

if __name__ == "__main__":
    main()

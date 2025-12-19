import streamlit as st
import pandas as pd
import sqlite3
import time
from datetime import datetime, timedelta
import altair as alt
import json

st.set_page_config(
    page_title="Smoke Detector Monitor",
    layout="wide",
    initial_sidebar_state="expanded"
)

DB_PATH = "smoke_detector.db"

@st.cache_data(ttl=1)  # Cache for 1 second
def get_active_channels():
    """Get list of active channels"""
    try:
        conn = sqlite3.connect(DB_PATH)
        query = '''
            SELECT DISTINCT channel 
            FROM readings 
            WHERE datetime(timestamp) > datetime('now', '-24 hours')
            ORDER BY channel
        '''
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df['channel'].tolist() if not df.empty else []
    except Exception as e:
        st.error(f"Database error: {e}")
        return []

@st.cache_data(ttl=1)  # Cache for 1 second
def get_recent_data(channel, hours=10):
    """Get recent readings from database for a specific channel"""
    try:
        conn = sqlite3.connect(DB_PATH)
        query = '''
            SELECT timestamp, channel, R, G, IR 
            FROM readings 
            WHERE channel = ? 
            AND datetime(timestamp) > datetime('now', '-{} hours')
            ORDER BY timestamp DESC
            LIMIT 10000
        '''.format(hours)
        df = pd.read_sql_query(query, conn, params=(channel,))
        conn.close()
        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df
    except Exception as e:
        st.error(f"Database error: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=30)  # Cache for 30 seconds
def get_current_stats(channel):
    """Get current statistics for a specific channel"""
    try:
        conn = sqlite3.connect(DB_PATH)
        query = '''
            SELECT * FROM statistics 
            WHERE channel = ?
            ORDER BY timestamp DESC 
            LIMIT 1
        '''
        df = pd.read_sql_query(query, conn, params=(channel,))
        conn.close()
        return df
    except:
        return pd.DataFrame()

@st.cache_data(ttl=5)  # Cache for 5 seconds
def get_recent_alerts(channel=None, limit=20):
    """Get recent alerts, optionally filtered by channel"""
    try:
        conn = sqlite3.connect(DB_PATH)
        if channel is not None:
            query = '''
                SELECT * FROM alerts 
                WHERE channel = ?
                ORDER BY timestamp DESC 
                LIMIT ?
            '''
            df = pd.read_sql_query(query, conn, params=(channel, limit))
        else:
            query = '''
                SELECT * FROM alerts 
                ORDER BY timestamp DESC 
                LIMIT ?
            '''
            df = pd.read_sql_query(query, conn, params=(limit,))
        conn.close()
        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df
    except:
        return pd.DataFrame()

def get_setting(key):
    """Get setting from database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    except:
        return None

def update_setting(key, value):
    """Update setting in database"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Failed to update setting: {e}")
        return False

# Main interface
st.title("🚨 Smoke Detector Monitoring Dashboard")

# Sidebar controls
st.sidebar.title("Control Panel")

# Monitoring control
monitoring_active = get_setting('monitoring_active') == 'true'
st.sidebar.metric("Status", "🟢 Active" if monitoring_active else "🔴 Inactive")

col1, col2 = st.sidebar.columns(2)
with col1:
    if st.button("Start", disabled=monitoring_active):
        if update_setting('monitoring_active', 'true'):
            st.success("Monitoring started!")
            st.rerun()

with col2:
    if st.button("Stop", disabled=not monitoring_active):
        if update_setting('monitoring_active', 'false'):
            st.success("Monitoring stopped!")
            st.rerun()

# Settings
st.sidebar.subheader("Settings")

# Email settings
email_enabled = st.sidebar.checkbox(
    "Enable Email Notifications",
    value=get_setting('email_enabled') == 'true'
)
if email_enabled != (get_setting('email_enabled') == 'true'):
    update_setting('email_enabled', 'true' if email_enabled else 'false')

if email_enabled:
    email_recipients = st.sidebar.text_area(
        "Email Recipients (comma-separated)",
        value=get_setting('email_recipients') or '',
        help="Enter email addresses separated by commas"
    )
    if email_recipients != get_setting('email_recipients'):
        update_setting('email_recipients', email_recipients)

# Auto-shutdown settings
auto_shutdown = st.sidebar.checkbox(
    "Enable Auto Power Shutdown",
    value=get_setting('auto_shutdown_enabled') == 'true'
)
if auto_shutdown != (get_setting('auto_shutdown_enabled') == 'true'):
    update_setting('auto_shutdown_enabled', 'true' if auto_shutdown else 'false')

if auto_shutdown:
    st.sidebar.warning("⚠️ Auto-shutdown ENABLED!")

# Time range selector
st.sidebar.subheader("Display Settings")
hours_to_display = st.sidebar.slider("Hours of data to display", 1, 24, 10)

# Get active channels
active_channels = get_active_channels()

if not active_channels:
    st.warning("No active channels detected. Make sure the monitoring script is running and sensors are connected.")
else:
    # Display overview of all channels
    st.subheader(f"Active Channels: {len(active_channels)}")
    
    # Create columns for channel overview
    overview_cols = st.columns(len(active_channels))
    for idx, channel in enumerate(active_channels):
        with overview_cols[idx]:
            df = get_recent_data(channel, hours=1)
            if not df.empty:
                latest = df.iloc[0]
                st.metric(
                    f"Channel {channel}",
                    f"R:{latest.get('R', 'N/A')} G:{latest.get('G', 'N/A')} IR:{latest.get('IR', 'N/A')}",
                    delta=None
                )
            else:
                st.metric(f"Channel {channel}", "No data")
    
    st.divider()
    
    # Display each channel in detail
    for channel in active_channels:
        st.header(f"Channel {channel}")
        
        df = get_recent_data(channel, hours=hours_to_display)
        stats_df = get_current_stats(channel)
        alerts_df = get_recent_alerts(channel=channel, limit=10)
        
        if not df.empty:
            # Current readings
            col1, col2, col3, col4 = st.columns(4)
            latest = df.iloc[0]
            
            with col1:
                st.metric("Red", latest.get('R', 'N/A'))
            with col2:
                st.metric("Green", latest.get('G', 'N/A'))
            with col3:
                st.metric("IR", latest.get('IR', 'N/A'))
            with col4:
                st.metric("Last Update", latest['timestamp'].strftime("%H:%M:%S"))
            
            # Statistics
            if not stats_df.empty:
                st.subheader(f"Channel {channel} Statistics")
                stats = stats_df.iloc[0]
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.write("**Red Channel**")
                    if pd.notna(stats.get('R_mean')):
                        st.write(f"Mean: {stats['R_mean']:.2f}")
                        st.write(f"Std Dev: {stats['R_std']:.2f}")
                
                with col2:
                    st.write("**Green Channel**")
                    if pd.notna(stats.get('G_mean')):
                        st.write(f"Mean: {stats['G_mean']:.2f}")
                        st.write(f"Std Dev: {stats['G_std']:.2f}")
                
                with col3:
                    st.write("**IR Channel**")
                    if pd.notna(stats.get('IR_mean')):
                        st.write(f"Mean: {stats['IR_mean']:.2f}")
                        st.write(f"Std Dev: {stats['IR_std']:.2f}")
            
            # Time series plot for this channel
            st.subheader(f"Channel {channel} - Readings Over Time")
            
            # Prepare data for plotting
            df_plot = df.melt(id_vars=['timestamp'], 
                             value_vars=['R', 'G', 'IR'],
                             var_name='Sensor', 
                             value_name='Value')
            
            chart = alt.Chart(df_plot).mark_line().encode(
                x=alt.X('timestamp:T', title='Time'),
                y=alt.Y('Value:Q', title='Reading Value'),
                color=alt.Color('Sensor:N', 
                               scale=alt.Scale(domain=['R', 'G', 'IR'], 
                                             range=['red', 'green', 'purple']))
            ).properties(
                height=300,
                title=f"Channel {channel} Smoke Detector Readings"
            ).interactive()
            
            st.altair_chart(chart, use_container_width=True)
            
            # Channel-specific alerts
            if not alerts_df.empty:
                st.subheader(f"Channel {channel} - Recent Alerts")
                
                for _, alert in alerts_df.iterrows():
                    alert_type = alert['alert_type']
                    timestamp = alert['timestamp'].strftime("%Y-%m-%d %H:%M:%S")
                    
                    if alert_type == 'CRITICAL':
                        st.error(f"**{timestamp} - {alert_type}**: {alert['message']}")
                    elif alert_type == 'WARNING':
                        st.warning(f"**{timestamp} - {alert_type}**: {alert['message']}")
                    else:
                        st.info(f"**{timestamp} - {alert_type}**: {alert['message']}")
                    
                    # Show details
                    if pd.notna(alert['R_value']):
                        with st.expander(f"Details for {timestamp}"):
                            col1, col2 = st.columns(2)
                            with col1:
                                st.write("**Raw Values:**")
                                st.write(f"R: {alert['R_value']}")
                                st.write(f"G: {alert['G_value']}")
                                st.write(f"IR: {alert['IR_value']}")
                            with col2:
                                st.write("**Z-Scores:**")
                                if pd.notna(alert['R_zscore']):
                                    st.write(f"R: {alert['R_zscore']:.2f}")
                                    st.write(f"G: {alert['G_zscore']:.2f}")
                                    st.write(f"IR: {alert['IR_zscore']:.2f}")
        else:
            st.warning(f"No recent data available for Channel {channel}.")
        
        st.divider()
    
    # All alerts summary at the bottom
    all_alerts_df = get_recent_alerts(limit=20)
    if not all_alerts_df.empty:
        st.header("All Recent Alerts (All Channels)")
        
        # Group by channel for summary
        alert_summary = all_alerts_df.groupby('channel').size().reset_index(name='count')
        st.write("**Alert Count by Channel:**")
        st.dataframe(alert_summary, hide_index=True)
        
        # Show details
        with st.expander("Show all alert details"):
            for _, alert in all_alerts_df.iterrows():
                alert_type = alert['alert_type']
                channel = alert['channel']
                timestamp = alert['timestamp'].strftime("%Y-%m-%d %H:%M:%S")
                
                if alert_type == 'CRITICAL':
                    st.error(f"**Ch {channel} - {timestamp} - {alert_type}**: {alert['message']}")
                elif alert_type == 'WARNING':
                    st.warning(f"**Ch {channel} - {timestamp} - {alert_type}**: {alert['message']}")
                else:
                    st.info(f"**Ch {channel} - {timestamp} - {alert_type}**: {alert['message']}")

# Auto-refresh every 5 seconds
time.sleep(5)
st.rerun()
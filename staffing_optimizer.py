import streamlit as st
import pandas as pd
import pulp
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Dict, List, Tuple, Optional
import logging
import datetime as dt
import json
import io
import csv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Data upload functions
def parse_site_schedule_upload(upload_file) -> Dict:
    """
    Parse an uploaded site schedule CSV file.
    Expected format:
    site_name,shift_type,valid_start_times,work_periods,paid_breaks,unpaid_breaks
    """
    site_schedules = {}
    
    try:
        content = upload_file.read().decode('utf-8')
        reader = csv.DictReader(io.StringIO(content))
        
        for row in reader:
            site_name = row.get('site_name', '').strip()
            shift_type = row.get('shift_type', '').strip()
            
            if not site_name or not shift_type:
                continue
                
            # Initialize site if not already present
            if site_name not in site_schedules:
                site_schedules[site_name] = {
                    'day_shift': {
                        'valid_start_times': [],
                        'work_periods': [],
                        'paid_breaks': [],
                        'unpaid_breaks': [],
                        'shift_length_hours': 10,
                        'unpaid_lunch_hours': 0.5
                    },
                    'night_shift': {
                        'valid_start_times': [],
                        'work_periods': [],
                        'paid_breaks': [],
                        'unpaid_breaks': [],
                        'shift_length_hours': 10,
                        'unpaid_lunch_hours': 0.5
                    }
                }
            
            # Parse valid start times
            valid_start_times = row.get('valid_start_times', '').strip()
            if valid_start_times:
                site_schedules[site_name][shift_type]['valid_start_times'] = [
                    time.strip() for time in valid_start_times.split(',')
                ]
            
            # Parse work periods
            work_periods = row.get('work_periods', '').strip()
            if work_periods:
                periods = []
                for period in work_periods.split(';'):
                    if '-' in period:
                        start, end = period.strip().split('-')
                        periods.append({'start': start.strip(), 'end': end.strip()})
                site_schedules[site_name][shift_type]['work_periods'] = periods
            
            # Parse paid breaks
            paid_breaks = row.get('paid_breaks', '').strip()
            if paid_breaks:
                breaks = []
                for brk in paid_breaks.split(';'):
                    if '-' in brk:
                        start, end = brk.strip().split('-')
                        breaks.append({'start': start.strip(), 'end': end.strip()})
                site_schedules[site_name][shift_type]['paid_breaks'] = breaks
            
            # Parse unpaid breaks
            unpaid_breaks = row.get('unpaid_breaks', '').strip()
            if unpaid_breaks:
                breaks = []
                for brk in unpaid_breaks.split(';'):
                    if '-' in brk:
                        start, end = brk.strip().split('-')
                        breaks.append({'start': start.strip(), 'end': end.strip()})
                site_schedules[site_name][shift_type]['unpaid_breaks'] = breaks
            
            # Parse shift_length_hours and unpaid_lunch_hours if present
            shift_length = row.get('shift_length_hours', '')
            if shift_length and shift_length.strip():
                site_schedules[site_name][shift_type]['shift_length_hours'] = float(shift_length)
                
            unpaid_lunch = row.get('unpaid_lunch_hours', '')
            if unpaid_lunch and unpaid_lunch.strip():
                site_schedules[site_name][shift_type]['unpaid_lunch_hours'] = float(unpaid_lunch)
    
    except Exception as e:
        logger.error(f"Error parsing site schedule upload: {str(e)}")
        st.error(f"Error parsing site schedule upload: {str(e)}")
    
    return site_schedules

def parse_hourly_demand_upload(upload_file) -> Dict:
    """
    Parse an uploaded hourly demand CSV file.
    Expected format:
    site_name,day,hour,volume,tph
    
    Where volume is the amount of work to be done and tph is throughput per hour
    """
    demand_profiles = {}
    
    try:
        content = upload_file.read().decode('utf-8')
        df = pd.read_csv(io.StringIO(content))
        
        # Validate required columns
        required_cols = ['site_name', 'day', 'hour', 'volume', 'tph']
        for col in required_cols:
            if col not in df.columns:
                st.error(f"Missing required column: {col}")
                return demand_profiles
        
        # Process each site
        for site_name in df['site_name'].unique():
            site_data = df[df['site_name'] == site_name]
            
            # Initialize site demand profile
            if site_name not in demand_profiles:
                demand_profiles[site_name] = {
                    'day_requirements': {day: 0 for day in ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']},
                    'night_requirements': {day: 0 for day in ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']},
                    'hourly_demand': []
                }
            
            # Process hourly demand for this site
            for _, row in site_data.iterrows():
                day = row['day']
                hour = int(row['hour'])
                volume = float(row['volume'])
                tph = float(row['tph'])
                
                # Calculate headcount required for this hour
                # If TPH is 0, default to 1 to avoid division by zero
                if tph <= 0:
                    staff_needed = volume  # Default to volume if no TPH provided
                    st.warning(f"TPH for {site_name} on {day} at hour {hour} is 0 or negative. Using volume as staff needed.")
                else:
                    staff_needed = volume / tph
                
                # Determine shift type based on hour
                shift_type = 'Day' if 5 <= hour < 15 else 'Night'
                
                # Add to hourly demand
                demand_profiles[site_name]['hourly_demand'].append({
                    'Day': day,
                    'Hour': hour,
                    'Shift_Type': shift_type,
                    'Volume': volume,
                    'TPH': tph,
                    'Demand': staff_needed
                })
                
                # Update daily requirements
                if shift_type == 'Day':
                    demand_profiles[site_name]['day_requirements'][day] += staff_needed
                else:
                    demand_profiles[site_name]['night_requirements'][day] += staff_needed
            
            # Convert hourly demand to DataFrame
            demand_profiles[site_name]['hourly_demand'] = pd.DataFrame(demand_profiles[site_name]['hourly_demand'])
    
    except Exception as e:
        logger.error(f"Error parsing hourly demand upload: {str(e)}")
        st.error(f"Error parsing hourly demand upload: {str(e)}")
    
    return demand_profiles

def parse_current_staffing_upload(upload_file) -> Dict:
    """
    Parse an uploaded current staffing CSV file.
    Expected format:
    site_name,pattern,start_time,employees
    """
    site_staffing = {}
    
    try:
        content = upload_file.read().decode('utf-8')
        df = pd.read_csv(io.StringIO(content))
        
        # Validate required columns
        required_cols = ['site_name', 'pattern', 'employees']
        for col in required_cols:
            if col not in df.columns:
                st.error(f"Missing required column: {col}")
                return site_staffing
        
        # Process each site
        for site_name in df['site_name'].unique():
            site_data = df[df['site_name'] == site_name]
            
            # Initialize site staffing
            if site_name not in site_staffing:
                site_staffing[site_name] = {}
            
            # Process staffing patterns for this site
            for _, row in site_data.iterrows():
                pattern = row['pattern']
                employees = int(row['employees'])
                
                # Check if the pattern has a start time specification
                if 'start_time' in df.columns and pd.notna(row['start_time']):
                    pattern = f"{pattern}-{row['start_time']}"
                
                site_staffing[site_name][pattern] = employees
    
    except Exception as e:
        logger.error(f"Error parsing current staffing upload: {str(e)}")
        st.error(f"Error parsing current staffing upload: {str(e)}")
    
    return site_staffing

def generate_sample_uploads():
    """Generate sample CSV files for upload examples"""
    
    # Sample site schedule
    site_schedule_csv = """site_name,shift_type,valid_start_times,work_periods,paid_breaks,unpaid_breaks,shift_length_hours,unpaid_lunch_hours
SiteA,day_shift,"0500,0600,0700,0800,0900,1000,1100,1200,1300,1400","0700-0930;0945-1200;1230-1430;1445-1730","0930-0945;1430-1445","1200-1230",10,0.5
SiteA,night_shift,"1500,1600,1700,1800,1900,2000,2100,2200,2300,0000,0100,0200,0300,0400","1500-1730;1745-2000;2030-2230;2245-0100","1730-1745;2230-2245","2000-2030",10,0.5
SiteB,day_shift,"0600,0700,0800,0900,1000,1100,1200,1300,1400","0600-0900;0915-1200;1230-1530","0900-0915;1530-1545","1200-1230",10,0.5
SiteB,night_shift,"1600,1700,1800,1900,2000,2100,2200,2300,0000,0100,0200,0300,0400,0500","1600-1900;1915-2200;2230-0130","1900-1915;2200-2230","0130-0200",10,0.5"""
    
    # Sample hourly demand
    hourly_demand_csv = """site_name,day,hour,volume,tph
SiteA,Sun,6,800,10
SiteA,Sun,7,1200,10
SiteA,Sun,8,1500,10
SiteA,Sun,9,1800,10
SiteA,Sun,10,2000,10
SiteA,Sun,11,2200,10
SiteA,Sun,12,2000,10
SiteA,Sun,13,1800,10
SiteA,Sun,14,1500,10
SiteA,Sun,15,1200,10
SiteA,Sun,16,1500,10
SiteA,Sun,17,1800,10
SiteA,Sun,18,2000,10
SiteA,Sun,19,2200,10
SiteA,Sun,20,2000,10
SiteA,Sun,21,1800,10
SiteA,Sun,22,1500,10
SiteA,Sun,23,1200,10
SiteA,Mon,6,1000,10
SiteA,Mon,7,1500,10
SiteA,Mon,8,2000,10
SiteA,Mon,9,2500,10
SiteA,Mon,10,3000,10
SiteA,Mon,11,3200,10
SiteA,Mon,12,2800,10
SiteA,Mon,13,2400,10
SiteA,Mon,14,2000,10
SiteA,Mon,15,1500,10
SiteA,Mon,16,1800,10
SiteA,Mon,17,2200,10
SiteA,Mon,18,2500,10
SiteA,Mon,19,2700,10
SiteA,Mon,20,2400,10
SiteA,Mon,21,2100,10
SiteA,Mon,22,1800,10
SiteA,Mon,23,1400,10
SiteB,Sun,6,400,10
SiteB,Sun,7,600,10
SiteB,Sun,8,800,10
SiteB,Sun,9,1000,10
SiteB,Sun,10,1200,10
SiteB,Sun,11,1300,10
SiteB,Sun,12,1100,10
SiteB,Sun,13,900,10
SiteB,Sun,14,700,10
SiteB,Sun,15,600,10
SiteB,Sun,16,700,10
SiteB,Sun,17,900,10
SiteB,Sun,18,1100,10
SiteB,Sun,19,1200,10
SiteB,Sun,20,1000,10
SiteB,Sun,21,800,10
SiteB,Sun,22,600,10
SiteB,Sun,23,400,10"""
    
    # Sample current staffing
    current_staffing_csv = """site_name,pattern,start_time,employees
SiteA,DA,0700,100
SiteA,DB,0700,80
SiteA,DC,0700,60
SiteA,DD,0700,70
SiteA,DE,0700,90
SiteA,NA,1900,70
SiteA,NB,1900,60
SiteA,NC,1900,50
SiteA,ND,1900,40
SiteA,NE,1900,30
SiteB,DA,0600,50
SiteB,DB,0600,40
SiteB,DC,0600,30
SiteB,DD,0600,35
SiteB,DE,0600,45
SiteB,NA,1800,35
SiteB,NB,1800,30
SiteB,NC,1800,25
SiteB,ND,1800,20
SiteB,NE,1800,15"""
    
    return site_schedule_csv, hourly_demand_csv, current_staffing_csv

# Global variables
met_df = pd.DataFrame()  # Initialize empty DataFrame for MET distribution

# Shift timing configuration
DEFAULT_SITE_SCHEDULE = {
    'day_shift': {
        'valid_start_times': ['0500', '0600', '0700', '0800', '0900', '1000', '1100', '1200', '1300', '1400'],
        'work_periods': [
            {'start': '0700', 'end': '0930'},
            {'start': '0945', 'end': '1200'},
            {'start': '1230', 'end': '1430'},
            {'start': '1445', 'end': '1730'}
        ],
        'paid_breaks': [
            {'start': '0930', 'end': '0945'},
            {'start': '1430', 'end': '1445'}
        ],
        'unpaid_breaks': [
            {'start': '1200', 'end': '1230'}
        ],
        'shift_length_hours': 10,
        'unpaid_lunch_hours': 0.5
    },
    'night_shift': {
        'valid_start_times': ['1500', '1600', '1700', '1800', '1900', '2000', '2100', '2200', '2300', '0000', '0100', '0200', '0300', '0400'],
        'work_periods': [
            {'start': '1500', 'end': '1730'},
            {'start': '1745', 'end': '2000'},
            {'start': '2030', 'end': '2230'},
            {'start': '2245', 'end': '0100'}
        ],
        'paid_breaks': [
            {'start': '1730', 'end': '1745'},
            {'start': '2230', 'end': '2245'}
        ],
        'unpaid_breaks': [
            {'start': '2000', 'end': '2030'}
        ],
        'shift_length_hours': 10,
        'unpaid_lunch_hours': 0.5
    }
}

# Default demand profile - percentage of daily total by hour within shift
DEFAULT_DEMAND_PROFILE = {
    'day_shift': [0.05, 0.08, 0.12, 0.15, 0.15, 0.13, 0.12, 0.10, 0.07, 0.03],  # 10 hours (0500-1500)
    'night_shift': [0.05, 0.10, 0.15, 0.15, 0.15, 0.12, 0.10, 0.08, 0.06, 0.04]  # 10 hours (1500-0100)
}

# Utility functions for time handling
def time_to_minutes(time_str):
    """Convert time string (HHMM) to minutes since midnight."""
    hours = int(time_str[:2])
    minutes = int(time_str[2:])
    return hours * 60 + minutes

def minutes_to_time(minutes):
    """Convert minutes since midnight to time string (HHMM)."""
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}{mins:02d}"

def is_valid_start_time(time_str, site_schedule, shift_type):
    """Check if a time string is a valid start time for the given shift type."""
    return time_str in site_schedule[shift_type]['valid_start_times']

def categorize_shift_pattern(pattern: str, days: List[str], pattern_data: Dict[str, int]) -> str:
    """
    Categorizes a shift pattern based on its weekend days.
    
    Args:
        pattern (str): The pattern identifier (e.g., 'DA', 'NB')
        days (List[str]): List of days in order
        pattern_data (Dict[str, int]): Dictionary mapping days to 1/0 for work/off
        
    Returns:
        str: Category identifier ('0', '1', '2', '3' for day shifts, '0', '1', '2', '3' for night shifts)
    """
    shift_type = pattern[0]  # 'D' or 'N'
    
    if shift_type == 'D':
        # For day shifts, weekends are Sat and Sun
        weekend_days = ['Sat', 'Sun']
    else:
        # For night shifts, weekends are Fri, Sat, Sun
        weekend_days = ['Fri', 'Sat', 'Sun']
    
    # Count weekend days worked
    weekend_work_days = sum(pattern_data[day] for day in weekend_days)
    
    # Return category based on number of weekend days worked
    return str(weekend_work_days)

def create_patterns_df() -> pd.DataFrame:
    """
    Creates a DataFrame containing base staffing patterns.
    Pattern A (DA/NA) will be further split into MET variations in a second phase.
    """
    # Define base patterns (1=scheduled work day, 0=off day)
    base_patterns = {
        'A': [1, 1, 1, 1, 0, 0, 0],  # Sun-Wed
        'B': [0, 0, 0, 1, 1, 1, 0],  # Thu-Sat
        'C': [0, 1, 1, 1, 1, 0, 0],  # Mon-Thu
        'D': [0, 0, 1, 1, 1, 1, 0],  # Tue-Fri
        'E': [0, 1, 1, 1, 1, 1, 0],  # Mon-Fri
        'F': [0, 1, 1, 1, 1, 1, 0],  # Mon-Fri
        'G': [1, 1, 0, 0, 1, 1, 0],  # Sun-Mon, Thu-Fri
        'H': [1, 1, 0, 1, 1, 0, 0],  # Sun-Mon, Wed-Thu
        'I': [1, 0, 1, 1, 1, 0, 0],  # Sun, Tue-Thu
        'J': [0, 1, 0, 1, 1, 0, 1],  # Mon, Wed-Thu, Sat
        'K': [0, 1, 1, 0, 1, 1, 0],  # Mon-Tue, Thu-Fri
        'L': [1, 1, 1, 0, 0, 0, 1],  # Sun-Tue, Sat
        'M': [0, 0, 1, 1, 1, 0, 1],  # Tue-Thu, Sat
        'N': [1, 0, 0, 0, 1, 1, 1],  # Sun, Thu-Sat
        'O': [1, 1, 0, 0, 0, 1, 1],  # Sun-Mon, Fri-Sat
        'P': [1, 1, 1, 1, 0, 0, 0],  # Sun-Wed
        'Q': [0, 1, 1, 1, 1, 0, 0],  # Mon-Thu
        'R': [0, 1, 1, 0, 1, 1, 0],  # Mon-Tue, Thu-Fri
        'S': [1, 0, 0, 1, 1, 1, 0],  # Sun, Wed-Fri
        'T': [1, 1, 1, 1, 0, 0, 0],  # Sun-Wed
        'U': [1, 1, 0, 0, 1, 1, 0],  # Sun-Mon, Thu-Fri
        'V': [1, 0, 1, 1, 0, 0, 1],  # Sun, Tue-Wed, Sat
        'W': [1, 1, 1, 0, 0, 1, 0],  # Sun-Tue, Fri
        'X': [0, 1, 0, 0, 1, 1, 1],  # Mon, Thu-Sat
        'Y': [0, 0, 1, 1, 1, 0, 1],  # Tue-Thu, Sat
        'Z': [0, 1, 1, 1, 0, 1, 0],  # Mon-Wed, Fri
        '1': [0, 1, 1, 1, 0, 1, 0],  # Mon-Wed, Fri
        '2': [1, 1, 0, 0, 1, 0, 1],  # Sun-Mon, Thu, Sat
        '3': [0, 1, 1, 1, 0, 0, 1],  # Mon-Wed, Sat
        '4': [0, 1, 0, 1, 1, 1, 0],  # Mon, Wed-Fri
        '5': [1, 1, 1, 0, 1, 0, 0],  # Sun-Tue, Thu
    }
    
    days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    shifts = ['D', 'N']  # Day and Night shifts
    
    # Create base patterns
    patterns_data = []
    for shift in shifts:
        for pattern_code, pattern in base_patterns.items():
            pattern_id = f"{shift}{pattern_code}"
            pattern_row = {
                'Pattern': pattern_id,
                'Shift': 'Day' if shift == 'D' else 'Night',
                'Base_Pattern': pattern_code
            }
            # Add scheduled days
            for i, day in enumerate(days):
                pattern_row[day] = pattern[i]
            patterns_data.append(pattern_row)
    
    df = pd.DataFrame(patterns_data)
    
    # Calculate working days
    df['Days'] = df[days].sum(axis=1)
    
    # Calculate weekend days based on shift type
    df['Weekend_Days'] = df.apply(lambda row: 
        sum(row[['Sat', 'Sun']]) if row['Shift'] == 'Day' else 
        sum(row[['Fri', 'Sat', 'Sun']]), axis=1)
    
    # Categorize each pattern
    df['Weekend_Category'] = df.apply(lambda row: 
        categorize_shift_pattern(row['Pattern'], days, {day: row[day] for day in days}), axis=1)
    
    # Calculate cost multiplier - will be updated by UI settings
    df['Cost_Multiplier'] = 1.0
    
    return df

def filter_patterns(patterns_df: pd.DataFrame, filter_type: str) -> List[str]:
    """
    Filters patterns based on the specified filter type.
    
    Args:
        patterns_df: DataFrame containing pattern information
        filter_type: Type of filter to apply ("All patterns", "4-day patterns", "5-day patterns", "Custom selection")
        
    Returns:
        List of filtered pattern codes
    """
    if filter_type == "All patterns":
        return patterns_df['Pattern'].tolist()
    elif filter_type == "4-day patterns":
        return patterns_df[patterns_df['Days'] == 4]['Pattern'].tolist()
    elif filter_type == "5-day patterns":
        return patterns_df[patterns_df['Days'] == 5]['Pattern'].tolist()
    else:  # Custom selection
        return patterns_df['Pattern'].tolist()

def validate_requirements(day_requirements: Dict[str, int], night_requirements: Dict[str, int]) -> bool:
    """
    Validates staffing requirements to ensure they are reasonable.
    
    Args:
        day_requirements (Dict[str, int]): Day shift requirements by day
        night_requirements (Dict[str, int]): Night shift requirements by day
    
    Returns:
        bool: True if requirements are valid, False otherwise
    """
    # Check if all values are numeric and non-negative
    for day, value in day_requirements.items():
        if not isinstance(value, (int, float)):
            raise ValueError(f"Day shift requirement for {day} must be a number, got {type(value)}")
        if value < 0:
            raise ValueError(f"Day shift requirement for {day} must be non-negative, got {value}")
    
    for day, value in night_requirements.items():
        if not isinstance(value, (int, float)):
            raise ValueError(f"Night shift requirement for {day} must be a number, got {type(value)}")
        if value < 0:
            raise ValueError(f"Night shift requirement for {day} must be non-negative, got {value}")
    
    # Check if at least one requirement is greater than 0
    if not any(value > 0 for value in day_requirements.values()) and not any(value > 0 for value in night_requirements.values()):
        raise ValueError("At least one shift requirement must be greater than 0")
    
    return True

def optimize_staffing(patterns_df: pd.DataFrame, selected_patterns: List[str], 
                     day_requirements: Dict[str, int], night_requirements: Dict[str, int], 
                     optimize_cost: bool = True, max_overstaffing: float = 0.15) -> Tuple[pd.DataFrame, Dict[str, float], Dict[str, float]]:
    """
    Optimizes staffing patterns to meet requirements while minimizing cost or headcount.
    Phase 1: Optimizes base pattern staffing.
    
    Args:
        patterns_df: DataFrame with pattern data
        selected_patterns: List of patterns to include in optimization
        day_requirements: Dictionary with day shift requirements by day of week
        night_requirements: Dictionary with night shift requirements by day of week
        optimize_cost: If True, optimize for cost, else optimize for headcount
        max_overstaffing: Maximum percentage (0.0-1.0) of overstaffing allowed above requirements
    """
    model = pulp.LpProblem("Staffing_Optimization", pulp.LpMinimize)
    
    days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    
    # Find peak demands
    peak_day_demand = max(day_requirements.values())
    peak_night_demand = max(night_requirements.values())
    
    # Calculate minimum staff needed
    min_day_staff = int(peak_day_demand * 1.4)
    min_night_staff = int(peak_night_demand * 1.4)
    max_staff = max(min_day_staff, min_night_staff)
    
    # Pattern variables
    pattern_vars = {
        pattern: pulp.LpVariable(f'Pattern_{pattern}', 
                               lowBound=0,
                               upBound=max_staff,
                               cat='Integer')
        for pattern in selected_patterns
    }
    
    # Staffing requirements constraints
    for day in days:
        # Day shift - lower bound
        model += (
            pulp.lpSum(
                patterns_df[patterns_df['Pattern'] == p][day].iloc[0] * pattern_vars[p]
                for p in selected_patterns
                if patterns_df[patterns_df['Pattern'] == p]['Shift'].iloc[0] == 'Day'
            ) >= day_requirements[day]
        )
        
        # Day shift - upper bound to prevent overstaffing
        model += (
            pulp.lpSum(
                patterns_df[patterns_df['Pattern'] == p][day].iloc[0] * pattern_vars[p]
                for p in selected_patterns
                if patterns_df[patterns_df['Pattern'] == p]['Shift'].iloc[0] == 'Day'
            ) <= day_requirements[day] * (1 + max_overstaffing)
        )
        
        # Night shift - lower bound
        model += (
            pulp.lpSum(
                patterns_df[patterns_df['Pattern'] == p][day].iloc[0] * pattern_vars[p]
                for p in selected_patterns
                if patterns_df[patterns_df['Pattern'] == p]['Shift'].iloc[0] == 'Night'
            ) >= night_requirements[day]
        )
        
        # Night shift - upper bound to prevent overstaffing
        model += (
            pulp.lpSum(
                patterns_df[patterns_df['Pattern'] == p][day].iloc[0] * pattern_vars[p]
                for p in selected_patterns
                if patterns_df[patterns_df['Pattern'] == p]['Shift'].iloc[0] == 'Night'
            ) <= night_requirements[day] * (1 + max_overstaffing)
        )
    
    # Group patterns by base pattern (e.g., DA, NA) for balancing
    base_patterns = {}
    max_diff_vars = []  # Keep track of max difference variables
    
    for pattern in selected_patterns:
        base = pattern[:2]  # Get shift and base pattern code
        if base not in base_patterns:
            base_patterns[base] = []
        base_patterns[base].append(pattern)
    
    # Balance constraints for each base pattern group
    for base, patterns in base_patterns.items():
        if len(patterns) > 1:
            # Ensure relatively even distribution within each pattern group
            avg_var = pulp.LpVariable(f'Avg_{base}', lowBound=0)
            max_diff = pulp.LpVariable(f'MaxDiff_{base}', lowBound=0)
            max_diff_vars.append(max_diff)  # Add to our list
            
            for pattern in patterns:
                model += pattern_vars[pattern] - avg_var <= max_diff
                model += avg_var - pattern_vars[pattern] <= max_diff
    
    # Objective function
    if optimize_cost:
        model += (
            # Base cost
            pulp.lpSum(
                pattern_vars[p] * patterns_df[patterns_df['Pattern'] == p]['Cost_Multiplier'].iloc[0]
                for p in selected_patterns
            ) +
            # Pattern balance penalty
            100 * pulp.lpSum(max_diff_vars)  # Use our collected max_diff variables
        )
    else:
        model += (
            # Minimize total headcount
            pulp.lpSum(pattern_vars.values()) +
            # Pattern balance penalty
            100 * pulp.lpSum(max_diff_vars)  # Use our collected max_diff variables
        )
    
    # Solve
    solver = pulp.PULP_CBC_CMD(msg=0)
    solver.options = ['maxSeconds 300', 'allowableGap 0.01']
    status = model.solve(solver)
    
    if status != pulp.LpStatusOptimal:
        raise ValueError(f"Optimization failed with status: {pulp.LpStatus[status]}")
    
    # Get results
    results = []
    for pattern in selected_patterns:
        if pulp.value(pattern_vars[pattern]) > 0:
            pattern_data = patterns_df[patterns_df['Pattern'] == pattern].iloc[0].to_dict()
            pattern_data['Employees'] = int(pulp.value(pattern_vars[pattern]))
            results.append(pattern_data)
    
    results_df = pd.DataFrame(results)
    
    # Calculate staffing levels
    day_staffing = {day: sum(
        row['Employees'] * row[day]
        for _, row in results_df.iterrows()
        if row['Shift'] == 'Day'
    ) for day in days}
    
    night_staffing = {day: sum(
        row['Employees'] * row[day]
        for _, row in results_df.iterrows()
        if row['Shift'] == 'Night'
    ) for day in days}
    
    return results_df, day_staffing, night_staffing

def optimize_met_distribution(pattern_staff_dict: Dict[str, int], shift: str, day_requirements: Dict[str, int]) -> pd.DataFrame:
    """
    Optimizes the distribution of staff across MET days based on daily demand.
    For each pattern, assigns staff to MET days (off days) with a goal to maximize flexibility
    by spreading MET assignments across all days of the week.
    
    Args:
        pattern_staff_dict: Dictionary mapping base patterns to number of staff
        shift: 'Day' or 'Night'
        day_requirements: Daily staffing requirements
    
    Returns:
        DataFrame with MET day assignments for all patterns
    """
    if not pattern_staff_dict:
        return pd.DataFrame()  # Return empty dataframe if no patterns
    
    days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    # Map MET day numbers to actual days (using 1-based indexing to match pattern codes)
    day_map = {1: 'Sun', 2: 'Mon', 3: 'Tue', 4: 'Wed', 5: 'Thu', 6: 'Fri', 7: 'Sat'}
    day_to_idx = {day: i for i, day in enumerate(days)}
    
    # Get off days for each pattern from the pattern's code
    pattern_off_days = {
        'A': ['Thu', 'Fri', 'Sat'],  # Sun-Wed pattern, off Thu-Sat
        'B': ['Sun', 'Mon', 'Tue'],  # Thu-Sat pattern, off Sun-Tue
        'C': ['Fri', 'Sat'],         # Mon-Thu pattern, off Fri-Sat
        'D': ['Sun', 'Mon'],         # Tue-Fri pattern, off Sun-Mon
        'E': ['Sat'],                # Mon-Fri pattern, off Sat
        'F': ['Sat'],                # Mon-Fri pattern, off Sat
        'G': ['Tue', 'Wed', 'Sat'],  # Sun-Mon, Thu-Fri pattern
        'H': ['Tue', 'Fri', 'Sat'],  # Sun-Mon, Wed-Thu pattern
        'I': ['Mon', 'Fri', 'Sat'],  # Sun, Tue-Thu pattern
        'J': ['Tue', 'Fri'],         # Mon, Wed-Thu, Sat pattern
        'K': ['Wed', 'Sat'],         # Mon-Tue, Thu-Fri pattern
        'L': ['Wed', 'Thu', 'Fri'],  # Sun-Tue, Sat pattern
        'M': ['Sun', 'Mon', 'Fri'],  # Tue-Thu, Sat pattern
        'N': ['Mon', 'Tue', 'Wed'],  # Sun, Thu-Sat pattern
        'O': ['Tue', 'Wed', 'Thu'],  # Sun-Mon, Fri-Sat pattern
        'P': ['Thu', 'Fri', 'Sat'],  # Sun-Wed pattern
        'Q': ['Fri', 'Sat'],         # Mon-Thu pattern
        'R': ['Wed', 'Sat'],         # Mon-Tue, Thu-Fri pattern
        'S': ['Mon', 'Tue'],         # Sun, Wed-Fri pattern
        'T': ['Thu', 'Fri', 'Sat'],  # Sun-Wed pattern
        'U': ['Tue', 'Wed', 'Sat'],  # Sun-Mon, Thu-Fri pattern
        'V': ['Thu', 'Fri'],         # Sun, Tue-Wed, Sat pattern
        'W': ['Wed', 'Thu', 'Sat'],  # Sun-Tue, Fri pattern
        'X': ['Tue', 'Wed', 'Sun'],  # Mon, Thu-Sat pattern
        'Y': ['Sun', 'Mon', 'Fri'],  # Tue-Thu, Sat pattern
        'Z': ['Thu', 'Sat'],         # Mon-Wed, Fri pattern
        '1': ['Thu', 'Sat'],         # Mon-Wed, Fri pattern
        '2': ['Tue', 'Wed', 'Fri'],  # Sun-Mon, Thu, Sat pattern
        '3': ['Thu', 'Fri'],         # Mon-Wed, Sat pattern
        '4': ['Tue', 'Sat'],         # Mon, Wed-Fri pattern
        '5': ['Wed', 'Fri', 'Sat'],  # Sun-Tue, Thu pattern
    }
    
    all_met_results = []
    
    # Need global model to ensure maximizing coverage across all days
    global_model = pulp.LpProblem(f"{shift}_Global_MET_Distribution", pulp.LpMinimize)
    
    # Track MET coverage by day across all patterns
    met_day_coverage = {day: pulp.LpVariable(f'MET_{day}_Coverage', lowBound=0) for day in days}
    
    # Pattern-specific variables
    pattern_met_vars = {}
    
    # For each pattern, create variables for MET day assignments
    for pattern_code, staff_count in pattern_staff_dict.items():
        if staff_count <= 0:
            continue
            
        # Get off days that can be used for MET
        off_days = pattern_off_days.get(pattern_code, [])
        if not off_days:
            continue  # Skip if no off days available for MET
            
        # Variables for each MET day option for this pattern
        pattern_met_vars[pattern_code] = {
            day_to_idx[day] + 1: pulp.LpVariable(f'MET_{pattern_code}_{day}', 
                                   lowBound=0,
                                   upBound=staff_count,
                                   cat='Integer')
            for day in off_days
        }
        
        # All staff for this pattern must be assigned a MET day
        global_model += pulp.lpSum(pattern_met_vars[pattern_code].values()) == staff_count
    
    # Calculate total MET coverage by day
    for day in days:
        day_idx = day_to_idx[day] + 1
        global_model += met_day_coverage[day] == pulp.lpSum(
            pattern_met_vars[pattern][day_idx] 
            for pattern in pattern_met_vars 
            if day_idx in pattern_met_vars[pattern]
        )
    
    # Objective: maximize the minimum MET coverage across all days
    # This will ensure more even distribution
    min_coverage = pulp.LpVariable('Min_MET_Coverage', lowBound=0)
    max_coverage = pulp.LpVariable('Max_MET_Coverage', lowBound=0)
    
    # Set min and max coverage bounds
    for day in days:
        global_model += met_day_coverage[day] >= min_coverage
        global_model += met_day_coverage[day] <= max_coverage
    
    # Objective: minimize the difference between max and min coverage
    # This encourages even spread while still meeting needs
    global_model += (max_coverage - min_coverage) - 0.01 * pulp.lpSum(
        met_day_coverage[day] * day_requirements[day] for day in days
    )
    
    # Solve
    try:
        solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=60)  # 1 minute time limit
        status = global_model.solve(solver)
        
        if status != pulp.LpStatusOptimal and status != pulp.LpStatusFeasible:
            logger.warning(f"Global MET optimization failed with status: {pulp.LpStatus[status]}")
            # Fall back to individual pattern optimization
            return fallback_optimize_met_distribution(pattern_staff_dict, shift, day_requirements)
            
        # Create results from the global model
        shift_letter = 'D' if shift == 'Day' else 'N'
        
        for pattern_code in pattern_met_vars:
            for day_idx in pattern_met_vars[pattern_code]:
                staff = int(pulp.value(pattern_met_vars[pattern_code][day_idx]))
                if staff > 0:
                    all_met_results.append({
                        'Pattern': f'{shift_letter}{pattern_code}{day_idx}',
                        'Shift': shift,
                        'Base_Pattern': pattern_code,
                        'MET_Day': day_map[day_idx],
                        'Employees': staff
                    })
    except Exception as e:
        logger.error(f"Error in global MET optimization: {str(e)}")
        # Fall back to individual pattern optimization
        return fallback_optimize_met_distribution(pattern_staff_dict, shift, day_requirements)
    
    return pd.DataFrame(all_met_results)

def fallback_optimize_met_distribution(pattern_staff_dict: Dict[str, int], shift: str, day_requirements: Dict[str, int]) -> pd.DataFrame:
    """
    Fallback method that optimizes MET distribution pattern by pattern if the global approach fails.
    """
    days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    day_map = {1: 'Sun', 2: 'Mon', 3: 'Tue', 4: 'Wed', 5: 'Thu', 6: 'Fri', 7: 'Sat'}
    day_to_idx = {day: i for i, day in enumerate(days)}
    
    pattern_off_days = {
        'A': ['Thu', 'Fri', 'Sat'],  # Sun-Wed pattern, off Thu-Sat
        'B': ['Sun', 'Mon', 'Tue'],  # Thu-Sat pattern, off Sun-Tue
        'C': ['Fri', 'Sat'],         # Mon-Thu pattern, off Fri-Sat
        'D': ['Sun', 'Mon'],         # Tue-Fri pattern, off Sun-Mon
        'E': ['Sat'],                # Mon-Fri pattern, off Sat
        'F': ['Sat'],                # Mon-Fri pattern, off Sat
        'G': ['Tue', 'Wed', 'Sat'],  # Sun-Mon, Thu-Fri pattern
        'H': ['Tue', 'Fri', 'Sat'],  # Sun-Mon, Wed-Thu pattern
        'I': ['Mon', 'Fri', 'Sat'],  # Sun, Tue-Thu pattern
        'J': ['Tue', 'Fri'],         # Mon, Wed-Thu, Sat pattern
        'K': ['Wed', 'Sat'],         # Mon-Tue, Thu-Fri pattern
        'L': ['Wed', 'Thu', 'Fri'],  # Sun-Tue, Sat pattern
        'M': ['Sun', 'Mon', 'Fri'],  # Tue-Thu, Sat pattern
        'N': ['Mon', 'Tue', 'Wed'],  # Sun, Thu-Sat pattern
        'O': ['Tue', 'Wed', 'Thu'],  # Sun-Mon, Fri-Sat pattern
        'P': ['Thu', 'Fri', 'Sat'],  # Sun-Wed pattern
        'Q': ['Fri', 'Sat'],         # Mon-Thu pattern
        'R': ['Wed', 'Sat'],         # Mon-Tue, Thu-Fri pattern
        'S': ['Mon', 'Tue'],         # Sun, Wed-Fri pattern
        'T': ['Thu', 'Fri', 'Sat'],  # Sun-Wed pattern
        'U': ['Tue', 'Wed', 'Sat'],  # Sun-Mon, Thu-Fri pattern
        'V': ['Thu', 'Fri'],         # Sun, Tue-Wed, Sat pattern
        'W': ['Wed', 'Thu', 'Sat'],  # Sun-Tue, Fri pattern
        'X': ['Tue', 'Wed', 'Sun'],  # Mon, Thu-Sat pattern
        'Y': ['Sun', 'Mon', 'Fri'],  # Tue-Thu, Sat pattern
        'Z': ['Thu', 'Sat'],         # Mon-Wed, Fri pattern
        '1': ['Thu', 'Sat'],         # Mon-Wed, Fri pattern
        '2': ['Tue', 'Wed', 'Fri'],  # Sun-Mon, Thu, Sat pattern
        '3': ['Thu', 'Fri'],         # Mon-Wed, Sat pattern
        '4': ['Tue', 'Sat'],         # Mon, Wed-Fri pattern
        '5': ['Wed', 'Fri', 'Sat'],  # Sun-Tue, Thu pattern
    }
    
    all_met_results = []
    
    for pattern_code, staff_count in pattern_staff_dict.items():
        if staff_count <= 0:
            continue
            
        off_days = pattern_off_days.get(pattern_code, [])
        if not off_days:
            continue
            
        model = pulp.LpProblem(f"{shift}_{pattern_code}_MET_Distribution", pulp.LpMinimize)
        
        met_vars = {
            day_to_idx[day] + 1: pulp.LpVariable(f'MET_{pattern_code}_{day}', 
                                   lowBound=0,
                                   upBound=staff_count,
                                   cat='Integer')
            for day in off_days
        }
        
        model += pulp.lpSum(met_vars.values()) == staff_count
        
        if len(met_vars) > 1:
            max_diff = pulp.LpVariable(f'Max_Diff_{pattern_code}', lowBound=0)
            avg_met = staff_count / len(met_vars)
            
            for day_idx in met_vars:
                model += met_vars[day_idx] - avg_met <= max_diff
                model += avg_met - met_vars[day_idx] <= max_diff
            
            objective_terms = [max_diff]
            for day_idx in met_vars:
                day_name = day_map[day_idx]
                objective_terms.append(-0.1 * met_vars[day_idx] * day_requirements[day_name])
            
            model += pulp.lpSum(objective_terms)
        else:
            day_idx = list(met_vars.keys())[0]
            model += met_vars[day_idx] == staff_count
        
        try:
            status = model.solve(pulp.PULP_CBC_CMD(msg=0))
            
            if status != pulp.LpStatusOptimal:
                logger.warning(f"MET optimization for {pattern_code} failed: {pulp.LpStatus[status]}")
                continue
                
            shift_letter = 'D' if shift == 'Day' else 'N'
            
            for day_idx in met_vars:
                staff = int(pulp.value(met_vars[day_idx]))
                if staff > 0:
                    all_met_results.append({
                        'Pattern': f'{shift_letter}{pattern_code}{day_idx}',
                        'Shift': shift,
                        'Base_Pattern': pattern_code,
                        'MET_Day': day_map[day_idx],
                        'Employees': staff
                    })
        except Exception as e:
            logger.error(f"Error optimizing MET for {pattern_code}: {str(e)}")
    
    return pd.DataFrame(all_met_results)

def plot_met_distribution(met_df):
    """
    Plots the MET day distribution by day of week.
    Shows how many employees are assigned to each MET day.
    
    Args:
        met_df (pd.DataFrame): DataFrame containing the MET assignments
    """
    if met_df.empty:
        return None
        
    days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']  # Show all days
    
    # Create figure
    fig = make_subplots(rows=1, cols=1, subplot_titles=['MET Day Distribution'])
    
    # Calculate MET distribution for day shift
    day_met_data = []
    for day in days:
        day_met = met_df[
            (met_df['Shift'] == 'Day') & 
            (met_df['MET_Day'] == day)
        ]['Employees'].sum()
        day_met_data.append(day_met)
    
    # Calculate MET distribution for night shift
    night_met_data = []
    for day in days:
        night_met = met_df[
            (met_df['Shift'] == 'Night') & 
            (met_df['MET_Day'] == day)
        ]['Employees'].sum()
        night_met_data.append(night_met)
    
    # Add day shift MET data
    fig.add_trace(
        go.Bar(x=days, y=day_met_data, name="Day Shift MET", marker_color='cornflowerblue')
    )
    
    # Add night shift MET data
    fig.add_trace(
        go.Bar(x=days, y=night_met_data, name="Night Shift MET", marker_color='mediumseagreen')
    )
    
    # Add total MET data
    total_met_data = [day_met_data[i] + night_met_data[i] for i in range(len(days))]
    fig.add_trace(
        go.Scatter(x=days, y=total_met_data, name="Total MET", 
                  line=dict(color='darkred', width=3), mode='lines+markers')
    )
    
    fig.update_layout(
        barmode='stack',
        height=400,
        title='MET Day Distribution Across Week',
        xaxis_title='Day of Week',
        yaxis_title='Number of Employees',
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5
        )
    )
    return fig

def plot_coverage(day_staffing, night_staffing, day_requirements, night_requirements, met_df=None):
    """
    Plots comprehensive coverage including regular staffing and MET assignments.
    
    Args:
        day_staffing: Regular day shift staffing levels
        night_staffing: Regular night shift staffing levels
        day_requirements: Day shift requirements
        night_requirements: Night shift requirements
        met_df: DataFrame with MET assignments (optional)
    """
    days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    
    fig = make_subplots(rows=2, cols=1, 
                        subplot_titles=('Day Shift Coverage', 'Night Shift Coverage'),
                        vertical_spacing=0.12,
                        row_heights=[0.5, 0.5])
    
    # Calculate MET availablity by day if provided
    day_met = {day: 0 for day in days}
    night_met = {day: 0 for day in days}
    
    if met_df is not None and not met_df.empty:
        for day in days:
            day_met[day] = met_df[
                (met_df['Shift'] == 'Day') & 
                (met_df['MET_Day'] == day)
            ]['Employees'].sum()
            
            night_met[day] = met_df[
                (met_df['Shift'] == 'Night') & 
                (met_df['MET_Day'] == day)
            ]['Employees'].sum()
    
    # Day shift - Requirements
    fig.add_trace(
        go.Bar(x=days, y=[day_requirements[day] for day in days], 
               name="Required", marker_color='indianred',
               width=0.4, offset=-0.3),
        row=1, col=1
    )
    
    # Day shift - Regular staffing
    fig.add_trace(
        go.Bar(x=days, y=[day_staffing[day] for day in days], 
               name="Regular", marker_color='royalblue',
               width=0.4, offset=0.1),
        row=1, col=1
    )
    
    # Day shift - MET availability
    if met_df is not None:
        fig.add_trace(
            go.Bar(x=days, y=[day_met[day] for day in days], 
                   name="MET Available", marker_color='forestgreen',
                   width=0.15, offset=0.525),
            row=1, col=1
        )
    
    # Night shift - Requirements
    fig.add_trace(
        go.Bar(x=days, y=[night_requirements[day] for day in days], 
               name="Required", marker_color='indianred',
               width=0.4, offset=-0.3, showlegend=False),
        row=2, col=1
    )
    
    # Night shift - Regular staffing
    fig.add_trace(
        go.Bar(x=days, y=[night_staffing[day] for day in days], 
               name="Regular", marker_color='royalblue',
               width=0.4, offset=0.1, showlegend=False),
        row=2, col=1
    )
    
    # Night shift - MET availability
    if met_df is not None:
        fig.add_trace(
            go.Bar(x=days, y=[night_met[day] for day in days], 
                   name="MET Available", marker_color='forestgreen',
                   width=0.15, offset=0.525, showlegend=False),
            row=2, col=1
        )
    
    # Add total capacity (Regular + MET) lines
    if met_df is not None:
        day_total = [day_staffing[day] + day_met[day] for day in days]
        night_total = [night_staffing[day] + night_met[day] for day in days]
        
        fig.add_trace(
            go.Scatter(x=days, y=day_total, name="Max Capacity", 
                       line=dict(color='darkgreen', width=2, dash='dot')),
            row=1, col=1
        )
        
        fig.add_trace(
            go.Scatter(x=days, y=night_total, name="Max Capacity", 
                       line=dict(color='darkgreen', width=2, dash='dot'),
                       showlegend=False),
            row=2, col=1
        )
    
    # Update layout
    fig.update_layout(
        height=800,
        barmode='group',
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5
        ),
        margin=dict(t=100)
    )
    
    # Update axes for better readability
    fig.update_xaxes(tickangle=0)
    fig.update_yaxes(title_text="Employees", row=1, col=1)
    fig.update_yaxes(title_text="Employees", row=2, col=1)
    
    return fig

def calculate_weekly_sd_costs(results_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculates weekly shift differential costs based on 40-hour work weeks.
    
    Args:
        results_df: DataFrame containing optimization results
        
    Returns:
        DataFrame with weekly SD costs by pattern
    """
    # Create a copy to avoid modifying original
    cost_df = results_df.copy()
    
    # Calculate SD rate (the additional percentage above base rate)
    cost_df['SD_Rate'] = cost_df['Cost_Multiplier'] - 1.0
    
    # Calculate weekly SD cost (40 hours × SD rate × base rate × headcount)
    # Assuming base_rate is $1 for relative calculations
    cost_df['Weekly_SD_Hours'] = 40  # All patterns are 40-hour weeks
    cost_df['Weekly_SD_Cost'] = (
        cost_df['Weekly_SD_Hours'] * 
        cost_df['SD_Rate'] * 
        cost_df['Employees']
    )
    
    return cost_df

def create_summary_tables(results_df, day_staffing, night_staffing, 
                          day_requirements, night_requirements, met_df):
    """
    Creates comprehensive summary tables for staffing results.
    """
    days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    
    # Calculate weekly SD costs
    results_with_costs = calculate_weekly_sd_costs(results_df)
    
    # 1. Daily Staffing Summary
    staffing_data = []
    
    # Calculate MET availability by day
    day_met = {day: 0 for day in days}
    night_met = {day: 0 for day in days}
    
    if not met_df.empty:
        for day in days:
            day_met[day] = met_df[
                (met_df['Shift'] == 'Day') & 
                (met_df['MET_Day'] == day)
            ]['Employees'].sum()
            
            night_met[day] = met_df[
                (met_df['Shift'] == 'Night') & 
                (met_df['MET_Day'] == day)
            ]['Employees'].sum()
    
    for day in days:
        # Calculate percentages as numbers first, format as strings later
        day_coverage_pct = round((day_staffing[day] / day_requirements[day]) * 100, 1)
        day_max_coverage_pct = round(((day_staffing[day] + day_met[day]) / day_requirements[day]) * 100, 1)
        night_coverage_pct = round((night_staffing[day] / night_requirements[day]) * 100, 1)
        night_max_coverage_pct = round(((night_staffing[day] + night_met[day]) / night_requirements[day]) * 100, 1)
        
        day_row = {
            'Day': day,
            'Day Required': day_requirements[day],
            'Day Regular': round(day_staffing[day], 1),
            'Day MET Available': day_met[day],
            'Day Potential Coverage': round(day_staffing[day] + day_met[day], 1),
            'Day Coverage %': f"{day_coverage_pct}%",
            'Day Max Coverage %': f"{day_max_coverage_pct}%",
            'Night Required': night_requirements[day],
            'Night Regular': round(night_staffing[day], 1),
            'Night MET Available': night_met[day],
            'Night Potential Coverage': round(night_staffing[day] + night_met[day], 1),
            'Night Coverage %': f"{night_coverage_pct}%",
            'Night Max Coverage %': f"{night_max_coverage_pct}%"
        }
        staffing_data.append(day_row)
    
    staffing_summary = pd.DataFrame(staffing_data)
    
    # 2. Pattern Distribution Summary with Costs
    pattern_summary = results_with_costs.groupby(['Shift', 'Base_Pattern', 'Weekend_Category']).agg({
        'Employees': 'sum',
        'Weekly_SD_Cost': 'sum',
        'Cost_Multiplier': 'first'
    }).reset_index()
    
    # Add percentage column
    total_employees = results_with_costs['Employees'].sum()
    pattern_summary['Percentage'] = (pattern_summary['Employees'] / total_employees * 100).round(1).apply(lambda x: f"{x}%")
    
    # Format cost multiplier
    pattern_summary['Rate'] = pattern_summary['Cost_Multiplier'].apply(lambda x: f"{x:.2f}x")
    
    # Calculate total weekly SD cost
    total_weekly_sd = results_with_costs['Weekly_SD_Cost'].sum()
    
    # 3. MET Distribution By Pattern and Day
    if not met_df.empty:
        met_pivot = met_df.pivot_table(
            index=['Shift', 'Base_Pattern'],
            columns='MET_Day',
            values='Employees',
            aggfunc='sum',
            fill_value=0
        ).reset_index()
        
        available_days = [day for day in days if day in met_pivot.columns]
        met_pivot['Total'] = met_pivot[available_days].sum(axis=1)
        available_columns = ['Shift', 'Base_Pattern'] + available_days + ['Total']
        met_summary = met_pivot[available_columns]
    else:
        met_summary = pd.DataFrame(columns=['Shift', 'Base_Pattern'] + days + ['Total'])
    
    return staffing_summary, pattern_summary, met_summary, total_weekly_sd

def create_ctp_targets_chart(results_df, met_df):
    """
    Creates a chart showing CTP (Capacity Targets Plan) - what percentage of 
    total headcount should be hired to each MET level cohort.
    
    Args:
        results_df: DataFrame with base pattern results
        met_df: DataFrame with MET assignments
    
    Returns:
        A Plotly figure object
    """
    if met_df.empty:
        return None
        
    # Create the CTP targets dataframe
    total_hc = results_df['Employees'].sum()
    
    # First, group by shift and base pattern
    base_pattern_counts = results_df.groupby(['Shift', 'Base_Pattern'])['Employees'].sum().reset_index()
    # Use the actual pattern code (e.g., DA, NB) for display
    base_pattern_counts['Display_Code'] = base_pattern_counts.apply(
        lambda row: ('D' if row['Shift'] == 'Day' else 'N') + row['Base_Pattern'], 
        axis=1
    )
    base_pattern_counts['Percentage'] = (base_pattern_counts['Employees'] / total_hc * 100).round(1)
    
    # Now handle MET cohorts
    met_cohorts = met_df.copy()
    # Use the actual pattern code in format (e.g., DA5, NB2)
    met_cohorts['Display_Code'] = met_cohorts['Pattern']
    met_cohort_counts = met_cohorts.groupby('Display_Code').agg({
        'Employees': 'sum',
        'Shift': 'first',
        'Base_Pattern': 'first',
        'MET_Day': 'first'
    }).reset_index()
    met_cohort_counts['Percentage'] = (met_cohort_counts['Employees'] / total_hc * 100).round(1)
    
    # Create the visualization
    fig = go.Figure()
    
    # Add a bar for each shift-pattern combination
    for shift in ['Day', 'Night']:
        shift_data = base_pattern_counts[base_pattern_counts['Shift'] == shift]
        
        # Sort by pattern code
        shift_data = shift_data.sort_values('Base_Pattern')
        
        # Add the base patterns
        fig.add_trace(go.Bar(
            x=shift_data['Display_Code'],
            y=shift_data['Percentage'],
            name=f"{shift} Base Patterns",
            marker_color='royalblue' if shift == 'Day' else 'mediumseagreen',
            text=[f"{p:.1f}%" for p in shift_data['Percentage']],
            textposition='auto',
            hovertemplate="<b>%{x}</b><br>Headcount: %{customdata}<br>Percentage: %{y:.1f}%<extra></extra>",
            customdata=shift_data['Employees']
        ))
    
    # Add a second trace for MET cohorts
    for shift in ['Day', 'Night']:
        shift_met_data = met_cohort_counts[met_cohort_counts['Shift'] == shift]
        
        # Sort by pattern and MET day
        shift_met_data = shift_met_data.sort_values(['Base_Pattern', 'MET_Day'])
        
        if not shift_met_data.empty:
            fig.add_trace(go.Bar(
                x=shift_met_data['Display_Code'],
                y=shift_met_data['Percentage'],
                name=f"{shift} MET Cohorts",
                marker_color='cornflowerblue' if shift == 'Day' else 'lightgreen',
                text=[f"{p:.1f}%" for p in shift_met_data['Percentage']],
                textposition='auto',
                hovertemplate="<b>%{x}</b><br>Headcount: %{customdata}<br>Percentage: %{y:.1f}%<extra></extra>",
                customdata=shift_met_data['Employees']
            ))
    
    # Update layout for better readability
    fig.update_layout(
        title='CTP Targets: Percentage of Total Headcount by Pattern and MET Cohort',
        xaxis_title='Pattern Code',
        yaxis_title='Percentage of Total Headcount',
        height=600,
        barmode='group',
        bargap=0.15,
        bargroupgap=0.1,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5
        ),
        yaxis=dict(
            ticksuffix="%",
            range=[0, max(base_pattern_counts['Percentage'].max(), 
                          met_cohort_counts['Percentage'].max() if not met_cohort_counts.empty else 0) * 1.1]
        ),
        margin=dict(l=50, r=50, t=100, b=100)
    )
    
    # Add annotations for better clarity
    fig.add_annotation(
        x=0.5, y=1.15,
        xref="paper", yref="paper",
        text="<b>Hire these percentages of total headcount to each pattern/cohort</b>",
        showarrow=False,
        font=dict(size=14)
    )
    
    return fig

def calculate_current_costs(patterns_df: pd.DataFrame, current_staffing: Dict[str, int]) -> Tuple[float, Dict[str, float], Dict[str, float]]:
    """
    Calculates current staffing costs and daily coverage.
    
    Args:
        patterns_df: DataFrame containing pattern information
        current_staffing: Dictionary mapping pattern codes to current headcount
        
    Returns:
        Tuple of (total_weekly_cost, day_coverage, night_coverage)
    """
    days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    day_coverage = {day: 0 for day in days}
    night_coverage = {day: 0 for day in days}
    total_weekly_cost = 0.0
    
    for pattern, count in current_staffing.items():
        if count > 0:
            pattern_data = patterns_df[patterns_df['Pattern'] == pattern].iloc[0]
            
            # Calculate weekly cost
            weekly_cost = 40 * (pattern_data['Cost_Multiplier'] - 1.0) * count
            total_weekly_cost += weekly_cost
            
            # Calculate daily coverage
            for day in days:
                if pattern_data['Shift'] == 'Day':
                    day_coverage[day] += pattern_data[day] * count
                else:
                    night_coverage[day] += pattern_data[day] * count
    
    return total_weekly_cost, day_coverage, night_coverage

def load_test_values():
    """
    Returns test values for staffing requirements and current staffing.
    """
    # Test staffing requirements
    day_req = {
        'Sun': 800, 'Mon': 800, 'Tue': 800, 'Wed': 800, 
        'Thu': 800, 'Fri': 800, 'Sat': 800
    }
    night_req = {
        'Sun': 800, 'Mon': 800, 'Tue': 800, 'Wed': 800, 
        'Thu': 800, 'Fri': 800, 'Sat': 800
    }
    
    # Test current staffing with shift pattern-level headcount
    current_staffing = {
        # Day shift patterns
        'DA': 100, 'DB': 100, 'DC': 100, 'DD': 100, 'DE': 100,
        'DF': 100, 'DG': 100, 'DH': 100, 'DI': 100, 'DJ': 100,
        'DK': 100, 'DL': 100, 'DM': 100, 'DN': 100, 'DO': 100,
        'DP': 100, 'DQ': 100, 'DR': 100, 'DS': 100, 'DT': 100,
        'DU': 100, 'DV': 100, 'DW': 100, 'DX': 100, 'DY': 100,
        'DZ': 100, 'D1': 100, 'D2': 100, 'D3': 100, 'D4': 100,
        'D5': 100,
        # Night shift patterns
        'NA': 100, 'NB': 100, 'NC': 100, 'ND': 100, 'NE': 100,
        'NF': 100, 'NG': 100, 'NH': 100, 'NI': 100, 'NJ': 100,
        'NK': 100, 'NL': 100, 'NM': 100, 'NN': 100, 'NO': 100,
        'NP': 100, 'NQ': 100, 'NR': 100, 'NS': 100, 'NT': 100,
        'NU': 100, 'NV': 100, 'NW': 100, 'NX': 100, 'NY': 100,
        'NZ': 100, 'N1': 100, 'N2': 100, 'N3': 100, 'N4': 100,
        'N5': 100
    }
    
    return day_req, night_req, current_staffing

def generate_hourly_demand(day_requirements: Dict[str, int], demand_profile: Dict[str, List[float]]) -> pd.DataFrame:
    """
    Generates hourly demand based on daily requirements and an hourly profile.
    
    Args:
        day_requirements: Daily headcount requirements
        demand_profile: Hourly profile as percentage of daily total by shift type
        
    Returns:
        DataFrame with hourly demand for each day
    """
    days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    hours = list(range(24))
    
    hourly_data = []
    
    for day in days:
        day_demand = day_requirements[day]
        
        for hour in hours:
            # Determine shift type for this hour (day or night)
            shift_type = 'day_shift' if 5 <= hour < 15 else 'night_shift'
            
            # Get the hour index within the shift (0-9 for 10-hour shifts)
            shift_hour_idx = (hour - 5) % 24 if shift_type == 'day_shift' else (hour - 15) % 24
            if shift_hour_idx >= 10:  # Only use first 10 hours for each shift
                continue
                
            # Get the demand profile for this hour
            hour_percentage = demand_profile[shift_type][shift_hour_idx]
            
            # Calculate the demand for this hour
            hour_demand = day_demand * hour_percentage
            
            hourly_data.append({
                'Day': day,
                'Hour': hour,
                'Shift_Type': 'Day' if shift_type == 'day_shift' else 'Night',
                'Demand': hour_demand
            })
    
    return pd.DataFrame(hourly_data)

def create_hourly_coverage(pattern_results: pd.DataFrame, site_schedule: dict) -> pd.DataFrame:
    """
    Creates hourly coverage profile based on staffing pattern results.
    
    Args:
        pattern_results: DataFrame with pattern staffing results
        site_schedule: Dictionary with site schedule information
        
    Returns:
        DataFrame with hourly coverage
    """
    days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    hours = list(range(24))
    
    # Initialize hourly coverage
    coverage_data = []
    
    for _, row in pattern_results.iterrows():
        pattern = row['Pattern']
        employees = row['Employees']
        shift_type = 'day_shift' if row['Shift'] == 'Day' else 'night_shift'
        
        # Extract pattern components
        pattern_code = pattern[:2]  # DA, NB, etc.
        
        # If there's a start time in the pattern (DA5-0700), use it
        # Otherwise use the default start time
        start_time = '0700' if shift_type == 'day_shift' else '1900'
        if '-' in pattern:
            start_time = pattern.split('-')[1]
        
        # Convert start time to hour
        start_hour = int(start_time[:2])
        
        # Determine which days this pattern works
        working_days = [days[i] for i, val in enumerate([row[day] for day in days]) if val == 1]
        
        # Calculate hourly coverage for each working day
        for day in working_days:
            # Use site schedule to determine working periods
            work_periods = site_schedule[shift_type]['work_periods']
            
            # Adjust work periods based on shift start time
            adjusted_work_periods = []
            for period in work_periods:
                period_start = time_to_minutes(period['start'])
                period_end = time_to_minutes(period['end'])
                
                # Convert the custom start time to minutes
                shift_start = time_to_minutes(start_time)
                
                # Calculate the offset from the default period start
                default_period_start = time_to_minutes('0700' if shift_type == 'day_shift' else '1900')
                time_offset = shift_start - default_period_start
                
                # Adjust period start and end times
                adjusted_start = (period_start + time_offset) % (24 * 60)
                adjusted_end = (period_end + time_offset) % (24 * 60)
                
                adjusted_work_periods.append({
                    'start': minutes_to_time(adjusted_start),
                    'end': minutes_to_time(adjusted_end)
                })
            
            # Calculate each working hour based on adjusted periods
            for period in adjusted_work_periods:
                period_start_hour = int(period['start'][:2])
                period_end_hour = int(period['end'][:2])
                
                # Handle periods that cross midnight
                if period_end_hour < period_start_hour:
                    period_end_hour += 24
                
                # Add coverage for each hour in this period
                for hour in range(period_start_hour, period_end_hour + 1):
                    hour_24 = hour % 24  # Convert back to 24-hour format
                    
                    coverage_data.append({
                        'Day': day,
                        'Hour': hour_24,
                        'Pattern': pattern,
                        'Start_Time': start_time,
                        'Employees': employees
                    })
    
    # Convert to DataFrame and aggregate
    coverage_df = pd.DataFrame(coverage_data)
    if not coverage_df.empty:
        coverage_agg = coverage_df.groupby(['Day', 'Hour']).agg({'Employees': 'sum'}).reset_index()
    else:
        # Create empty dataframe with expected structure
        coverage_agg = pd.DataFrame(columns=['Day', 'Hour', 'Employees'])
    
    return coverage_agg

def optimize_shift_timing(pattern_results: pd.DataFrame, hourly_demand: pd.DataFrame, 
                          site_schedule: Dict) -> pd.DataFrame:
    """
    Optimizes the distribution of start times for each pattern based on hourly demand.
    
    Args:
        pattern_results: DataFrame with pattern staffing results from first stage
        hourly_demand: DataFrame with hourly demand by day
        site_schedule: Dictionary with site schedule information
        
    Returns:
        DataFrame with patterns and their optimal start times
    """
    days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    
    # Create a problem for each pattern-day combination
    all_results = []
    
    # Group staff by pattern
    pattern_groups = pattern_results.groupby(['Pattern'])
    
    for pattern, group in pattern_groups:
        # Get pattern info
        pattern_info = group.iloc[0]
        staff_count = pattern_info['Employees']
        shift_type = 'day_shift' if pattern_info['Shift'] == 'Day' else 'night_shift'
        
        # Get valid start times for this shift
        valid_start_times = site_schedule[shift_type]['valid_start_times']
        
        # Determine which days this pattern works
        working_days = []
        for day in days:
            day_value = pattern_info.get(day, 0)
            if day_value > 0:
                working_days.append(day)
        
        # Create optimization model
        model = pulp.LpProblem(f"Shift_Timing_{pattern}", pulp.LpMinimize)
        
        # Create variables for each start time
        start_time_vars = {
            start_time: pulp.LpVariable(
                f"{pattern}_{start_time}", 
                lowBound=0, 
                upBound=staff_count,
                cat='Integer'
            )
            for start_time in valid_start_times
        }
        
        # Constraint: total staff for all start times must equal pattern staff count
        model += pulp.lpSum(start_time_vars.values()) == staff_count
        
        # Calculate coverage for each potential start time
        coverage_by_start = {}
        
        for start_time in valid_start_times:
            # Create a test pattern with this start time
            test_pattern = f"{pattern}-{start_time}"
            test_df = pattern_info.to_frame().T.copy()
            test_df['Pattern'] = test_pattern
            test_df['Employees'] = 1  # Just need relative coverage
            
            # Calculate hourly coverage for this start time
            test_coverage = create_hourly_coverage(test_df, site_schedule)
            
            # Save the coverage profile
            coverage_by_start[start_time] = test_coverage
        
        # Create objective: minimize the gap between demand and coverage
        coverage_gap = pulp.LpVariable("Coverage_Gap", lowBound=0)
        
        # For each hour with demand, calculate the gap
        for day in working_days:
            # Get demand for this day
            day_demand = hourly_demand[hourly_demand['Day'] == day]
            
            for _, demand_row in day_demand.iterrows():
                hour = demand_row['Hour']
                hour_demand = demand_row['Demand']
                
                # Calculate total coverage for this hour from all start times
                hour_coverage = pulp.lpSum(
                    start_time_vars[start_time] * (
                        coverage_by_start[start_time][
                            (coverage_by_start[start_time]['Day'] == day) & 
                            (coverage_by_start[start_time]['Hour'] == hour)
                        ]['Employees'].sum() if not coverage_by_start[start_time].empty else 0
                    )
                    for start_time in valid_start_times
                )
                
                # Gap between coverage and demand
                model += hour_coverage - hour_demand <= coverage_gap
                model += hour_demand - hour_coverage <= coverage_gap
        
        # Set objective to minimize the gap
        model += coverage_gap
        
        # Solve the model
        try:
            status = model.solve(pulp.PULP_CBC_CMD(msg=0))
            
            if status == pulp.LpStatusOptimal or status == pulp.LpStatusFeasible:
                for start_time, var in start_time_vars.items():
                    staff = int(pulp.value(var))
                    if staff > 0:
                        # Create full pattern with start time
                        full_pattern = f"{pattern}-{start_time}"
                        
                        # Add to results
                        result_row = pattern_info.to_dict()
                        result_row['Pattern'] = full_pattern
                        result_row['Start_Time'] = start_time
                        result_row['Employees'] = staff
                        all_results.append(result_row)
            else:
                logger.warning(f"Shift timing optimization for {pattern} failed: {pulp.LpStatus[status]}")
                # Fall back to even distribution
                even_staff = staff_count // len(valid_start_times)
                remaining = staff_count % len(valid_start_times)
                
                for i, start_time in enumerate(valid_start_times):
                    # Distribute staff evenly, with any remainder going to earlier shifts
                    staff = even_staff + (1 if i < remaining else 0)
                    if staff > 0:
                        full_pattern = f"{pattern}-{start_time}"
                        result_row = pattern_info.to_dict()
                        result_row['Pattern'] = full_pattern
                        result_row['Start_Time'] = start_time
                        result_row['Employees'] = staff
                        all_results.append(result_row)
        
        except Exception as e:
            logger.error(f"Error in shift timing optimization for {pattern}: {str(e)}")
            # Fall back to even distribution
            even_staff = staff_count // len(valid_start_times)
            remaining = staff_count % len(valid_start_times)
            
            for i, start_time in enumerate(valid_start_times):
                staff = even_staff + (1 if i < remaining else 0)
                if staff > 0:
                    full_pattern = f"{pattern}-{start_time}"
                    result_row = pattern_info.to_dict()
                    result_row['Pattern'] = full_pattern
                    result_row['Start_Time'] = start_time
                    result_row['Employees'] = staff
                    all_results.append(result_row)
    
    return pd.DataFrame(all_results) if all_results else pd.DataFrame()

def plot_hourly_coverage(hourly_demand: pd.DataFrame, hourly_coverage: pd.DataFrame) -> go.Figure:
    """
    Creates a visualization of hourly demand vs. coverage.
    
    Args:
        hourly_demand: DataFrame with hourly demand
        hourly_coverage: DataFrame with hourly coverage
        
    Returns:
        Plotly figure object
    """
    days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    hours = list(range(24))
    
    fig = make_subplots(
        rows=len(days), 
        cols=1,
        subplot_titles=[f"{day}" for day in days],
        shared_xaxes=True,
        vertical_spacing=0.02
    )
    
    for i, day in enumerate(days):
        day_demand = hourly_demand[hourly_demand['Day'] == day]
        day_coverage = hourly_coverage[hourly_coverage['Day'] == day]
        
        # Create demand bars
        demand_data = []
        for hour in hours:
            hour_demand = day_demand[day_demand['Hour'] == hour]['Demand'].sum() if not day_demand.empty else 0
            demand_data.append(hour_demand)
        
        fig.add_trace(
            go.Bar(
                x=hours,
                y=demand_data,
                name=f"{day} Demand" if i == 0 else None,
                marker_color='indianred',
                opacity=0.7,
                showlegend=(i == 0)
            ),
            row=i+1, col=1
        )
        
        # Create coverage line
        coverage_data = []
        for hour in hours:
            hour_coverage = day_coverage[day_coverage['Hour'] == hour]['Employees'].sum() if not day_coverage.empty else 0
            coverage_data.append(hour_coverage)
        
        fig.add_trace(
            go.Scatter(
                x=hours,
                y=coverage_data,
                name=f"{day} Coverage" if i == 0 else None,
                line=dict(color='royalblue', width=3),
                showlegend=(i == 0)
            ),
            row=i+1, col=1
        )
    
    # Update layout
    fig.update_layout(
        height=1000,
        title_text="Hourly Demand vs. Coverage by Day",
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5
        )
    )
    
    # Update x-axes
    fig.update_xaxes(
        title_text="Hour of Day",
        tickvals=list(range(0, 24, 3)),
        ticktext=[f"{h:02d}:00" for h in range(0, 24, 3)]
    )
    
    # Update y-axes
    fig.update_yaxes(title_text="Employees")
    
    return fig

def main():
    """
    Main function that sets up the Streamlit interface and handles the optimization process.
    """
    global met_df  # Make met_df accessible as a global variable
    
    st.set_page_config(layout="wide", page_title="Staffing Pattern Optimizer", page_icon="📊")
    st.title("Staffing Pattern Optimizer")
    
    # Define days list
    days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    
    # Initialize session state variables if they don't exist
    if 'current_staffing' not in st.session_state:
        st.session_state.current_staffing = {}
    if 'current_cost' not in st.session_state:
        st.session_state.current_cost = 0.0
    if 'current_day_coverage' not in st.session_state:
        st.session_state.current_day_coverage = {day: 0 for day in days}
    if 'current_night_coverage' not in st.session_state:
        st.session_state.current_night_coverage = {day: 0 for day in days}
    if 'met_df' not in st.session_state:
        st.session_state.met_df = pd.DataFrame()
    if 'last_results_df' not in st.session_state:
        st.session_state.last_results_df = pd.DataFrame()
    if 'last_day_staffing' not in st.session_state:
        st.session_state.last_day_staffing = {day: 0 for day in days}
    if 'last_night_staffing' not in st.session_state:
        st.session_state.last_night_staffing = {day: 0 for day in days}
    if 'site_schedule' not in st.session_state:
        st.session_state.site_schedule = DEFAULT_SITE_SCHEDULE
    if 'demand_profile' not in st.session_state:
        st.session_state.demand_profile = DEFAULT_DEMAND_PROFILE
    if 'hourly_demand' not in st.session_state:
        st.session_state.hourly_demand = pd.DataFrame()
    if 'shift_timing_results' not in st.session_state:
        st.session_state.shift_timing_results = pd.DataFrame()
    if 'uploaded_sites' not in st.session_state:
        st.session_state.uploaded_sites = {}
    if 'current_site' not in st.session_state:
        st.session_state.current_site = "Free Form Model"
    
    # Access the global met_df and update it from session state if available
    global met_df
    met_df = st.session_state.met_df
    
    # Initialize visualizations as None
    coverage_fig = None
    met_fig = None
    ctp_fig = None
    hourly_fig = None
    
    try:
        # Data upload section at the top
        st.header("Data Upload")
        
        upload_columns = st.columns(4)
        
        with upload_columns[0]:
            site_schedule_file = st.file_uploader("Upload Site Schedules (CSV)", type="csv", key="site_schedule_upload")
            if site_schedule_file:
                site_schedules = parse_site_schedule_upload(site_schedule_file)
                if site_schedules:
                    for site_name, schedule in site_schedules.items():
                        if 'uploaded_sites' not in st.session_state:
                            st.session_state.uploaded_sites = {}
                        if site_name not in st.session_state.uploaded_sites:
                            st.session_state.uploaded_sites[site_name] = {}
                        st.session_state.uploaded_sites[site_name]['site_schedule'] = schedule
                    st.success(f"Loaded site schedules for {len(site_schedules)} sites")
        
        with upload_columns[1]:
            hourly_demand_file = st.file_uploader("Upload Hourly Demand (CSV)", type="csv", key="hourly_demand_upload")
            if hourly_demand_file:
                demand_profiles = parse_hourly_demand_upload(hourly_demand_file)
                if demand_profiles:
                    for site_name, profile in demand_profiles.items():
                        if 'uploaded_sites' not in st.session_state:
                            st.session_state.uploaded_sites = {}
                        if site_name not in st.session_state.uploaded_sites:
                            st.session_state.uploaded_sites[site_name] = {}
                        st.session_state.uploaded_sites[site_name]['demand_profile'] = profile
                    st.success(f"Loaded demand profiles for {len(demand_profiles)} sites")
        
        with upload_columns[2]:
            current_staffing_file = st.file_uploader("Upload Current Staffing (CSV)", type="csv", key="current_staffing_upload")
            if current_staffing_file:
                site_staffing = parse_current_staffing_upload(current_staffing_file)
                if site_staffing:
                    for site_name, staffing in site_staffing.items():
                        if 'uploaded_sites' not in st.session_state:
                            st.session_state.uploaded_sites = {}
                        if site_name not in st.session_state.uploaded_sites:
                            st.session_state.uploaded_sites[site_name] = {}
                        st.session_state.uploaded_sites[site_name]['current_staffing'] = staffing
                    st.success(f"Loaded current staffing for {len(site_staffing)} sites")
        
        with upload_columns[3]:
            # Generate sample data
            if st.button("Generate Sample Data"):
                site_schedule_csv, hourly_demand_csv, current_staffing_csv = generate_sample_uploads()
                
                st.download_button(
                    label="Download Sample Site Schedule CSV",
                    data=site_schedule_csv,
                    file_name="sample_site_schedule.csv",
                    mime="text/csv"
                )
                
                st.download_button(
                    label="Download Sample Hourly Demand CSV",
                    data=hourly_demand_csv,
                    file_name="sample_hourly_demand.csv",
                    mime="text/csv"
                )
                
                st.download_button(
                    label="Download Sample Current Staffing CSV",
                    data=current_staffing_csv,
                    file_name="sample_current_staffing.csv",
                    mime="text/csv"
                )
                
        # Site selection
        if st.session_state.uploaded_sites:
            st.header("Select Site to Model")
            site_options = ["Free Form Model"] + list(st.session_state.uploaded_sites.keys())
            selected_site = st.selectbox(
                "Select a site to model",
                site_options,
                index=site_options.index(st.session_state.current_site) if st.session_state.current_site in site_options else 0
            )
            
            if selected_site != st.session_state.current_site:
                st.session_state.current_site = selected_site
                
                # Reset state if switching to free form
                if selected_site == "Free Form Model":
                    st.session_state.site_schedule = DEFAULT_SITE_SCHEDULE
                    st.session_state.demand_profile = DEFAULT_DEMAND_PROFILE
                    st.session_state.current_staffing = {}
                    st.session_state.current_day_coverage = {day: 0 for day in days}
                    st.session_state.current_night_coverage = {day: 0 for day in days}
                    st.session_state.hourly_demand = pd.DataFrame()
                    st.session_state.current_cost = 0.0
                    st.rerun()
                
                # Load site-specific data
                else:
                    site_data = st.session_state.uploaded_sites[selected_site]
                    
                    # Load site schedule if available
                    if 'site_schedule' in site_data:
                        st.session_state.site_schedule = site_data['site_schedule']
                    
                    # Load demand profile if available
                    if 'demand_profile' in site_data:
                        st.session_state.current_day_coverage = site_data['demand_profile']['day_requirements']
                        st.session_state.current_night_coverage = site_data['demand_profile']['night_requirements']
                        st.session_state.hourly_demand = site_data['demand_profile']['hourly_demand']
                    
                    # Load current staffing if available
                    if 'current_staffing' in site_data:
                        st.session_state.current_staffing = site_data['current_staffing']
                        
                        # Calculate costs and coverage based on current staffing
                        patterns_df = create_patterns_df()
                        st.session_state.current_cost, day_coverage, night_coverage = calculate_current_costs(
                            patterns_df, st.session_state.current_staffing)
                        
                        if not any(req > 0 for req in st.session_state.current_day_coverage.values()) and not any(req > 0 for req in st.session_state.current_night_coverage.values()):
                            # If no demand profile was uploaded, use the coverage as requirements
                            st.session_state.current_day_coverage = day_coverage
                            st.session_state.current_night_coverage = night_coverage
                    
                    st.rerun()
        
        # Step 1: Load patterns
        patterns_df = create_patterns_df()
        
        # Step 2: Configure costs in sidebar
        st.sidebar.title("Cost Configuration")
        
        # Day shift weekend differentials
        st.sidebar.write("Day Shift Weekend Differentials")
        day_0_weekend = st.sidebar.number_input("0 Weekend Days", min_value=0.0, value=0.0, step=0.05)
        day_1_weekend = st.sidebar.number_input("1 Weekend Day", min_value=0.0, value=0.1, step=0.05)
        day_2_weekend = st.sidebar.number_input("2 Weekend Days", min_value=0.0, value=0.2, step=0.05)
        
        # Night shift weekend differentials
        st.sidebar.write("Night Shift Weekend Differentials")
        night_0_weekend = st.sidebar.number_input("0 Weekend Days (Night)", min_value=0.0, value=0.2, step=0.05)
        night_1_weekend = st.sidebar.number_input("1 Weekend Day (Night)", min_value=0.0, value=0.3, step=0.05)
        night_2_weekend = st.sidebar.number_input("2 Weekend Days (Night)", min_value=0.0, value=0.4, step=0.05)
        night_3_weekend = st.sidebar.number_input("3 Weekend Days (Night)", min_value=0.0, value=0.5, step=0.05)
        
        # Site Schedule Configuration - expandable section
        with st.sidebar.expander("Site Schedule Configuration"):
            # Select configuration mode
            schedule_mode = st.radio(
                "Schedule Configuration Mode",
                ["Use Default", "Custom Schedule"],
                index=0
            )
            
            if schedule_mode == "Use Default":
                st.session_state.site_schedule = DEFAULT_SITE_SCHEDULE
                
                # Display the current schedule for reference
                st.write("Day Shift Schedule:")
                day_times = []
                for period in DEFAULT_SITE_SCHEDULE['day_shift']['work_periods']:
                    day_times.append(f"{period['start']} - {period['end']}")
                st.write(", ".join(day_times))
                
                st.write("Night Shift Schedule:")
                night_times = []
                for period in DEFAULT_SITE_SCHEDULE['night_shift']['work_periods']:
                    night_times.append(f"{period['start']} - {period['end']}")
                st.write(", ".join(night_times))
                
                # Display valid start times
                st.write("Valid Day Shift Start Times:")
                st.write(", ".join(DEFAULT_SITE_SCHEDULE['day_shift']['valid_start_times']))
                
                st.write("Valid Night Shift Start Times:")
                st.write(", ".join(DEFAULT_SITE_SCHEDULE['night_shift']['valid_start_times']))
            else:
                # Custom schedule editor - simplified for usability
                st.write("Day Shift Configuration")
                
                # Valid start times for day shift
                day_start_times = st.text_input(
                    "Valid Day Shift Start Times (comma-separated HHMM format)",
                    value=",".join(st.session_state.site_schedule['day_shift']['valid_start_times'])
                )
                
                # Work periods for day shift
                day_work_periods = st.text_area(
                    "Day Shift Work Periods (one per line, start-end in HHMM format)",
                    value="\n".join([f"{p['start']}-{p['end']}" for p in st.session_state.site_schedule['day_shift']['work_periods']])
                )
                
                st.write("Night Shift Configuration")
                
                # Valid start times for night shift
                night_start_times = st.text_input(
                    "Valid Night Shift Start Times (comma-separated HHMM format)",
                    value=",".join(st.session_state.site_schedule['night_shift']['valid_start_times'])
                )
                
                # Work periods for night shift
                night_work_periods = st.text_area(
                    "Night Shift Work Periods (one per line, start-end in HHMM format)",
                    value="\n".join([f"{p['start']}-{p['end']}" for p in st.session_state.site_schedule['night_shift']['work_periods']])
                )
                
                # Save custom schedule
                if st.button("Save Custom Schedule"):
                    try:
                        # Parse day shift start times
                        day_start_times_list = [t.strip() for t in day_start_times.split(",")]
                        
                        # Parse day shift work periods
                        day_periods_list = []
                        for line in day_work_periods.split("\n"):
                            if "-" in line:
                                start, end = line.strip().split("-")
                                day_periods_list.append({"start": start.strip(), "end": end.strip()})
                        
                        # Parse night shift start times
                        night_start_times_list = [t.strip() for t in night_start_times.split(",")]
                        
                        # Parse night shift work periods
                        night_periods_list = []
                        for line in night_work_periods.split("\n"):
                            if "-" in line:
                                start, end = line.strip().split("-")
                                night_periods_list.append({"start": start.strip(), "end": end.strip()})
                        
                        # Create new site schedule
                        new_schedule = {
                            'day_shift': {
                                'valid_start_times': day_start_times_list,
                                'work_periods': day_periods_list,
                                'paid_breaks': st.session_state.site_schedule['day_shift']['paid_breaks'],
                                'unpaid_breaks': st.session_state.site_schedule['day_shift']['unpaid_breaks'],
                                'shift_length_hours': 10,
                                'unpaid_lunch_hours': 0.5
                            },
                            'night_shift': {
                                'valid_start_times': night_start_times_list,
                                'work_periods': night_periods_list,
                                'paid_breaks': st.session_state.site_schedule['night_shift']['paid_breaks'],
                                'unpaid_breaks': st.session_state.site_schedule['night_shift']['unpaid_breaks'],
                                'shift_length_hours': 10,
                                'unpaid_lunch_hours': 0.5
                            }
                        }
                        
                        # Update session state
                        st.session_state.site_schedule = new_schedule
                        st.success("Custom schedule saved successfully!")
                    except Exception as e:
                        st.error(f"Error saving custom schedule: {str(e)}")
        
        # Demand Profile Configuration - expandable section  
        with st.sidebar.expander("Hourly Demand Profile"):
            # Select demand profile mode
            demand_mode = st.radio(
                "Demand Profile Mode",
                ["Use Default", "Custom Profile"],
                index=0
            )
            
            if demand_mode == "Use Default":
                st.session_state.demand_profile = DEFAULT_DEMAND_PROFILE
                
                # Display the default profile for reference
                st.write("Day Shift Hourly Profile (% of daily total):")
                st.line_chart(pd.DataFrame({
                    'Hour': [f"{(i+5):02d}:00" for i in range(10)],
                    'Demand %': DEFAULT_DEMAND_PROFILE['day_shift']
                }).set_index('Hour'))
                
                st.write("Night Shift Hourly Profile (% of daily total):")
                st.line_chart(pd.DataFrame({
                    'Hour': [f"{((i+15)%24):02d}:00" for i in range(10)],
                    'Demand %': DEFAULT_DEMAND_PROFILE['night_shift']
                }).set_index('Hour'))
            else:
                # Custom demand profile editor
                st.write("Edit Day Shift Hourly Profile (% of daily total)")
                
                # Create sliders for each hour of day shift
                day_profile = []
                for i in range(10):
                    hour = (i + 5) % 24  # Day shift starts at 0500
                    default_value = st.session_state.demand_profile['day_shift'][i]
                    value = st.slider(
                        f"{hour:02d}:00",
                        min_value=0.0,
                        max_value=0.3,
                        value=default_value,
                        step=0.01,
                        key=f"day_profile_{i}"
                    )
                    day_profile.append(value)
                
                st.write("Edit Night Shift Hourly Profile (% of daily total)")
                
                # Create sliders for each hour of night shift
                night_profile = []
                for i in range(10):
                    hour = (i + 15) % 24  # Night shift starts at 1500
                    default_value = st.session_state.demand_profile['night_shift'][i]
                    value = st.slider(
                        f"{hour:02d}:00",
                        min_value=0.0,
                        max_value=0.3,
                        value=default_value,
                        step=0.01,
                        key=f"night_profile_{i}"
                    )
                    night_profile.append(value)
                
                # Save custom demand profile
                if st.button("Save Custom Demand Profile"):
                    # Normalize to ensure sum is 1.0
                    day_total = sum(day_profile)
                    night_total = sum(night_profile)
                    
                    normalized_day = [v / day_total for v in day_profile]
                    normalized_night = [v / night_total for v in night_profile]
                    
                    # Update session state
                    st.session_state.demand_profile = {
                        'day_shift': normalized_day,
                        'night_shift': normalized_night
                    }
                    
                    st.success("Custom demand profile saved successfully!")
        
        # TPH Configuration - expandable section
        with st.sidebar.expander("Throughput Per Hour (TPH) Configuration"):
            # Default TPH values
            if 'tph_values' not in st.session_state:
                st.session_state.tph_values = {
                    'day_shift': 10.0,
                    'night_shift': 10.0
                }
            
            # TPH editor
            st.write("Set TPH values for headcount calculation (volume ÷ TPH = staff needed)")
            
            # Simple TPH mode with one value per shift
            simple_tph_mode = st.checkbox("Use simple TPH mode (one value per shift)", value=True)
            
            if simple_tph_mode:
                day_tph = st.number_input(
                    "Day Shift TPH",
                    min_value=1.0,
                    max_value=100.0,
                    value=st.session_state.tph_values.get('day_shift', 10.0),
                    step=0.5
                )
                
                night_tph = st.number_input(
                    "Night Shift TPH",
                    min_value=1.0,
                    max_value=100.0,
                    value=st.session_state.tph_values.get('night_shift', 10.0),
                    step=0.5
                )
                
                # Update session state
                st.session_state.tph_values = {
                    'day_shift': day_tph,
                    'night_shift': night_tph
                }
            else:
                # Advanced TPH mode with hour-by-hour values
                st.write("Day Shift TPH by Hour")
                day_tph_values = {}
                
                # Create a 2-column layout for the TPH inputs
                tph_cols = st.columns(2)
                
                # Day shift TPH inputs
                for i in range(10):
                    hour = (i + 5) % 24  # Day shift starts at 0500
                    hour_key = f"hour_{hour}"
                    
                    # Get the current TPH value for this hour
                    current_tph = st.session_state.tph_values.get(hour_key, 10.0)
                    
                    # Create the number input in the appropriate column
                    with tph_cols[i % 2]:
                        day_tph_values[hour_key] = st.number_input(
                            f"{hour:02d}:00",
                            min_value=1.0,
                            max_value=100.0,
                            value=current_tph,
                            step=0.5,
                            key=f"day_tph_{hour}"
                        )
                
                st.write("Night Shift TPH by Hour")
                night_tph_values = {}
                
                # Night shift TPH inputs
                for i in range(10):
                    hour = (i + 15) % 24  # Night shift starts at 1500
                    hour_key = f"hour_{hour}"
                    
                    # Get the current TPH value for this hour
                    current_tph = st.session_state.tph_values.get(hour_key, 10.0)
                    
                    # Create the number input in the appropriate column
                    with tph_cols[i % 2]:
                        night_tph_values[hour_key] = st.number_input(
                            f"{hour:02d}:00",
                            min_value=1.0,
                            max_value=100.0,
                            value=current_tph,
                            step=0.5,
                            key=f"night_tph_{hour}"
                        )
                
                # Update session state with all TPH values
                tph_values = {'day_shift': 10.0, 'night_shift': 10.0}  # Default values
                tph_values.update(day_tph_values)
                tph_values.update(night_tph_values)
                st.session_state.tph_values = tph_values
            
            # Information about TPH usage
            st.info("TPH values are used when manually entering volume data or when uploading volume/TPH data. For uploaded data, TPH values in the upload take precedence over these settings.")
        
        # Update cost multipliers
        patterns_df['Cost_Multiplier'] = patterns_df.apply(lambda row:
            (1.0 + {
                '0': day_0_weekend if row['Shift'] == 'Day' else night_0_weekend,
                '1': day_1_weekend if row['Shift'] == 'Day' else night_1_weekend,
                '2': day_2_weekend if row['Shift'] == 'Day' else night_2_weekend,
                '3': night_3_weekend if row['Shift'] == 'Night' else 0.0
            }[row['Weekend_Category']]),
            axis=1)
        
        # Test loading button at top level (before all other content)
        if st.button("Load Test Values"):
            day_req, night_req, current_staff = load_test_values()
            st.session_state.current_staffing = current_staff
            st.session_state.current_day_coverage = day_req
            st.session_state.current_night_coverage = night_req
            # Calculate costs based on the test staffing
            st.session_state.current_cost, _, _ = calculate_current_costs(
                patterns_df, st.session_state.current_staffing)
            st.success("Test values loaded successfully!")
            # Force a refresh
            st.rerun()
        
        # Volume-based staffing section
        st.header("1. Volume & Staffing Requirements")
        
        volume_mode = st.radio(
            "Input Mode",
            ["Manual Coverage Entry", "Volume-Based Calculation"],
            index=0
        )
        
        if volume_mode == "Volume-Based Calculation":
            # Manual volume entry
            st.subheader("Enter Daily Volume")
            
            volume_cols = st.columns(7)
            day_volumes = {}
            for i, day in enumerate(days):
                with volume_cols[i]:
                    day_volumes[day] = st.number_input(
                        f"{day} Volume",
                        min_value=0,
                        value=1000,
                        step=100,
                        key=f"volume_{day}"
                    )
            
            # Get TPH values from session state
            day_tph = st.session_state.tph_values.get('day_shift', 10.0)
            night_tph = st.session_state.tph_values.get('night_shift', 10.0)
            
            # Use a slider to split volume between day and night shifts
            day_night_split = st.slider(
                "Day/Night Volume Split (%)",
                min_value=0,
                max_value=100,
                value=70,
                step=5,
                help="Percentage of volume processed during day shift"
            )
            
            # Calculate day and night requirements based on volume and TPH
            day_req = {}
            night_req = {}
            
            # Create an hourly breakdown of volume and staff requirements
            hourly_demand_data = []
            
            for day in days:
                # Split volume between day and night shifts
                day_volume = day_volumes[day] * (day_night_split / 100)
                night_volume = day_volumes[day] * ((100 - day_night_split) / 100)
                
                # Calculate required staff at daily level (volume / tph)
                day_req[day] = day_volume / day_tph if day_tph > 0 else day_volume
                night_req[day] = night_volume / night_tph if night_tph > 0 else night_volume
                
                # Calculate hourly volume distribution based on demand profile
                for i, hour_pct in enumerate(st.session_state.demand_profile['day_shift']):
                    hour = (i + 5) % 24  # Day shift starts at 0500
                    hour_volume = day_volume * hour_pct
                    
                    # If using advanced TPH mode, get the hour-specific TPH
                    if 'hour_{}'.format(hour) in st.session_state.tph_values and not simple_tph_mode:
                        hour_tph = st.session_state.tph_values['hour_{}'.format(hour)]
                    else:
                        hour_tph = day_tph
                    
                    # Calculate staff needed for this hour
                    hour_staff = hour_volume / hour_tph if hour_tph > 0 else hour_volume
                    
                    # Add to hourly demand data
                    hourly_demand_data.append({
                        'Day': day,
                        'Hour': hour,
                        'Shift_Type': 'Day',
                        'Volume': hour_volume,
                        'TPH': hour_tph,
                        'Staff_Needed': hour_staff
                    })
                
                # Calculate hourly volume distribution for night shift
                for i, hour_pct in enumerate(st.session_state.demand_profile['night_shift']):
                    hour = (i + 15) % 24  # Night shift starts at 1500
                    hour_volume = night_volume * hour_pct
                    
                    # If using advanced TPH mode, get the hour-specific TPH
                    if 'hour_{}'.format(hour) in st.session_state.tph_values and not simple_tph_mode:
                        hour_tph = st.session_state.tph_values['hour_{}'.format(hour)]
                    else:
                        hour_tph = night_tph
                    
                    # Calculate staff needed for this hour
                    hour_staff = hour_volume / hour_tph if hour_tph > 0 else hour_volume
                    
                    # Add to hourly demand data
                    hourly_demand_data.append({
                        'Day': day,
                        'Hour': hour,
                        'Shift_Type': 'Night',
                        'Volume': hour_volume,
                        'TPH': hour_tph,
                        'Staff_Needed': hour_staff
                    })
            
            # Create the hourly demand DataFrame
            hourly_demand_df = pd.DataFrame(hourly_demand_data)
            st.session_state.hourly_demand = hourly_demand_df
            
            # Update session state with calculated requirements
            st.session_state.current_day_coverage = day_req
            st.session_state.current_night_coverage = night_req
            
            # Display calculated requirements
            st.subheader("Calculated Staffing Requirements")
            
            # Daily requirements table
            coverage_data = []
            for day in days:
                coverage_data.append({
                    'Day': day,
                    'Day Volume': round(day_volumes[day] * (day_night_split / 100), 1),
                    'Day Staff Required': round(day_req[day], 1),
                    'Night Volume': round(day_volumes[day] * ((100 - day_night_split) / 100), 1),
                    'Night Staff Required': round(night_req[day], 1),
                    'Total Volume': day_volumes[day],
                    'Total Staff Required': round(day_req[day] + night_req[day], 1)
                })
            
            st.write("Daily Volume & Staff Requirements:")
            st.dataframe(pd.DataFrame(coverage_data), 
                        hide_index=True,
                        height=300,
                        width=1000)
            
            # Hourly breakdown visualization
            st.write("Hourly Breakdown:")
            
            # Create tabs for different days to show hourly breakdown
            day_tabs = st.tabs(days)
            
            for i, day in enumerate(days):
                with day_tabs[i]:
                    day_data = hourly_demand_df[hourly_demand_df['Day'] == day]
                    
                    # Create columns for layout
                    col1, col2 = st.columns([3, 2])
                    
                    with col1:
                        # Create a grouped bar chart for volume and staff by hour
                        fig = go.Figure()
                        
                        # Add volume bars
                        fig.add_trace(go.Bar(
                            x=day_data['Hour'],
                            y=day_data['Volume'],
                            name='Volume',
                            marker_color='lightblue'
                        ))
                        
                        # Add staff needed line
                        fig.add_trace(go.Scatter(
                            x=day_data['Hour'],
                            y=day_data['Staff_Needed'],
                            name='Staff Needed',
                            mode='lines+markers',
                            marker=dict(size=8),
                            line=dict(width=3, color='red')
                        ))
                        
                        # Add TPH line on secondary y-axis
                        fig.add_trace(go.Scatter(
                            x=day_data['Hour'],
                            y=day_data['TPH'],
                            name='TPH',
                            mode='lines+markers',
                            marker=dict(size=8),
                            line=dict(width=2, color='green', dash='dot'),
                            yaxis='y2'
                        ))
                        
                        # Update layout
                        fig.update_layout(
                            title=f'Hourly Volume, Staff, and TPH for {day}',
                            xaxis=dict(
                                title='Hour of Day',
                                tickmode='array',
                                tickvals=list(range(24)),
                                ticktext=[f'{h:02d}:00' for h in range(24)]
                            ),
                            yaxis=dict(title='Volume / Staff'),
                            yaxis2=dict(
                                title='TPH',
                                overlaying='y',
                                side='right'
                            ),
                            legend=dict(
                                orientation='h',
                                yanchor='bottom',
                                y=1.02,
                                xanchor='center',
                                x=0.5
                            ),
                            height=500
                        )
                        
                        st.plotly_chart(fig, use_container_width=True)
                    
                    with col2:
                        # Show the hourly data in a table
                        st.dataframe(
                            day_data[['Hour', 'Shift_Type', 'Volume', 'TPH', 'Staff_Needed']],
                            hide_index=True,
                            height=500
                        )
        else:
            # Direct entry of staffing requirements
            st.subheader("Enter Daily Staffing Requirements")
            
            day_cols = st.columns(7)
            night_cols = st.columns(7)
            
            st.write("Day Shift Requirements:")
            day_req = {}
            for i, day in enumerate(days):
                with day_cols[i]:
                    day_req[day] = st.number_input(
                        f"{day}",
                        min_value=0,
                        value=st.session_state.current_day_coverage.get(day, 0),
                        step=1,
                        key=f"day_req_{day}"
                    )
            
            st.write("Night Shift Requirements:")
            night_req = {}
            for i, day in enumerate(days):
                with night_cols[i]:
                    night_req[day] = st.number_input(
                        f"{day}",
                        min_value=0,
                        value=st.session_state.current_night_coverage.get(day, 0),
                        step=1,
                        key=f"night_req_{day}"
                    )
            
            # Update session state with manual requirements
            st.session_state.current_day_coverage = day_req
            st.session_state.current_night_coverage = night_req
        
        # Step 3: Input current staffing
        st.header("2. Current Staffing Input")
        
        # Get unique patterns
        unique_patterns = patterns_df['Pattern'].unique()
        day_patterns = [p for p in unique_patterns if p.startswith('D')]
        night_patterns = [p for p in unique_patterns if p.startswith('N')]
        
        # Create tabs for day and night patterns
        pattern_tabs = st.tabs(["Day Shift Patterns", "Night Shift Patterns"])
        
        with pattern_tabs[0]:
            num_cols = 5
            day_cols = st.columns(num_cols)
            for i, pattern in enumerate(day_patterns):
                with day_cols[i % num_cols]:
                    st.session_state.current_staffing[pattern] = st.number_input(
                        f"{pattern}",
                        min_value=0,
                        value=st.session_state.current_staffing.get(pattern, 0),
                        step=1,
                        key=f"current_{pattern}"
                    )
        
        with pattern_tabs[1]:
            night_cols = st.columns(num_cols)
            for i, pattern in enumerate(night_patterns):
                with night_cols[i % num_cols]:
                    st.session_state.current_staffing[pattern] = st.number_input(
                        f"{pattern}",
                        min_value=0,
                        value=st.session_state.current_staffing.get(pattern, 0),
                        step=1,
                        key=f"current_{pattern}"
                    )
        
        # Step 4: Calculate current costs and coverage
        if any(count > 0 for count in st.session_state.current_staffing.values()):
            st.header("3. Current Coverage & Costs")
            
            # Calculate current costs and coverage
            st.session_state.current_cost, st.session_state.current_day_coverage, st.session_state.current_night_coverage = calculate_current_costs(
                patterns_df, st.session_state.current_staffing)
            
            # Display current coverage
            coverage_data = []
            for day in days:
                coverage_data.append({
                    'Day': day,
                    'Day Coverage': st.session_state.current_day_coverage[day],
                    'Night Coverage': st.session_state.current_night_coverage[day]
                })
            st.dataframe(pd.DataFrame(coverage_data), hide_index=True)
            
            st.metric("Current Weekly SD Cost", f"${st.session_state.current_cost:.1f}")
            
            # Step 5: Optimization
            st.header("4. Optimization")
            
            # Pattern selection
            st.subheader("Select Patterns for Optimization")
            filter_type = st.radio(
                "Pattern Type",
                ["All patterns", "4-day patterns", "5-day patterns", "Custom selection"]
            )
            
            available_patterns = filter_patterns(patterns_df, filter_type)
            
            if filter_type == "Custom selection":
                shift_type = st.radio(
                    "Shift Type",
                    ["All", "Day", "Night"]
                )
                if shift_type != "All":
                    available_patterns = [p for p in available_patterns 
                                        if patterns_df[patterns_df['Pattern'] == p]['Shift'].iloc[0] == shift_type]
                
                selected_patterns = st.multiselect(
                    "Select patterns:",
                    available_patterns,
                    default=available_patterns[:5]
                )
            else:
                selected_patterns = available_patterns
            
            optimize_cost = st.checkbox("Optimize for Cost", value=True)
            include_met = st.checkbox("Include MET Optimization", value=True)
            include_shift_timing = st.checkbox("Include Shift Timing Optimization", value=True)
            
            # Maximum overstaffing slider
            max_overstaffing = st.slider(
                "Maximum Overstaffing (%)",
                min_value=0,
                max_value=50,
                value=15,
                step=5,
                help="Maximum percentage by which staffing can exceed requirements"
            ) / 100.0  # Convert to decimal
            
            if st.button("Run Optimization"):
                if not selected_patterns:
                    st.error("Please select at least one pattern.")
                    return
                
                try:
                    # Use current coverage as requirements for optimization
                    day_req = st.session_state.current_day_coverage.copy()
                    night_req = st.session_state.current_night_coverage.copy()
                    
                    # Validate requirements before optimization
                    if not any(req > 0 for req in day_req.values()) and not any(req > 0 for req in night_req.values()):
                        st.error("Current coverage is zero for all days. Please enter current staffing or load test values.")
                        return
                    
                    # Run optimization
                    results_df, day_staffing, night_staffing = optimize_staffing(
                        patterns_df, selected_patterns, day_req, night_req, optimize_cost, max_overstaffing
                    )
                    
                    # Store results in session state
                    st.session_state.last_results_df = results_df
                    st.session_state.last_day_staffing = day_staffing
                    st.session_state.last_night_staffing = night_staffing
                    
                    if not results_df.empty:
                        # Calculate optimized costs
                        optimized_cost = calculate_weekly_sd_costs(results_df)['Weekly_SD_Cost'].sum()
                        
                        # Run MET optimization if selected
                        if include_met:
                            # Get day shift patterns
                            day_patterns = results_df[results_df['Shift'] == 'Day']
                            if not day_patterns.empty:
                                day_pattern_dict = day_patterns.set_index('Base_Pattern')['Employees'].to_dict()
                                day_met_df = optimize_met_distribution(day_pattern_dict, 'Day', day_req)
                            else:
                                day_met_df = pd.DataFrame()
                            
                            # Get night shift patterns
                            night_patterns = results_df[results_df['Shift'] == 'Night']
                            if not night_patterns.empty:
                                night_pattern_dict = night_patterns.set_index('Base_Pattern')['Employees'].to_dict()
                                night_met_df = optimize_met_distribution(night_pattern_dict, 'Night', night_req)
                            else:
                                night_met_df = pd.DataFrame()
                            
                            # Combine MET results
                            if not day_met_df.empty or not night_met_df.empty:
                                met_df = pd.concat([day_met_df, night_met_df], ignore_index=True)
                                st.session_state.met_df = met_df
                        
                        # Run shift timing optimization if selected
                        if include_shift_timing:
                            # Generate hourly demand profile
                            st.session_state.hourly_demand = generate_hourly_demand(
                                day_req, st.session_state.demand_profile
                            )
                            
                            # Run shift timing optimization
                            shift_timing_results = optimize_shift_timing(
                                results_df, 
                                st.session_state.hourly_demand,
                                st.session_state.site_schedule
                            )
                            
                            # Store results in session state
                            st.session_state.shift_timing_results = shift_timing_results
                            
                            # Create hourly coverage profile
                            hourly_coverage = create_hourly_coverage(
                                shift_timing_results, 
                                st.session_state.site_schedule
                            )
                        else:
                            st.session_state.shift_timing_results = pd.DataFrame()
                        
                        # Display comparison
                        st.header("5. Results Comparison")
                        
                        cost_cols = st.columns(2)
                        
                        with cost_cols[0]:
                            # Cost comparison
                            st.subheader("Cost Comparison")
                            st.metric("Current Weekly SD Cost", f"${st.session_state.current_cost:.1f}")
                            st.metric("Optimized Weekly SD Cost", f"${optimized_cost:.1f}")
                            savings = st.session_state.current_cost - optimized_cost
                            annual_savings = savings * 52  # 52 weeks in a year
                            st.metric("Weekly Savings", f"${savings:.1f}", 
                                    delta=f"{((savings/st.session_state.current_cost)*100):.1f}%")
                            st.metric("Annual Savings", f"${annual_savings:.1f}",
                                    delta=f"{((annual_savings/(st.session_state.current_cost*52))*100):.1f}%")
                        
                        with cost_cols[1]:
                            # Display optimized pattern distribution
                            st.subheader("Optimized Pattern Distribution")
                            st.dataframe(results_df[['Pattern', 'Shift', 'Employees']], 
                                        hide_index=True,
                                        height=400,
                                        width=600)
                        
                        # Display coverage comparison
                        st.subheader("Coverage Comparison")
                        coverage_comparison = []
                        for day in days:
                            coverage_comparison.append({
                                'Day': day,
                                'Current Day': st.session_state.current_day_coverage[day],
                                'Optimized Day': day_staffing[day],
                                'Current Night': st.session_state.current_night_coverage[day],
                                'Optimized Night': night_staffing[day]
                            })
                        st.dataframe(pd.DataFrame(coverage_comparison), 
                                   hide_index=True,
                                   height=300,
                                   width=800)
                        
                        # Display visualizations
                        st.header("6. Visualizations")
                        
                        # Main tabs for different visualizations
                        viz_tabs = st.tabs(["Coverage", "MET Distribution", "CTP Targets", "Hourly Coverage", "Summary Tables"])
                        
                        with viz_tabs[0]:
                            # Create the coverage visualization
                            coverage_fig = plot_coverage(
                                day_staffing, night_staffing, 
                                day_req, night_req,
                                st.session_state.met_df
                            )
                            
                            if coverage_fig is not None:
                                st.plotly_chart(coverage_fig, use_container_width=True)
                        
                        with viz_tabs[1]:
                            # MET distribution if available
                            if not st.session_state.met_df.empty:
                                met_fig = plot_met_distribution(st.session_state.met_df)
                                if met_fig is not None:
                                    st.plotly_chart(met_fig, use_container_width=True)
                                else:
                                    st.info("No MET distribution data available.")
                            else:
                                st.info("No MET assignments available. Enable MET Optimization in the options.")
                        
                        with viz_tabs[2]:
                            # CTP targets
                            if not st.session_state.met_df.empty:
                                ctp_fig = create_ctp_targets_chart(results_df, st.session_state.met_df)
                                if ctp_fig is not None:
                                    st.plotly_chart(ctp_fig, use_container_width=True)
                                else:
                                    st.info("No CTP targets data available.")
                            else:
                                st.info("No MET assignments available. Enable MET Optimization in the options.")
                        
                        with viz_tabs[3]:
                            # Hourly Coverage - only if shift timing optimization was done
                            if not st.session_state.shift_timing_results.empty:
                                st.subheader("Shift Timing Results")
                                
                                # Show shift timing distribution
                                st.dataframe(
                                    st.session_state.shift_timing_results[['Pattern', 'Start_Time', 'Employees']],
                                    hide_index=True,
                                    height=400,
                                    width=600
                                )
                                
                                # Calculate hourly coverage
                                hourly_coverage = create_hourly_coverage(
                                    st.session_state.shift_timing_results,
                                    st.session_state.site_schedule
                                )
                                
                                # Create visualizations
                                st.subheader("Hourly Volume & Staffing")
                                
                                if not st.session_state.hourly_demand.empty:
                                    # Create tabs for different days
                                    hour_tabs = st.tabs(days)
                                    
                                    for i, day in enumerate(days):
                                        with hour_tabs[i]:
                                            # Get day-specific data
                                            day_demand = st.session_state.hourly_demand[st.session_state.hourly_demand['Day'] == day]
                                            day_coverage = hourly_coverage[hourly_coverage['Day'] == day]
                                            
                                            # Create hourly comparison chart
                                            fig = go.Figure()
                                            
                                            # Add volume bars (if available)
                                            if 'Volume' in day_demand.columns:
                                                fig.add_trace(go.Bar(
                                                    x=day_demand['Hour'],
                                                    y=day_demand['Volume'],
                                                    name='Volume',
                                                    marker_color='lightblue',
                                                    opacity=0.5
                                                ))
                                                
                                                # Add volume goal as a line
                                                fig.add_trace(go.Scatter(
                                                    x=day_demand['Hour'],
                                                    y=day_demand['Volume'],
                                                    name='Volume Goal',
                                                    mode='lines',
                                                    line=dict(color='blue', width=2, dash='dot')
                                                ))
                                            
                                            # Add staff needed line (if available)
                                            if 'Staff_Needed' in day_demand.columns:
                                                fig.add_trace(go.Scatter(
                                                    x=day_demand['Hour'],
                                                    y=day_demand['Staff_Needed'],
                                                    name='Staff Needed',
                                                    mode='lines',
                                                    line=dict(width=3, color='red', dash='dot')
                                                ))
                                            elif 'Demand' in day_demand.columns:
                                                fig.add_trace(go.Scatter(
                                                    x=day_demand['Hour'],
                                                    y=day_demand['Demand'],
                                                    name='Staff Needed',
                                                    mode='lines',
                                                    line=dict(width=3, color='red', dash='dot')
                                                ))
                                            
                                            # Add actual coverage line
                                            fig.add_trace(go.Scatter(
                                                x=day_coverage['Hour'],
                                                y=day_coverage['Employees'],
                                                name='Actual Coverage',
                                                mode='lines+markers',
                                                marker=dict(size=8),
                                                line=dict(width=3, color='green')
                                            ))
                                            
                                            # Add TPH line on secondary y-axis if available
                                            if 'TPH' in day_demand.columns:
                                                fig.add_trace(go.Scatter(
                                                    x=day_demand['Hour'],
                                                    y=day_demand['TPH'],
                                                    name='TPH',
                                                    mode='lines',
                                                    line=dict(width=2, color='purple', dash='dash'),
                                                    yaxis='y2'
                                                ))
                                            
                                            # Update layout
                                            fig.update_layout(
                                                title=f'Hourly Demand vs. Coverage for {day}',
                                                xaxis=dict(
                                                    title='Hour of Day',
                                                    tickmode='array',
                                                    tickvals=list(range(24)),
                                                    ticktext=[f'{h:02d}:00' for h in range(24)]
                                                ),
                                                yaxis=dict(title='Volume / Staff'),
                                                yaxis2=dict(
                                                    title='TPH',
                                                    overlaying='y',
                                                    side='right',
                                                    showgrid=False
                                                ) if 'TPH' in day_demand.columns else None,
                                                legend=dict(
                                                    orientation='h',
                                                    yanchor='bottom',
                                                    y=1.02,
                                                    xanchor='center',
                                                    x=0.5
                                                ),
                                                height=800,
                                                width=1200
                                            )
                                            
                                            st.plotly_chart(fig, use_container_width=True)
                                            
                                            # Show the hourly data in a table
                                            col1, col2 = st.columns(2)
                                            
                                            with col1:
                                                st.write("Hourly Demand & Goals:")
                                                
                                                # Create a more informative demand table
                                                if 'Volume' in day_demand.columns and 'Staff_Needed' in day_demand.columns:
                                                    demand_display = day_demand[['Hour', 'Shift_Type', 'Volume', 'TPH', 'Staff_Needed']].copy()
                                                    demand_display['Hour'] = demand_display['Hour'].apply(lambda x: f"{x:02d}:00")
                                                    demand_display.columns = ['Hour', 'Shift Type', 'Volume Goal', 'TPH', 'Staff Needed']
                                                else:
                                                    demand_display = day_demand
                                                
                                                st.dataframe(
                                                    demand_display,
                                                    hide_index=True,
                                                    height=400,
                                                    width=600
                                                )
                                            
                                            with col2:
                                                st.write("Hourly Coverage:")
                                                
                                                # Create a more informative coverage table
                                                coverage_display = day_coverage.copy()
                                                if not coverage_display.empty:
                                                    coverage_display['Hour'] = coverage_display['Hour'].apply(lambda x: f"{x:02d}:00")
                                                    
                                                    # If we have demand data, add staff needed for comparison
                                                    if 'Staff_Needed' in day_demand.columns:
                                                        hour_to_staff = day_demand.set_index('Hour')['Staff_Needed'].to_dict()
                                                        coverage_display['Staff Needed'] = coverage_display['Hour'].apply(
                                                            lambda h: hour_to_staff.get(int(h.split(':')[0]), 0)
                                                        )
                                                        coverage_display['Difference'] = coverage_display['Employees'] - coverage_display['Staff Needed']
                                                
                                                st.dataframe(
                                                    coverage_display,
                                                    hide_index=True, 
                                                    height=400,
                                                    width=600
                                                )
                                else:
                                    # Simpler visualization without hourly demand data
                                    hourly_fig = plot_hourly_coverage(
                                        pd.DataFrame(), # Empty demand 
                                        hourly_coverage
                                    )
                                    if hourly_fig is not None:
                                        st.plotly_chart(hourly_fig, use_container_width=True)
                            else:
                                st.info("No shift timing results available. Enable Shift Timing Optimization in the options.")
                        
                        with viz_tabs[4]:
                            # Summary tables
                            if not st.session_state.met_df.empty:
                                staffing_summary, pattern_summary, met_summary, total_weekly_sd = create_summary_tables(
                                    results_df, day_staffing, night_staffing, 
                                    day_req, night_req, st.session_state.met_df
                                )
                                
                                st.subheader("Daily Staffing Summary")
                                st.dataframe(staffing_summary, 
                                           hide_index=True,
                                           height=300,
                                           width=1000)
                                
                                st.subheader("Pattern Distribution Summary")
                                st.dataframe(pattern_summary, 
                                           hide_index=True,
                                           height=400,
                                           width=800)
                                
                                st.subheader("MET Distribution By Pattern and Day")
                                st.dataframe(met_summary, 
                                           hide_index=True,
                                           height=400,
                                           width=1000)
                                
                                st.metric("Total Weekly SD Cost", f"${total_weekly_sd:.1f}")
                    else:
                        st.error("No feasible solution found with current constraints.")
                except Exception as e:
                    st.error(f"An error occurred during optimization: {str(e)}")
                    logger.error(f"Optimization error: {str(e)}")
            
            # Display existing results if available
            elif not st.session_state.last_results_df.empty:
                st.header("Previous Optimization Results")
                
                results_df = st.session_state.last_results_df
                day_staffing = st.session_state.last_day_staffing
                night_staffing = st.session_state.last_night_staffing
                day_req = st.session_state.current_day_coverage
                night_req = st.session_state.current_night_coverage
                
                # Calculate optimized costs
                optimized_cost = calculate_weekly_sd_costs(results_df)['Weekly_SD_Cost'].sum()
                
                # Display comparison
                st.subheader("Results Comparison")
                
                cost_cols = st.columns(2)
                
                with cost_cols[0]:
                    # Cost comparison
                    st.subheader("Cost Comparison")
                    st.metric("Current Weekly SD Cost", f"${st.session_state.current_cost:.1f}")
                    st.metric("Optimized Weekly SD Cost", f"${optimized_cost:.1f}")
                    savings = st.session_state.current_cost - optimized_cost
                    annual_savings = savings * 52  # 52 weeks in a year
                    st.metric("Weekly Savings", f"${savings:.1f}", 
                            delta=f"{((savings/st.session_state.current_cost)*100):.1f}%")
                    st.metric("Annual Savings", f"${annual_savings:.1f}",
                            delta=f"{((annual_savings/(st.session_state.current_cost*52))*100):.1f}%")
                
                with cost_cols[1]:
                    # Display optimized pattern distribution
                    st.subheader("Optimized Pattern Distribution")
                    st.dataframe(results_df[['Pattern', 'Shift', 'Employees']], 
                                hide_index=True,
                                height=400,
                                width=600)
                
                # Display coverage comparison
                st.subheader("Coverage Comparison")
                coverage_comparison = []
                for day in days:
                    coverage_comparison.append({
                        'Day': day,
                        'Current Day': st.session_state.current_day_coverage[day],
                        'Optimized Day': day_staffing[day],
                        'Current Night': st.session_state.current_night_coverage[day],
                        'Optimized Night': night_staffing[day]
                    })
                st.dataframe(pd.DataFrame(coverage_comparison), 
                                   hide_index=True,
                                   height=300,
                                   width=800)
                
                # Display visualizations
                st.header("Visualizations")
                
                # Main tabs for different visualizations
                viz_tabs = st.tabs(["Coverage", "MET Distribution", "CTP Targets", "Hourly Coverage", "Summary Tables"])
                
                with viz_tabs[0]:
                    # Create the coverage visualization
                    coverage_fig = plot_coverage(
                        day_staffing, night_staffing, 
                        day_req, night_req,
                        st.session_state.met_df
                    )
                    
                    if coverage_fig is not None:
                        st.plotly_chart(coverage_fig, use_container_width=True)
                
                with viz_tabs[1]:
                    # MET distribution if available
                    if not st.session_state.met_df.empty:
                        met_fig = plot_met_distribution(st.session_state.met_df)
                        if met_fig is not None:
                            st.plotly_chart(met_fig, use_container_width=True)
                        else:
                            st.info("No MET distribution data available.")
                    else:
                        st.info("No MET assignments available. Enable MET Optimization in the options.")
                
                with viz_tabs[2]:
                    # CTP targets
                    if not st.session_state.met_df.empty:
                        ctp_fig = create_ctp_targets_chart(results_df, st.session_state.met_df)
                        if ctp_fig is not None:
                            st.plotly_chart(ctp_fig, use_container_width=True)
                        else:
                            st.info("No CTP targets data available.")
                    else:
                        st.info("No MET assignments available. Enable MET Optimization in the options.")
                
                with viz_tabs[3]:
                    # Hourly Coverage - only if shift timing optimization was done
                    if not st.session_state.shift_timing_results.empty:
                        st.subheader("Shift Timing Results")
                        
                        # Show shift timing distribution
                        st.dataframe(
                            st.session_state.shift_timing_results[['Pattern', 'Start_Time', 'Employees']],
                            hide_index=True,
                            height=400,
                            width=600
                        )
                        
                        # Calculate hourly coverage
                        hourly_coverage = create_hourly_coverage(
                            st.session_state.shift_timing_results,
                            st.session_state.site_schedule
                        )
                        
                        # Create visualizations
                        st.subheader("Hourly Volume & Staffing")
                        
                        if not st.session_state.hourly_demand.empty:
                            # Create tabs for different days
                            hour_tabs = st.tabs(days)
                            
                            for i, day in enumerate(days):
                                with hour_tabs[i]:
                                    # Get day-specific data
                                    day_demand = st.session_state.hourly_demand[st.session_state.hourly_demand['Day'] == day]
                                    day_coverage = hourly_coverage[hourly_coverage['Day'] == day]
                                    
                                    # Create hourly comparison chart
                                    fig = go.Figure()
                                    
                                    # Add volume bars (if available)
                                    if 'Volume' in day_demand.columns:
                                        fig.add_trace(go.Bar(
                                            x=day_demand['Hour'],
                                            y=day_demand['Volume'],
                                            name='Volume',
                                            marker_color='lightblue',
                                            opacity=0.5
                                        ))
                                        
                                        # Add volume goal as a line
                                        fig.add_trace(go.Scatter(
                                            x=day_demand['Hour'],
                                            y=day_demand['Volume'],
                                            name='Volume Goal',
                                            mode='lines',
                                            line=dict(color='blue', width=2, dash='dot')
                                        ))
                                    
                                    # Add staff needed line (if available)
                                    if 'Staff_Needed' in day_demand.columns:
                                        fig.add_trace(go.Scatter(
                                            x=day_demand['Hour'],
                                            y=day_demand['Staff_Needed'],
                                            name='Staff Needed',
                                            mode='lines',
                                            line=dict(width=3, color='red', dash='dot')
                                        ))
                                    elif 'Demand' in day_demand.columns:
                                        fig.add_trace(go.Scatter(
                                            x=day_demand['Hour'],
                                            y=day_demand['Demand'],
                                            name='Staff Needed',
                                            mode='lines',
                                            line=dict(width=3, color='red', dash='dot')
                                        ))
                                    
                                    # Add actual coverage line
                                    fig.add_trace(go.Scatter(
                                        x=day_coverage['Hour'],
                                        y=day_coverage['Employees'],
                                        name='Actual Coverage',
                                        mode='lines+markers',
                                        marker=dict(size=8),
                                        line=dict(width=3, color='green')
                                    ))
                                    
                                    # Add TPH line on secondary y-axis if available
                                    if 'TPH' in day_demand.columns:
                                        fig.add_trace(go.Scatter(
                                            x=day_demand['Hour'],
                                            y=day_demand['TPH'],
                                            name='TPH',
                                            mode='lines',
                                            line=dict(width=2, color='purple', dash='dash'),
                                            yaxis='y2'
                                        ))
                                    
                                    # Update layout
                                    fig.update_layout(
                                        title=f'Hourly Demand vs. Coverage for {day}',
                                        xaxis=dict(
                                            title='Hour of Day',
                                            tickmode='array',
                                            tickvals=list(range(24)),
                                            ticktext=[f'{h:02d}:00' for h in range(24)]
                                        ),
                                        yaxis=dict(title='Volume / Staff'),
                                        yaxis2=dict(
                                            title='TPH',
                                            overlaying='y',
                                            side='right',
                                            showgrid=False
                                        ) if 'TPH' in day_demand.columns else None,
                                        legend=dict(
                                            orientation='h',
                                            yanchor='bottom',
                                            y=1.02,
                                            xanchor='center',
                                            x=0.5
                                        ),
                                        height=800,
                                        width=1200
                                    )
                                    
                                    st.plotly_chart(fig, use_container_width=True)
                                    
                                    # Show the hourly data in a table
                                    col1, col2 = st.columns(2)
                                    
                                    with col1:
                                        st.write("Hourly Demand & Goals:")
                                        
                                        # Create a more informative demand table
                                        if 'Volume' in day_demand.columns and 'Staff_Needed' in day_demand.columns:
                                            demand_display = day_demand[['Hour', 'Shift_Type', 'Volume', 'TPH', 'Staff_Needed']].copy()
                                            demand_display['Hour'] = demand_display['Hour'].apply(lambda x: f"{x:02d}:00")
                                            demand_display.columns = ['Hour', 'Shift Type', 'Volume Goal', 'TPH', 'Staff Needed']
                                        else:
                                            demand_display = day_demand
                                        
                                        st.dataframe(
                                            demand_display,
                                            hide_index=True,
                                            height=400,
                                            width=600
                                        )
                                    
                                    with col2:
                                        st.write("Hourly Coverage:")
                                        
                                        # Create a more informative coverage table
                                        coverage_display = day_coverage.copy()
                                        if not coverage_display.empty:
                                            coverage_display['Hour'] = coverage_display['Hour'].apply(lambda x: f"{x:02d}:00")
                                            
                                            # If we have demand data, add staff needed for comparison
                                            if 'Staff_Needed' in day_demand.columns:
                                                hour_to_staff = day_demand.set_index('Hour')['Staff_Needed'].to_dict()
                                                coverage_display['Staff Needed'] = coverage_display['Hour'].apply(
                                                    lambda h: hour_to_staff.get(int(h.split(':')[0]), 0)
                                                )
                                                coverage_display['Difference'] = coverage_display['Employees'] - coverage_display['Staff Needed']
                                        
                                        st.dataframe(
                                            coverage_display,
                                            hide_index=True, 
                                            height=400,
                                            width=600
                                        )
                        else:
                            # Simpler visualization without hourly demand data
                            hourly_fig = plot_hourly_coverage(
                                pd.DataFrame(), # Empty demand 
                                hourly_coverage
                            )
                            if hourly_fig is not None:
                                st.plotly_chart(hourly_fig, use_container_width=True)
                    else:
                        st.info("No shift timing results available. Enable Shift Timing Optimization in the options.")
                    
                    with viz_tabs[4]:
                        # Summary tables
                        if not st.session_state.met_df.empty:
                            staffing_summary, pattern_summary, met_summary, total_weekly_sd = create_summary_tables(
                                results_df, day_staffing, night_staffing, 
                                day_req, night_req, st.session_state.met_df
                            )
                            
                            st.subheader("Daily Staffing Summary")
                            st.dataframe(staffing_summary, 
                                       hide_index=True,
                                       height=300,
                                       width=1000)
                            
                            st.subheader("Pattern Distribution Summary")
                            st.dataframe(pattern_summary, 
                                       hide_index=True,
                                       height=400,
                                       width=800)
                            
                            st.subheader("MET Distribution By Pattern and Day")
                            st.dataframe(met_summary, 
                                       hide_index=True,
                                       height=400,
                                       width=1000)
                            
                            st.metric("Total Weekly SD Cost", f"${total_weekly_sd:.1f}")
                        else:
                            staffing_summary, pattern_summary, met_summary, total_weekly_sd = create_summary_tables(
                                results_df, day_staffing, night_staffing, 
                                day_req, night_req, pd.DataFrame()
                            )
                            
                            st.subheader("Daily Staffing Summary")
                            st.dataframe(staffing_summary, 
                                       hide_index=True,
                                       height=300,
                                       width=1000)
                            
                            st.subheader("Pattern Distribution Summary")
                            st.dataframe(pattern_summary, 
                                       hide_index=True,
                                       height=400,
                                       width=800)
                            
                            st.subheader("MET Distribution By Pattern and Day")
                            st.dataframe(met_summary, 
                                       hide_index=True,
                                       height=400,
                                       width=1000)
                            
                            st.metric("Total Weekly SD Cost", f"${total_weekly_sd:.1f}")
        else:
            st.warning("Please enter current staffing to continue.")
    
    except Exception as e:
        st.error(f"An unexpected error occurred: {str(e)}")
        logger.error(f"Application error: {str(e)}")

if __name__ == "__main__":
    main()

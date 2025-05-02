# Staffing Pattern Optimizer

A comprehensive tool for optimizing workforce staffing patterns across multiple sites, shifts, and days of the week.

## Features

- **Pattern Optimization**: Optimize staffing across different shift patterns to meet requirements while minimizing cost
- **MET Optimization**: Distribute Mandatory Extra Time effectively across available days
- **Shift Timing Optimization**: Determine optimal start times for shifts based on hourly demand
- **TPH-Based Calculations**: Calculate staffing needs based on volume and Throughput Per Hour (TPH)
- **Multi-Site Support**: Upload and analyze data for multiple sites
- **Visualizations**: Comprehensive charts showing coverage vs. demand on daily and hourly levels

## Getting Started

### Prerequisites

- Python 3.8+ (3.10 recommended)
- Required packages listed in `requirements.txt`

### Installation

```bash
# Clone this repository
git clone https://github.com/lunchwolfjoe/staffing.git

# Navigate to the project directory
cd staffing

# Create and activate a virtual environment (recommended)
python -m venv venv
# On Windows
venv\Scripts\activate
# On macOS/Linux
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the app
streamlit run staffing_optimizer.py
```

## Usage

1. **Load/Enter Data**:
   - Upload site schedules, hourly demand data, and current staffing
   - Or use the built-in test data generator

2. **Configure Parameters**:
   - Set cost weights for different shift patterns
   - Configure TPH (Throughput Per Hour) values
   - Set maximum overstaffing percentage

3. **Run Optimization**:
   - Select optimization target (cost or headcount)
   - Choose whether to include MET and shift timing optimization
   - View results in tables and visualizations

## Data Format

### Site Schedule CSV
```
site_name,shift_type,valid_start_times,work_periods,paid_breaks,unpaid_breaks
SiteA,day_shift,"0500,0600,0700","0700-0930;0945-1200;1230-1430","0930-0945","1200-1230"
```

### Hourly Demand CSV
```
site_name,day,hour,volume,tph
SiteA,Mon,6,800,10
SiteA,Mon,7,1200,10
```

### Current Staffing CSV
```
site_name,pattern,start_time,employees
SiteA,DA,0700,100
SiteA,DB,0700,80
```

## Deployment

### Local Deployment
Run the app locally using the instructions in the Installation section.

### Streamlit Cloud Deployment
This application can be deployed on Streamlit Cloud:

1. Push your code to a GitHub repository
2. Go to [Streamlit Cloud](https://streamlit.io/cloud)
3. Click "New app" and link to your repository
4. Enter `staffing_optimizer.py` as the main file
5. Choose Python 3.10
6. Deploy!

## Troubleshooting

If you encounter dependency issues:

1. **Missing Packages**: Make sure all dependencies are installed: `pip install -r requirements.txt`
2. **Version Conflicts**: Try using Python 3.10 which is known to work with all dependencies
3. **Platform Issues**: 
   - On Windows, ensure you have Microsoft Visual C++ Build Tools installed
   - On Linux, you may need to install additional system libraries: `apt-get install build-essential python3-dev`

## License

This project is licensed under the MIT License - see the LICENSE file for details. 
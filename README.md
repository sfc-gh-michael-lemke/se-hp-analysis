# SE High Performer Analysis

> Data-driven analysis of what separates high-performing Sales Engineers from peers.

A Python analysis script that generates comprehensive HTML reports from Snowflake SE performance data.

## What It Does

Analyzes Snowflake SFDC and activity data to identify patterns that differentiate high-performing SEs. Generates a multi-section HTML report covering:

- Cohort definitions (HP vs. peer groups by tenure)
- Activity volume and quality metrics
- Meeting and multi-threading patterns
- Product diversity and implementation velocity
- Account health indicators
- Specialist leverage patterns
- Individual SE profiles

## Business Value

| Benefit | Description |
|---------|-------------|
| Coaching clarity | Quantifies replicable HP patterns for manager conversations |
| Hiring criteria | Data-backed signal on what predicts SE success |
| Ramp optimization | Identifies which early behaviors predict HP status |
| QBR framework | Objective benchmarks for quarterly business reviews |

## Output

Generates a self-contained HTML report saved to `~/Downloads/` with:
- Executive summary with key HP differentiators
- Cohort comparison charts
- Individual SE scorecards
- Methodology and data sources

## Usage

```bash
python generate_hp_analysis.py
```

Requires an active Snowflake CLI connection with access to SFDC and activity tables.

## Prerequisites

- Python 3.10+
- Snowflake CLI (`snow`) configured with appropriate role
- Access to: `SALES_DEV`, `SNOW_CERTIFIED`, Salesforce data

## Value Realization

Understanding high-performer patterns enables Snowflake SE leadership to scale what works: build better hiring scorecards, design more effective ramp programs, and give managers specific, data-backed coaching angles rather than generic performance feedback.

# SE High Performer Analysis

> Data-driven analysis of what separates high-performing Sales Engineers from peers at Snowflake.

A Python analysis script that generates comprehensive HTML reports from Snowflake SE performance data.

## What It Does

Analyzes Snowflake SFDC and activity data to identify patterns that differentiate high-performing SEs. Generates a multi-section, self-contained HTML report covering:

- Cohort definitions (HP vs. peer groups by tenure and segment)
- Activity volume and quality metrics
- Meeting patterns and multi-threading behavior
- Product diversity and implementation velocity
- Account health indicators and specialist leverage patterns
- Individual SE profiles with benchmarked scorecards

## Business Value

| Benefit | Description |
|---------|-------------|
| Coaching clarity | Quantifies replicable HP behaviors for manager conversations |
| Hiring signal | Data-backed attributes that predict SE success |
| Ramp optimization | Identifies which early behaviors correlate with HP status |
| QBR framework | Objective benchmarks for quarterly business reviews |
| Org-wide patterns | Surfaces team-level insights for leadership planning |

## Output

Generates a self-contained HTML report saved to `~/Downloads/` with:

- Executive summary with key HP differentiators
- Cohort comparison visualizations
- Individual SE scorecards
- Statistical methodology notes

## Usage

```bash
python generate_hp_analysis.py
```

Requires an active Snowflake CLI connection with appropriate role access.

## Prerequisites

- Python 3.10+
- Snowflake CLI (`snow`) configured with `SALES_EXEC_ACCESS_RL` or equivalent
- Access to: `SALES_DEV`, `SNOW_CERTIFIED`, Salesforce/activity tables

## Data Sources

| Source | Purpose |
|--------|---------|
| `SALES_DEV` | SE activity and engagement data |
| `SNOW_CERTIFIED` | Attainment and quota data |
| Salesforce (via Fivetran) | Opportunity and account data |
| Gong (via activity tables) | Call and meeting data |

## Value Realization

Understanding high-performer patterns enables SE leadership to scale what works: build better hiring scorecards, design more effective ramp programs, and give managers specific, data-backed coaching angles rather than generic performance feedback. This script turns a week of analyst work into a 10-minute automated analysis run.

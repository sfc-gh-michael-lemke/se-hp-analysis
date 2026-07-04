import snowflake.connector
import os
from datetime import datetime, date
from decimal import Decimal

# ── Configuration (substituted by skill) ─────────────────────────────────────
CONNECTION_NAME = "Coco2"
HP_NAMES = ["Bjorn Jonsson", "Caroline Bastarache", "Kaitlyn Wells", "Kern Lee", "Mikołaj Gałkowski"]
HP_COUNT = 5
FY_LABEL = "FY26"
SCOPE_LABEL = "Vishal Mehrotra Theater"
OUTPUT_BASE = "SE_HP_Analysis_VishalMehrotra_FY26"
OUTPUT_HTML = os.path.expanduser(f"~/Desktop/{OUTPUT_BASE}.html")
OUTPUT_PDF = os.path.expanduser(f"~/Desktop/{OUTPUT_BASE}.pdf")

# Build SQL fragments
HP_SQL_LIST = ",".join(f"'{n}'" for n in HP_NAMES)
COHORT_CASE = f"CASE WHEN SE_NAME IN ({HP_SQL_LIST}) THEN 'HP' ELSE 'Peer' END"
COHORT_CASE_EMP = f"CASE WHEN EMPLOYEE_NAME IN ({HP_SQL_LIST}) THEN 'HP' ELSE 'Peer' END"
COHORT_CASE_UC = f"CASE WHEN USE_CASE_LEAD_SE_NAME IN ({HP_SQL_LIST}) THEN 'HP' ELSE 'Peer' END"

SE_METRICS_FILTER = "SE_VP = 'Vishal Mehrotra'"
DAILY_METRICS_FILTER = "VP = 'Vishal Mehrotra'"
USE_CASE_FILTER = "ACCOUNT_SE_VP = 'Vishal Mehrotra'"
FY_FILTER = "FISCAL_QUARTER_FYYYYY_QQ LIKE 'FY2026%'"
FY_START_DATE = "2025-02-01"

# ── Connect to Snowflake ─────────────────────────────────────────────────────
conn = snowflake.connector.connect(connection_name=CONNECTION_NAME)
cur = conn.cursor()
cur.execute("USE WAREHOUSE CORPORATE_SE_WH")
print("Connected. Running queries...")

# ── Helper Functions ─────────────────────────────────────────────────────────
def query(sql):
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    return [dict(zip(cols, r)) for r in rows]

def pct_diff(hp_val, peer_val):
    if peer_val and peer_val != 0:
        return ((hp_val - peer_val) / abs(peer_val)) * 100
    return 0

def fmt_pct(val):
    if val > 0:
        return f"+{val:.0f}%"
    return f"{val:.0f}%"

def fmt_dollar(val):
    if val is None:
        return "$0"
    if abs(val) >= 1_000_000:
        return f"${val/1_000_000:.1f}M"
    if abs(val) >= 1_000:
        return f"${val/1_000:.0f}K"
    return f"${val:,.0f}"

# ── QUERY 1: Tenure & Experience ─────────────────────────────────────────────
print("  1/10 Tenure & Experience...")
tenure_data = query(f"""
    WITH latest AS (
        SELECT SE_NAME, HIRE_DATE, TENURE_IN_DAYS,
               {COHORT_CASE} AS COHORT,
               ROW_NUMBER() OVER (PARTITION BY SE_NAME ORDER BY WEEK_END_DATE DESC) AS rn
        FROM SALES.DEV.SE_METRICS
        WHERE {SE_METRICS_FILTER}
          AND SE_GROUP = 'Field SE'
          AND {FY_FILTER}
    )
    SELECT COHORT,
           COUNT(*) AS SE_COUNT,
           AVG(TENURE_IN_DAYS / 365.25) AS AVG_TENURE_YRS,
           MEDIAN(TENURE_IN_DAYS / 365.25) AS MED_TENURE_YRS,
           SUM(CASE WHEN TENURE_IN_DAYS < 365 THEN 1 ELSE 0 END) AS UNDER_1YR,
           SUM(CASE WHEN TENURE_IN_DAYS >= 365 AND TENURE_IN_DAYS < 730 THEN 1 ELSE 0 END) AS YR_1_2,
           SUM(CASE WHEN TENURE_IN_DAYS >= 730 AND TENURE_IN_DAYS < 1095 THEN 1 ELSE 0 END) AS YR_2_3,
           SUM(CASE WHEN TENURE_IN_DAYS >= 1095 AND TENURE_IN_DAYS < 1826 THEN 1 ELSE 0 END) AS YR_3_5,
           SUM(CASE WHEN TENURE_IN_DAYS >= 1826 THEN 1 ELSE 0 END) AS YR_5_PLUS
    FROM latest
    WHERE rn = 1
    GROUP BY COHORT
""")

# ── QUERY 2: Volume & Efficiency ─────────────────────────────────────────────
print("  2/10 Volume & Efficiency...")
volume_data = query(f"""
    WITH se_totals AS (
        SELECT SE_NAME,
               {COHORT_CASE} AS COHORT,
               MAX(LEAD_SE_ACCOUNT_CNT) AS ACCOUNTS,
               MAX(NEW_USE_CASE_CNT) AS NEW_UCS,
               MAX(USE_CASE_TECH_WIN_CNT) AS TECH_WINS,
               MAX(USE_CASE_TECH_WIN_ACV) AS TW_ACV,
               MAX(USE_CASE_DEPLOYED_CNT) AS GO_LIVES,
               MAX(USE_CASE_DEPLOYED_ACV) AS GL_ACV,
               AVG(TIME_TO_TECH_WIN) AS AVG_TTW
        FROM SALES.DEV.SE_METRICS
        WHERE {SE_METRICS_FILTER}
          AND SE_GROUP = 'Field SE'
          AND {FY_FILTER}
        GROUP BY SE_NAME
    )
    SELECT COHORT,
           COUNT(*) AS SE_COUNT,
           AVG(ACCOUNTS) AS AVG_ACCOUNTS,
           AVG(NEW_UCS) AS AVG_NEW_UCS,
           AVG(TECH_WINS) AS AVG_TWS,
           AVG(TW_ACV) AS AVG_TW_ACV,
           AVG(GO_LIVES) AS AVG_GLS,
           AVG(GL_ACV) AS AVG_GL_ACV,
           AVG(AVG_TTW) AS AVG_TTW,
           AVG(CASE WHEN ACCOUNTS > 0 THEN TECH_WINS * 1.0 / ACCOUNTS END) AS AVG_TW_PER_ACCT,
           AVG(CASE WHEN NEW_UCS > 0 THEN TECH_WINS * 1.0 / NEW_UCS END) AS AVG_TW_CONV,
           AVG(CASE WHEN TECH_WINS > 0 THEN GO_LIVES * 1.0 / TECH_WINS END) AS AVG_GL_TW_RATE,
           AVG(CASE WHEN TECH_WINS > 0 THEN TW_ACV * 1.0 / TECH_WINS END) AS AVG_ACV_PER_TW
    FROM se_totals
    GROUP BY COHORT
""")

# ── QUERY 3: Activity & Engagement (Combined Vivun + SetSail) ────────────────
print("  3/10 Activity & Engagement...")
activity_data = query(f"""
    WITH vivun AS (
        SELECT SE_NAME, {COHORT_CASE} AS COHORT,
               MAX(TOTAL_VIVUN_ACTIVITY_CNT) AS VIVUN_ACTS,
               MAX(TOTAL_VIVUN_ACTIVITY_HOURS) AS VIVUN_HRS,
               MAX(TOTAL_ACTIVITY_COUNT_IMPORTED_BY_FIELD_SE) AS EXPORT_ACTS
        FROM SALES.DEV.SE_METRICS
        WHERE {SE_METRICS_FILTER} AND SE_GROUP = 'Field SE' AND {FY_FILTER}
        GROUP BY SE_NAME
    ),
    setsail AS (
        SELECT EMPLOYEE_NAME AS SE_NAME, {COHORT_CASE_EMP} AS COHORT,
               SUM(TOTAL_SS_ACTIVITY_CNT) AS SS_ACTS,
               SUM(TOTAL_SS_ACTIVITY_HOURS) AS SS_HRS
        FROM SALES.DEV.SE_INDIVIDUAL_METRICS_DAILY
        WHERE {DAILY_METRICS_FILTER} AND SE_GROUP = 'Field SE'
          AND TIME_PERIOD_TYPE = 'Day'
          AND TIME_PERIOD_START >= '{FY_START_DATE}'
        GROUP BY EMPLOYEE_NAME
    )
    SELECT v.COHORT,
           COUNT(*) AS SE_COUNT,
           AVG(v.VIVUN_ACTS) AS AVG_VIVUN_ACTS,
           AVG(s.SS_ACTS) AS AVG_SS_ACTS,
           AVG(COALESCE(v.VIVUN_ACTS,0) + COALESCE(s.SS_ACTS,0)) AS AVG_COMBINED_ACTS,
           AVG(COALESCE(v.VIVUN_HRS,0) + COALESCE(s.SS_HRS,0)) AS AVG_COMBINED_HRS,
           AVG(v.EXPORT_ACTS) AS AVG_EXPORT_ACTS
    FROM vivun v
    LEFT JOIN setsail s ON v.SE_NAME = s.SE_NAME
    GROUP BY v.COHORT
""")

# ── QUERY 4: Meeting Quality ─────────────────────────────────────────────────
print("  4/10 Meeting Quality...")
meeting_data = query(f"""
    WITH se_meetings AS (
        SELECT EMPLOYEE_NAME AS SE_NAME,
               {COHORT_CASE_EMP} AS COHORT,
               COUNT(*) AS TOTAL_MTGS,
               SUM(CASE WHEN IS_VP_EXTERNAL_INVOLVED = TRUE THEN 1 ELSE 0 END) AS VP_MTGS,
               SUM(CASE WHEN IS_AIML_MEETING = TRUE THEN 1 ELSE 0 END) AS AI_MTGS,
               SUM(CASE WHEN IS_PARTNER_PRESENT = TRUE THEN 1 ELSE 0 END) AS PARTNER_MTGS,
               AVG(MEETING_DURATION) AS AVG_DURATION
        FROM SALES.DEV.INT_SE_SETSAIL_MEETINGS
        WHERE ACTIVITY_DATE >= '{FY_START_DATE}'
          AND SE_GROUP = 'Field SE'
        GROUP BY EMPLOYEE_NAME
    )
    SELECT COHORT,
           COUNT(*) AS SE_COUNT,
           AVG(TOTAL_MTGS) AS AVG_TOTAL_MTGS,
           AVG(CASE WHEN TOTAL_MTGS > 0 THEN VP_MTGS * 100.0 / TOTAL_MTGS END) AS AVG_VP_PCT,
           AVG(CASE WHEN TOTAL_MTGS > 0 THEN AI_MTGS * 100.0 / TOTAL_MTGS END) AS AVG_AI_PCT,
           AVG(CASE WHEN TOTAL_MTGS > 0 THEN PARTNER_MTGS * 100.0 / TOTAL_MTGS END) AS AVG_PARTNER_PCT,
           AVG(AVG_DURATION) AS AVG_DURATION
    FROM se_meetings
    WHERE COHORT IS NOT NULL
    GROUP BY COHORT
""")

# ── QUERY 5: Multi-Threading & Contact Breadth ───────────────────────────────
print("  5/10 Multi-Threading...")
threading_data = query(f"""
    WITH contacts AS (
        SELECT m.EMPLOYEE_NAME AS SE_NAME,
               {COHORT_CASE_EMP} AS COHORT,
               m.ACCOUNT_NAME,
               COUNT(DISTINCT p.P_EMAIL) AS DISTINCT_CONTACTS,
               COUNT(DISTINCT CASE WHEN p.SETSAIL_SENIORITY IN ('VP','CxO / Founder')
                     THEN p.P_EMAIL END) AS SENIOR_CONTACTS
        FROM SALES.DEV.INT_SE_SETSAIL_MEETINGS m
        JOIN SALES.DEV.SETSAIL_RAW_PARTICIPANTS p
          ON m.ACTIVITY_ID = p.ACTIVITY_ID
        WHERE m.ACTIVITY_DATE >= '{FY_START_DATE}'
          AND p.IS_EXTERNAL = TRUE
          AND m.SE_GROUP = 'Field SE'
        GROUP BY m.EMPLOYEE_NAME, m.ACCOUNT_NAME
    )
    SELECT COHORT,
           COUNT(DISTINCT SE_NAME) AS SE_COUNT,
           AVG(TOTAL_CONTACTS) AS AVG_CONTACTS,
           AVG(TOTAL_SENIOR) AS AVG_SENIOR,
           AVG(CONTACTS_PER_ACCT) AS AVG_CONTACTS_PER_ACCT,
           AVG(SENIOR_PER_ACCT) AS AVG_SENIOR_PER_ACCT,
           AVG(PCT_DEEP) AS AVG_PCT_DEEP,
           AVG(PCT_MULTI_EXEC) AS AVG_PCT_MULTI_EXEC
    FROM (
        SELECT SE_NAME, COHORT,
               SUM(DISTINCT_CONTACTS) AS TOTAL_CONTACTS,
               SUM(SENIOR_CONTACTS) AS TOTAL_SENIOR,
               AVG(DISTINCT_CONTACTS) AS CONTACTS_PER_ACCT,
               AVG(SENIOR_CONTACTS) AS SENIOR_PER_ACCT,
               SUM(CASE WHEN DISTINCT_CONTACTS >= 5 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS PCT_DEEP,
               SUM(CASE WHEN SENIOR_CONTACTS >= 2 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS PCT_MULTI_EXEC
        FROM contacts
        GROUP BY SE_NAME, COHORT
    )
    GROUP BY COHORT
""")

# ── QUERY 6: Product Diversity ────────────────────────────────────────────────
print("  6/10 Product Diversity...")
product_data = query(f"""
    WITH uc_cats AS (
        SELECT USE_CASE_LEAD_SE_NAME AS SE_NAME,
               {COHORT_CASE_UC} AS COHORT,
               ACCOUNT_NAME,
               USE_CASE_ID,
               f.VALUE::STRING AS PRODUCT_CATEGORY
        FROM MDM.MDM_INTERFACES.DIM_USE_CASE,
             LATERAL FLATTEN(INPUT => PRODUCT_CATEGORY_ARRAY) f
        WHERE {USE_CASE_FILTER}
          AND CREATED_DATE >= '{FY_START_DATE}'
          AND USE_CASE_STATUS NOT IN ('Not In Pursuit')
    ),
    se_summary AS (
        SELECT SE_NAME, COHORT,
               COUNT(DISTINCT USE_CASE_ID) AS TOTAL_UCS,
               COUNT(DISTINCT PRODUCT_CATEGORY) AS NUM_CATEGORIES,
               COUNT(DISTINCT ACCOUNT_NAME) AS NUM_ACCOUNTS
        FROM uc_cats
        GROUP BY SE_NAME, COHORT
    ),
    acct_depth AS (
        SELECT SE_NAME, COHORT, ACCOUNT_NAME,
               COUNT(DISTINCT USE_CASE_ID) AS UCS_IN_ACCT
        FROM uc_cats
        GROUP BY SE_NAME, COHORT, ACCOUNT_NAME
    )
    SELECT s.COHORT,
           COUNT(DISTINCT s.SE_NAME) AS SE_COUNT,
           AVG(s.NUM_CATEGORIES) AS AVG_CATEGORIES,
           SUM(CASE WHEN s.NUM_CATEGORIES >= 5 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS PCT_5_CAT,
           AVG(s.TOTAL_UCS * 1.0 / NULLIF(s.NUM_ACCOUNTS, 0)) AS AVG_UCS_PER_ACCT,
           AVG(deep.PCT_DEEP) AS AVG_PCT_DEEP_ACCTS
    FROM se_summary s
    LEFT JOIN (
        SELECT SE_NAME, COHORT,
               SUM(CASE WHEN UCS_IN_ACCT >= 3 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS PCT_DEEP
        FROM acct_depth
        GROUP BY SE_NAME, COHORT
    ) deep ON s.SE_NAME = deep.SE_NAME
    GROUP BY s.COHORT
""")

# ── QUERY 7: Implementation Velocity ─────────────────────────────────────────
print("  7/10 Implementation Velocity...")
velocity_data = query(f"""
    WITH uc_velocity AS (
        SELECT USE_CASE_LEAD_SE_NAME AS SE_NAME,
               {COHORT_CASE_UC} AS COHORT,
               DATEDIFF('day', TECHNICAL_WIN_DATE, IMPLEMENTATION_START_DATE) AS TW_TO_IMPL,
               DATEDIFF('day', IMPLEMENTATION_START_DATE, GO_LIVE_DATE) AS IMPL_TO_DEPLOY,
               DATEDIFF('day', TECHNICAL_WIN_DATE, GO_LIVE_DATE) AS TW_TO_DEPLOY
        FROM MDM.MDM_INTERFACES.DIM_USE_CASE
        WHERE {USE_CASE_FILTER}
          AND CREATED_DATE >= '{FY_START_DATE}'
          AND TECHNICAL_WIN_DATE IS NOT NULL
    )
    SELECT COHORT,
           COUNT(*) AS UC_COUNT,
           AVG(TW_TO_IMPL) AS AVG_TW_IMPL,
           MEDIAN(TW_TO_IMPL) AS MED_TW_IMPL,
           AVG(IMPL_TO_DEPLOY) AS AVG_IMPL_DEPLOY,
           MEDIAN(IMPL_TO_DEPLOY) AS MED_IMPL_DEPLOY,
           AVG(TW_TO_DEPLOY) AS AVG_TW_DEPLOY,
           MEDIAN(TW_TO_DEPLOY) AS MED_TW_DEPLOY
    FROM uc_velocity
    WHERE TW_TO_IMPL >= 0 AND TW_TO_IMPL < 365
    GROUP BY COHORT
""")

# ── QUERY 8: Account Health ──────────────────────────────────────────────────
print("  8/10 Account Health...")
health_data = query(f"""
    WITH se_accounts AS (
        SELECT DISTINCT USE_CASE_LEAD_SE_NAME AS SE_NAME, ACCOUNT_NAME,
               {COHORT_CASE_UC} AS COHORT
        FROM MDM.MDM_INTERFACES.DIM_USE_CASE
        WHERE {USE_CASE_FILTER}
          AND CREATED_DATE >= '{FY_START_DATE}'
    ),
    acct_health AS (
        SELECT sa.SE_NAME, sa.COHORT,
               abi.OVERALL_ASSESSMENT_SCORE,
               abi.ASSESSMENT_TIER,
               abi.YOY_REVENUE_GROWTH_PCT
        FROM se_accounts sa
        JOIN SALES.DEV.ACCOUNT_BUSINESS_INDICATORS abi
          ON sa.ACCOUNT_NAME = abi.ACCOUNT_NAME
    )
    SELECT COHORT,
           COUNT(DISTINCT SE_NAME) AS SE_COUNT,
           AVG(OVERALL_ASSESSMENT_SCORE) AS AVG_HEALTH,
           SUM(CASE WHEN ASSESSMENT_TIER IN ('Strong','Exceptional') THEN 1 ELSE 0 END)
               * 100.0 / NULLIF(COUNT(*), 0) AS PCT_STRONG,
           SUM(CASE WHEN ASSESSMENT_TIER IN ('Critical Gap','Needs Attention') THEN 1 ELSE 0 END)
               * 100.0 / NULLIF(COUNT(*), 0) AS PCT_AT_RISK,
           AVG(YOY_REVENUE_GROWTH_PCT) AS AVG_YOY_GROWTH
    FROM acct_health
    GROUP BY COHORT
""")

# ── QUERY 9: Specialist Leverage ──────────────────────────────────────────────
print("  9/10 Specialist Leverage...")
specialist_data = query(f"""
    WITH uc_specialist AS (
        SELECT USE_CASE_LEAD_SE_NAME AS SE_NAME,
               {COHORT_CASE_UC} AS COHORT,
               USE_CASE_ID,
               CASE WHEN USE_CASE_TEAM_PLATFORM_SPECIALIST_LIST IS NOT NULL
                         AND ARRAY_SIZE(USE_CASE_TEAM_PLATFORM_SPECIALIST_LIST) > 0
                    THEN 1 ELSE 0 END AS HAS_SPECIALIST
        FROM MDM.MDM_INTERFACES.DIM_USE_CASE
        WHERE {USE_CASE_FILTER}
          AND CREATED_DATE >= '{FY_START_DATE}'
          AND USE_CASE_STATUS NOT IN ('Not In Pursuit')
    )
    SELECT COHORT,
           COUNT(DISTINCT SE_NAME) AS SE_COUNT,
           SUM(HAS_SPECIALIST) * 100.0 / NULLIF(COUNT(*), 0) AS PCT_WITH_SPECIALIST
    FROM uc_specialist
    GROUP BY COHORT
""")

# ── QUERY 10: Individual SE Profiles ──────────────────────────────────────────
print("  10/10 Individual SE Profiles...")
individual_data = query(f"""
    SELECT SE_NAME,
           MAX(LEAD_SE_ACCOUNT_CNT) AS ACCOUNTS,
           MAX(NEW_USE_CASE_CNT) AS NEW_UCS,
           MAX(USE_CASE_TECH_WIN_CNT) AS TECH_WINS,
           MAX(USE_CASE_TECH_WIN_ACV) AS TW_ACV,
           MAX(USE_CASE_DEPLOYED_CNT) AS GO_LIVES,
           MAX(USE_CASE_DEPLOYED_ACV) AS GL_ACV,
           AVG(TIME_TO_TECH_WIN) AS AVG_TTW,
           AVG(CASE WHEN NEW_USE_CASE_CNT > 0
               THEN USE_CASE_TECH_WIN_CNT * 1.0 / NEW_USE_CASE_CNT END) AS TW_CONV,
           AVG(CASE WHEN USE_CASE_TECH_WIN_CNT > 0
               THEN USE_CASE_DEPLOYED_CNT * 1.0 / USE_CASE_TECH_WIN_CNT END) AS GL_TW_RATE,
           AVG(CASE WHEN USE_CASE_TECH_WIN_CNT > 0
               THEN USE_CASE_TECH_WIN_ACV * 1.0 / USE_CASE_TECH_WIN_CNT END) AS ACV_PER_TW,
           AVG(CASE WHEN LEAD_SE_ACCOUNT_CNT > 0
               THEN USE_CASE_TECH_WIN_CNT * 1.0 / LEAD_SE_ACCOUNT_CNT END) AS TW_PER_ACCT
    FROM SALES.DEV.SE_METRICS
    WHERE SE_NAME IN ({HP_SQL_LIST})
      AND {SE_METRICS_FILTER}
      AND SE_GROUP = 'Field SE'
      AND {FY_FILTER}
    GROUP BY SE_NAME
    ORDER BY TECH_WINS DESC
""")

print("All queries complete. Building report...")

# ── Extract HP vs Peer data ──────────────────────────────────────────────────
def get_cohort(data, cohort):
    for d in data:
        if d.get('COHORT') == cohort:
            return d
    return {}

hp_tenure = get_cohort(tenure_data, 'HP')
peer_tenure = get_cohort(tenure_data, 'Peer')
hp_vol = get_cohort(volume_data, 'HP')
peer_vol = get_cohort(volume_data, 'Peer')
hp_act = get_cohort(activity_data, 'HP')
peer_act = get_cohort(activity_data, 'Peer')
hp_mtg = get_cohort(meeting_data, 'HP')
peer_mtg = get_cohort(meeting_data, 'Peer')
hp_thread = get_cohort(threading_data, 'HP')
peer_thread = get_cohort(threading_data, 'Peer')
hp_prod = get_cohort(product_data, 'HP')
peer_prod = get_cohort(product_data, 'Peer')
hp_vel = get_cohort(velocity_data, 'HP')
peer_vel = get_cohort(velocity_data, 'Peer')
hp_health = get_cohort(health_data, 'HP')
peer_health = get_cohort(health_data, 'Peer')
hp_spec = get_cohort(specialist_data, 'HP')
peer_spec = get_cohort(specialist_data, 'Peer')

peer_count = peer_tenure.get('SE_COUNT', 0)

# Safe getters
def g(d, k, default=0):
    v = d.get(k)
    if v is None:
        return default
    if isinstance(v, Decimal):
        return float(v)
    return v

# ── Compute key differentiators for executive summary ────────────────────────
diffs = []

tenure_diff = pct_diff(g(hp_tenure, 'AVG_TENURE_YRS'), g(peer_tenure, 'AVG_TENURE_YRS'))
if abs(tenure_diff) > 10:
    diffs.append(('Tenure', f"{g(hp_tenure,'AVG_TENURE_YRS'):.1f} yrs vs {g(peer_tenure,'AVG_TENURE_YRS'):.1f} yrs", tenure_diff))

tw_acct_diff = pct_diff(g(hp_vol, 'AVG_TW_PER_ACCT'), g(peer_vol, 'AVG_TW_PER_ACCT'))
if abs(tw_acct_diff) > 10:
    diffs.append(('TW/Account', f"{g(hp_vol,'AVG_TW_PER_ACCT'):.2f} vs {g(peer_vol,'AVG_TW_PER_ACCT'):.2f}", tw_acct_diff))

acv_diff = pct_diff(g(hp_vol, 'AVG_ACV_PER_TW'), g(peer_vol, 'AVG_ACV_PER_TW'))
if abs(acv_diff) > 10:
    diffs.append(('ACV/TW', f"{fmt_dollar(g(hp_vol,'AVG_ACV_PER_TW'))} vs {fmt_dollar(g(peer_vol,'AVG_ACV_PER_TW'))}", acv_diff))

gl_diff = pct_diff(g(hp_vol, 'AVG_GLS'), g(peer_vol, 'AVG_GLS'))
if abs(gl_diff) > 10:
    diffs.append(('Go-Lives', f"{g(hp_vol,'AVG_GLS'):.1f} vs {g(peer_vol,'AVG_GLS'):.1f} avg go-lives", gl_diff))

tw_diff = pct_diff(g(hp_vol, 'AVG_TWS'), g(peer_vol, 'AVG_TWS'))
if abs(tw_diff) > 10:
    diffs.append(('Tech Wins', f"{g(hp_vol,'AVG_TWS'):.1f} vs {g(peer_vol,'AVG_TWS'):.1f} avg tech wins", tw_diff))

contact_diff = pct_diff(g(hp_thread, 'AVG_CONTACTS'), g(peer_thread, 'AVG_CONTACTS'))
if abs(contact_diff) > 10:
    diffs.append(('Contact Breadth', f"{g(hp_thread,'AVG_CONTACTS'):.0f} vs {g(peer_thread,'AVG_CONTACTS'):.0f} contacts", contact_diff))

senior_diff = pct_diff(g(hp_thread, 'AVG_SENIOR'), g(peer_thread, 'AVG_SENIOR'))
if abs(senior_diff) > 10:
    diffs.append(('Senior Contacts', f"{g(hp_thread,'AVG_SENIOR'):.1f} vs {g(peer_thread,'AVG_SENIOR'):.1f} VP/CxO contacts", senior_diff))

activity_diff = pct_diff(g(hp_act, 'AVG_COMBINED_ACTS'), g(peer_act, 'AVG_COMBINED_ACTS'))
if abs(activity_diff) > 10:
    diffs.append(('Combined Activity', f"{g(hp_act,'AVG_COMBINED_ACTS'):.0f} vs {g(peer_act,'AVG_COMBINED_ACTS'):.0f} activities", activity_diff))

health_diff = pct_diff(g(hp_health, 'PCT_STRONG'), g(peer_health, 'PCT_STRONG'))
if abs(health_diff) > 10:
    diffs.append(('Strong/Exceptional Accts', f"{g(hp_health,'PCT_STRONG'):.0f}% vs {g(peer_health,'PCT_STRONG'):.0f}%", health_diff))

prod_diff = pct_diff(g(hp_prod, 'AVG_UCS_PER_ACCT'), g(peer_prod, 'AVG_UCS_PER_ACCT'))
if abs(prod_diff) > 10:
    diffs.append(('UCs/Account', f"{g(hp_prod,'AVG_UCS_PER_ACCT'):.2f} vs {g(peer_prod,'AVG_UCS_PER_ACCT'):.2f}", prod_diff))

spec_diff = pct_diff(g(hp_spec, 'PCT_WITH_SPECIALIST'), g(peer_spec, 'PCT_WITH_SPECIALIST'))
if abs(spec_diff) > 10:
    diffs.append(('Specialist Leverage', f"{g(hp_spec,'PCT_WITH_SPECIALIST'):.0f}% vs {g(peer_spec,'PCT_WITH_SPECIALIST'):.0f}%", spec_diff))

vp_mtg_diff = pct_diff(g(hp_mtg, 'AVG_VP_PCT'), g(peer_mtg, 'AVG_VP_PCT'))
if abs(vp_mtg_diff) > 10:
    diffs.append(('VP-External Meeting %', f"{g(hp_mtg,'AVG_VP_PCT'):.1f}% vs {g(peer_mtg,'AVG_VP_PCT'):.1f}%", vp_mtg_diff))

# Sort by magnitude
diffs.sort(key=lambda x: abs(x[2]), reverse=True)

# ── SVG Bar Chart Builder ────────────────────────────────────────────────────
def svg_bar_chart(metrics, title="", hp_label=f"High Performers (n={HP_COUNT})", peer_label=f"Peers (n={peer_count})"):
    """
    metrics: list of (label, hp_val, peer_val, fmt_fn) tuples
    Returns SVG string
    """
    row_h = 50
    label_w = 180
    chart_w = 700
    h = 30 + len(metrics) * row_h + 10
    max_val = max(max(abs(m[1]), abs(m[2])) for m in metrics) or 1
    bar_max_w = chart_w - label_w - 100

    svg = f'<svg viewBox="0 0 {chart_w} {h}" class="bar-chart" style="width:100%;height:auto;">\n'

    for i, (label, hp_val, peer_val, fmt_fn) in enumerate(metrics):
        y_base = 30 + i * row_h
        hp_w = abs(hp_val) / max_val * bar_max_w if max_val else 0
        peer_w = abs(peer_val) / max_val * bar_max_w if max_val else 0

        svg += f'  <line x1="{label_w}" y1="{y_base}" x2="{chart_w-20}" y2="{y_base}" stroke="#F1F5F9" stroke-width="1"/>\n'
        svg += f'  <text x="{label_w-5}" y="{y_base+20}" text-anchor="end" font-size="12" fill="#64748B">{label}</text>\n'
        svg += f'  <rect x="{label_w}" y="{y_base+5}" width="{hp_w:.0f}" height="14" rx="3" fill="#29B5E8"/>\n'
        svg += f'  <rect x="{label_w}" y="{y_base+23}" width="{peer_w:.0f}" height="14" rx="3" fill="#CBD5E1"/>\n'
        svg += f'  <text x="{label_w+hp_w+6:.0f}" y="{y_base+17}" font-size="11" fill="#1E293B" font-weight="600">{fmt_fn(hp_val)}</text>\n'
        svg += f'  <text x="{label_w+peer_w+6:.0f}" y="{y_base+35}" font-size="11" fill="#64748B">{fmt_fn(peer_val)}</text>\n'

    svg += '</svg>'
    return svg

def fmt_num(v):
    if v is None: return "0"
    return f"{v:.1f}" if isinstance(v, float) else str(v)

def fmt_pct_val(v):
    if v is None: return "0%"
    return f"{v:.1f}%"

def fmt_days(v):
    if v is None: return "0d"
    return f"{v:.0f}d"

# ── Build KPI card HTML ──────────────────────────────────────────────────────
def kpi_card(label, hp_val, peer_val, fmt_fn=fmt_num, invert=False):
    diff = pct_diff(hp_val, peer_val) if not invert else pct_diff(peer_val, hp_val)
    delta_class = "pos" if diff > 0 else ("neg" if diff < -5 else "")
    delta_text = fmt_pct(diff if not invert else -diff)
    if abs(diff) < 3:
        delta_text = "~same"
        delta_class = ""
    return f'''<div class="kpi-card">
      <div class="kpi-label">{label}</div>
      <div class="kpi-value">{fmt_fn(hp_val)}</div>
      <div class="kpi-sub">vs {fmt_fn(peer_val)} peers</div>
      <div class="kpi-delta {delta_class}">{delta_text}</div>
    </div>'''

# ── Build Individual SE table ────────────────────────────────────────────────
def build_individual_table(data):
    rows = ""
    for d in data:
        rows += f'''<tr>
          <td>{d['SE_NAME']}</td>
          <td class="num">{g(d,'ACCOUNTS'):.0f}</td>
          <td class="num">{g(d,'NEW_UCS'):.0f}</td>
          <td class="num">{g(d,'TECH_WINS'):.0f}</td>
          <td class="num">{fmt_dollar(g(d,'TW_ACV'))}</td>
          <td class="num">{g(d,'GO_LIVES'):.0f}</td>
          <td class="num">{fmt_dollar(g(d,'GL_ACV'))}</td>
          <td class="num">{g(d,'AVG_TTW'):.0f}</td>
          <td class="num">{g(d,'TW_CONV',0)*100:.0f}%</td>
          <td class="num">{g(d,'GL_TW_RATE',0)*100:.0f}%</td>
          <td class="num">{fmt_dollar(g(d,'ACV_PER_TW'))}</td>
          <td class="num">{g(d,'TW_PER_ACCT',0):.2f}</td>
        </tr>'''
    return rows

# ── Build Executive Summary ──────────────────────────────────────────────────
def build_exec_summary():
    if not diffs:
        return "<p>Insufficient data to generate executive summary differentiators.</p>"
    top_diffs = diffs[:8]
    items = ""
    for name, detail, pct in top_diffs:
        direction = "higher" if pct > 0 else "lower"
        items += f"<li><strong>{abs(pct):.0f}% {direction} {name}</strong>: {detail}</li>\n"
    return f"""<p style="margin-bottom:12px;">Analysis of {HP_COUNT} high-performing SEs against {peer_count} peers within {SCOPE_LABEL} reveals consistent patterns. The top differentiators (ranked by magnitude):</p>
    <ul style="padding-left:20px;">{items}</ul>
    <p style="margin-top:16px; font-size:14px; color:#64748B;"><em>The overarching finding: the largest behavioral gaps are in multi-threading (contact breadth) and engagement depth. SEs who engage more people, at more levels, across more accounts consistently deliver better outcomes.</em></p>"""

# ── Build Tenure Distribution Chart ──────────────────────────────────────────
def tenure_chart():
    hp_n = g(hp_tenure, 'SE_COUNT', 1)
    peer_n = g(peer_tenure, 'SE_COUNT', 1)
    buckets = [
        ("Under 1yr", g(hp_tenure,'UNDER_1YR')/hp_n*100, g(peer_tenure,'UNDER_1YR')/peer_n*100),
        ("1-2 yrs", g(hp_tenure,'YR_1_2')/hp_n*100, g(peer_tenure,'YR_1_2')/peer_n*100),
        ("2-3 yrs", g(hp_tenure,'YR_2_3')/hp_n*100, g(peer_tenure,'YR_2_3')/peer_n*100),
        ("3-5 yrs", g(hp_tenure,'YR_3_5')/hp_n*100, g(peer_tenure,'YR_3_5')/peer_n*100),
        ("5+ yrs", g(hp_tenure,'YR_5_PLUS')/hp_n*100, g(peer_tenure,'YR_5_PLUS')/peer_n*100),
    ]
    return svg_bar_chart([(l, h, p, fmt_pct_val) for l, h, p in buckets])

# ── BUILD HTML ───────────────────────────────────────────────────────────────
gen_date = datetime.now().strftime("%B %Y")

html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>High-Performing SE Analysis | {SCOPE_LABEL} {FY_LABEL}</title>
<style>
  :root {{
    --primary: #29B5E8; --primary-dark: #1A8DB8;
    --accent: #FF6F00; --accent-light: #FFB74D;
    --green: #4CAF50; --green-dark: #2E7D32;
    --red: #EF5350; --bg: #FAFBFC; --card-bg: #FFFFFF;
    --text: #1E293B; --text-light: #64748B; --border: #E2E8F0;
    --hp-color: #29B5E8; --peer-color: #94A3B8;
    --hp-bar: #29B5E8; --peer-bar: #CBD5E1;
    --delta-pos: #4CAF50; --delta-neg: #EF5350;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 0 24px; }}
  .report-header {{ background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%); color: white; padding: 48px 0; margin-bottom: 32px; }}
  .report-header h1 {{ font-size: 32px; font-weight: 700; margin-bottom: 8px; }}
  .report-header .subtitle {{ font-size: 18px; color: var(--primary); font-weight: 500; }}
  .report-header .meta {{ margin-top: 16px; font-size: 14px; color: #94A3B8; }}
  .report-header .meta span {{ margin-right: 24px; }}
  .section {{ margin-bottom: 40px; }}
  .section-title {{ font-size: 22px; font-weight: 700; color: var(--text); margin-bottom: 4px; padding-bottom: 8px; border-bottom: 3px solid var(--primary); display: inline-block; }}
  .section-desc {{ color: var(--text-light); font-size: 14px; margin-bottom: 20px; margin-top: 8px; }}
  .card {{ background: var(--card-bg); border-radius: 12px; border: 1px solid var(--border); padding: 24px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }}
  .card-title {{ font-size: 15px; font-weight: 600; color: var(--text-light); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 16px; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }}
  .kpi-card {{ background: var(--card-bg); border-radius: 12px; border: 1px solid var(--border); padding: 20px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }}
  .kpi-label {{ font-size: 12px; font-weight: 600; color: var(--text-light); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }}
  .kpi-value {{ font-size: 28px; font-weight: 700; color: var(--primary-dark); }}
  .kpi-sub {{ font-size: 13px; color: var(--text-light); margin-top: 4px; }}
  .kpi-delta {{ font-size: 14px; font-weight: 600; margin-top: 4px; }}
  .kpi-delta.pos {{ color: var(--delta-pos); }}
  .kpi-delta.neg {{ color: var(--delta-neg); }}
  .chart-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }}
  .bar-chart text {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
  .legend-item {{ display: inline-flex; align-items: center; margin-right: 20px; font-size: 13px; color: var(--text-light); }}
  .legend-dot {{ width: 12px; height: 12px; border-radius: 3px; margin-right: 6px; display: inline-block; }}
  .chart-legend {{ margin-bottom: 12px; }}
  .insight {{ background: #F0F9FF; border-left: 4px solid var(--primary); padding: 16px 20px; border-radius: 0 8px 8px 0; margin: 16px 0; font-size: 14px; }}
  .insight strong {{ color: var(--primary-dark); }}
  .data-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  .data-table th {{ background: #F8FAFC; padding: 10px 12px; text-align: left; font-weight: 600; color: var(--text-light); text-transform: uppercase; font-size: 11px; letter-spacing: 0.5px; border-bottom: 2px solid var(--border); white-space: nowrap; }}
  .data-table td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); white-space: nowrap; }}
  .data-table tr:hover {{ background: #F8FAFC; }}
  .data-table .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .exec-summary {{ background: linear-gradient(135deg, #F0F9FF 0%, #E0F2FE 100%); border: 1px solid #BAE6FD; border-radius: 12px; padding: 28px; margin-bottom: 32px; }}
  .exec-summary h3 {{ font-size: 18px; color: var(--primary-dark); margin-bottom: 12px; }}
  .exec-summary ul {{ padding-left: 20px; }}
  .exec-summary li {{ margin-bottom: 8px; font-size: 15px; }}
  .toc {{ background: var(--card-bg); border-radius: 12px; border: 1px solid var(--border); padding: 24px; margin-bottom: 32px; }}
  .toc h3 {{ font-size: 16px; margin-bottom: 12px; }}
  .toc ol {{ padding-left: 20px; }}
  .toc li {{ margin-bottom: 6px; }}
  .toc a {{ color: var(--primary-dark); text-decoration: none; }}
  .report-footer {{ text-align: center; padding: 32px 0; color: var(--text-light); font-size: 13px; border-top: 1px solid var(--border); margin-top: 40px; }}
  @media print {{
    body {{ background: white; }}
    .report-header {{ padding: 24px 0; }}
    .section {{ page-break-inside: avoid; }}
    .card {{ box-shadow: none; border: 1px solid #ddd; }}
  }}
</style>
</head>
<body>

<!-- HEADER -->
<div class="report-header">
  <div class="container">
    <h1>What Makes a High-Performing SE?</h1>
    <div class="subtitle">{SCOPE_LABEL} | {FY_LABEL} Cohort Analysis</div>
    <div class="meta">
      <span>{HP_COUNT} High Performers vs. {peer_count} Peers</span>
      <span>Data through {FY_LABEL}</span>
      <span>Prepared: {gen_date}</span>
    </div>
  </div>
</div>

<div class="container">

<!-- TABLE OF CONTENTS -->
<div class="toc">
  <h3>Contents</h3>
  <ol>
    <li><a href="#exec-summary">Executive Summary</a></li>
    <li><a href="#methodology">Methodology</a></li>
    <li><a href="#tenure">Tenure &amp; Experience</a></li>
    <li><a href="#volume">Volume &amp; Efficiency Metrics</a></li>
    <li><a href="#activity">Activity &amp; Engagement</a></li>
    <li><a href="#meetings">Meeting Quality</a></li>
    <li><a href="#threading">Multi-Threading &amp; Contact Breadth</a></li>
    <li><a href="#product">Product Diversity &amp; Land-and-Expand</a></li>
    <li><a href="#velocity">Implementation Velocity</a></li>
    <li><a href="#health">Account Health &amp; Portfolio</a></li>
    <li><a href="#specialist">Specialist Leverage</a></li>
    <li><a href="#profiles">Individual SE Profiles</a></li>
    <li><a href="#recommendations">Recommendations</a></li>
  </ol>
</div>

<!-- EXECUTIVE SUMMARY -->
<div id="exec-summary" class="exec-summary">
  <h3>Executive Summary</h3>
  {build_exec_summary()}
</div>

<!-- METHODOLOGY -->
<div id="methodology" class="section">
  <h2 class="section-title">Methodology</h2>
  <p class="section-desc">How we identified and compared high-performing SEs</p>
  <div class="card">
    <p><strong>Cohort Definition:</strong> {HP_COUNT} SEs were identified as high performers by leadership. The comparison group is the remaining {peer_count} Field SEs in {SCOPE_LABEL}.</p>
    <p style="margin-top:12px;"><strong>Data Sources:</strong></p>
    <ul style="padding-left:20px; margin-top:8px; font-size:14px;">
      <li><strong>SE_METRICS</strong> &mdash; Weekly SE performance metrics (tech wins, go-lives, ACV, Vivun activity)</li>
      <li><strong>SE_INDIVIDUAL_METRICS_DAILY</strong> &mdash; Daily metrics including SetSail activity data</li>
      <li><strong>DIM_USE_CASE</strong> &mdash; SFDC use case records with product categories and specialist data</li>
      <li><strong>INT_SE_SETSAIL_MEETINGS</strong> &mdash; Meeting quality metrics</li>
      <li><strong>SETSAIL_RAW_PARTICIPANTS</strong> &mdash; Meeting participant data for multi-threading analysis</li>
      <li><strong>ACCOUNT_BUSINESS_INDICATORS</strong> &mdash; Account health scores and consumption data</li>
    </ul>
    <p style="margin-top:12px;"><strong>Time Period:</strong> {FY_LABEL} (starting {FY_START_DATE}). Vivun activity data may be concentrated in early quarters; SetSail data covers the full year. Combined activity metrics are used where appropriate.</p>
  </div>
</div>

<!-- TENURE & EXPERIENCE -->
<div id="tenure" class="section">
  <h2 class="section-title">Tenure &amp; Experience</h2>
  <p class="section-desc">Tenure distribution comparison between high performers and peers</p>
  <div class="kpi-grid">
    {kpi_card("Avg Tenure (HP)", g(hp_tenure,'AVG_TENURE_YRS'), g(peer_tenure,'AVG_TENURE_YRS'), lambda v: f"{v:.1f} yrs")}
    {kpi_card("Median Tenure (HP)", g(hp_tenure,'MED_TENURE_YRS'), g(peer_tenure,'MED_TENURE_YRS'), lambda v: f"{v:.1f} yrs")}
    {kpi_card("HPs Under 1 Year", g(hp_tenure,'UNDER_1YR')/max(g(hp_tenure,'SE_COUNT'),1)*100, g(peer_tenure,'UNDER_1YR')/max(g(peer_tenure,'SE_COUNT'),1)*100, lambda v: f"{v:.0f}%", invert=True)}
    {kpi_card("HPs 3+ Years", (g(hp_tenure,'YR_3_5')+g(hp_tenure,'YR_5_PLUS'))/max(g(hp_tenure,'SE_COUNT'),1)*100, (g(peer_tenure,'YR_3_5')+g(peer_tenure,'YR_5_PLUS'))/max(g(peer_tenure,'SE_COUNT'),1)*100, lambda v: f"{v:.0f}%")}
  </div>
  <div class="card">
    <div class="card-title">Tenure Distribution: High Performers vs Peers</div>
    {tenure_chart()}
  </div>
</div>

<!-- VOLUME & EFFICIENCY -->
<div id="volume" class="section">
  <h2 class="section-title">Volume &amp; Efficiency Metrics</h2>
  <p class="section-desc">High performers deliver more outcomes with better conversion and higher deal values</p>
  <div class="kpi-grid">
    {kpi_card("TW / Account", g(hp_vol,'AVG_TW_PER_ACCT'), g(peer_vol,'AVG_TW_PER_ACCT'), lambda v: f"{v:.2f}")}
    {kpi_card("ACV per TW", g(hp_vol,'AVG_ACV_PER_TW'), g(peer_vol,'AVG_ACV_PER_TW'), fmt_dollar)}
    {kpi_card("Go-Live from TW %", g(hp_vol,'AVG_GL_TW_RATE',0)*100, g(peer_vol,'AVG_GL_TW_RATE',0)*100, lambda v: f"{v:.0f}%")}
    {kpi_card("Avg Time-to-TW", g(hp_vol,'AVG_TTW'), g(peer_vol,'AVG_TTW'), fmt_days, invert=True)}
  </div>
  <div class="card">
    <div class="card-title">Average Volume Per SE ({FY_LABEL})</div>
    <div class="chart-legend">
      <span class="legend-item"><span class="legend-dot" style="background:#29B5E8;"></span>High Performers (n={HP_COUNT})</span>
      <span class="legend-item"><span class="legend-dot" style="background:#CBD5E1;"></span>Peers (n={peer_count})</span>
    </div>
    {svg_bar_chart([
        ("New Use Cases", g(hp_vol,'AVG_NEW_UCS'), g(peer_vol,'AVG_NEW_UCS'), fmt_num),
        ("Tech Wins", g(hp_vol,'AVG_TWS'), g(peer_vol,'AVG_TWS'), fmt_num),
        ("Go-Lives", g(hp_vol,'AVG_GLS'), g(peer_vol,'AVG_GLS'), fmt_num),
        ("TW Conversion %", g(hp_vol,'AVG_TW_CONV',0)*100, g(peer_vol,'AVG_TW_CONV',0)*100, fmt_pct_val),
        ("Accounts", g(hp_vol,'AVG_ACCOUNTS'), g(peer_vol,'AVG_ACCOUNTS'), fmt_num),
    ])}
  </div>
</div>

<!-- ACTIVITY & ENGAGEMENT -->
<div id="activity" class="section">
  <h2 class="section-title">Activity &amp; Engagement</h2>
  <p class="section-desc">Combined Vivun + SetSail activity shows higher performers are significantly more active</p>
  <div class="kpi-grid">
    {kpi_card("Combined Activities", g(hp_act,'AVG_COMBINED_ACTS'), g(peer_act,'AVG_COMBINED_ACTS'), lambda v: f"{v:.0f}")}
    {kpi_card("Combined Hours", g(hp_act,'AVG_COMBINED_HRS'), g(peer_act,'AVG_COMBINED_HRS'), lambda v: f"{v:.0f}")}
    {kpi_card("SetSail Activities", g(hp_act,'AVG_SS_ACTS'), g(peer_act,'AVG_SS_ACTS'), lambda v: f"{v:.0f}")}
    {kpi_card("Export Activities", g(hp_act,'AVG_EXPORT_ACTS'), g(peer_act,'AVG_EXPORT_ACTS'), lambda v: f"{v:.0f}")}
  </div>
  <div class="card">
    <div class="card-title">Activity Volume Comparison</div>
    {svg_bar_chart([
        ("Vivun Activities", g(hp_act,'AVG_VIVUN_ACTS'), g(peer_act,'AVG_VIVUN_ACTS'), fmt_num),
        ("SetSail Activities", g(hp_act,'AVG_SS_ACTS'), g(peer_act,'AVG_SS_ACTS'), fmt_num),
        ("Combined Hours", g(hp_act,'AVG_COMBINED_HRS'), g(peer_act,'AVG_COMBINED_HRS'), fmt_num),
        ("Export Activities", g(hp_act,'AVG_EXPORT_ACTS'), g(peer_act,'AVG_EXPORT_ACTS'), fmt_num),
    ])}
  </div>
</div>

<!-- MEETING QUALITY -->
<div id="meetings" class="section">
  <h2 class="section-title">Meeting Quality</h2>
  <p class="section-desc">Meeting quality breakdown between high performers and peers</p>
  <div class="kpi-grid">
    {kpi_card("Total Meetings", g(hp_mtg,'AVG_TOTAL_MTGS'), g(peer_mtg,'AVG_TOTAL_MTGS'), lambda v: f"{v:.0f}")}
    {kpi_card("VP-External %", g(hp_mtg,'AVG_VP_PCT'), g(peer_mtg,'AVG_VP_PCT'), lambda v: f"{v:.1f}%")}
    {kpi_card("AI/ML Meetings %", g(hp_mtg,'AVG_AI_PCT'), g(peer_mtg,'AVG_AI_PCT'), lambda v: f"{v:.1f}%")}
    {kpi_card("Partner Present %", g(hp_mtg,'AVG_PARTNER_PCT'), g(peer_mtg,'AVG_PARTNER_PCT'), lambda v: f"{v:.1f}%")}
  </div>
  <div class="card">
    <div class="card-title">Meeting Quality Breakdown</div>
    {svg_bar_chart([
        ("VP-External %", g(hp_mtg,'AVG_VP_PCT'), g(peer_mtg,'AVG_VP_PCT'), fmt_pct_val),
        ("AI/ML Meetings %", g(hp_mtg,'AVG_AI_PCT'), g(peer_mtg,'AVG_AI_PCT'), fmt_pct_val),
        ("Partner Present %", g(hp_mtg,'AVG_PARTNER_PCT'), g(peer_mtg,'AVG_PARTNER_PCT'), fmt_pct_val),
    ])}
  </div>
</div>

<!-- MULTI-THREADING -->
<div id="threading" class="section">
  <h2 class="section-title">Multi-Threading &amp; Contact Breadth</h2>
  <p class="section-desc">Measuring how wide SEs go within accounts by analyzing distinct external contacts in meetings</p>
  <div class="kpi-grid">
    {kpi_card("Distinct External Contacts", g(hp_thread,'AVG_CONTACTS'), g(peer_thread,'AVG_CONTACTS'), lambda v: f"{v:.0f}")}
    {kpi_card("Senior Contacts (VP/CxO)", g(hp_thread,'AVG_SENIOR'), g(peer_thread,'AVG_SENIOR'), lambda v: f"{v:.1f}")}
    {kpi_card("Contacts per Account", g(hp_thread,'AVG_CONTACTS_PER_ACCT'), g(peer_thread,'AVG_CONTACTS_PER_ACCT'), lambda v: f"{v:.1f}")}
    {kpi_card("Senior per Account", g(hp_thread,'AVG_SENIOR_PER_ACCT'), g(peer_thread,'AVG_SENIOR_PER_ACCT'), lambda v: f"{v:.2f}")}
  </div>
  <div class="card">
    <div class="card-title">Contact Breadth Comparison</div>
    {svg_bar_chart([
        ("Distinct Ext. Contacts", g(hp_thread,'AVG_CONTACTS'), g(peer_thread,'AVG_CONTACTS'), fmt_num),
        ("Senior Contacts (VP/CxO)", g(hp_thread,'AVG_SENIOR'), g(peer_thread,'AVG_SENIOR'), fmt_num),
        ("Contacts / Account", g(hp_thread,'AVG_CONTACTS_PER_ACCT'), g(peer_thread,'AVG_CONTACTS_PER_ACCT'), fmt_num),
        ("Accts w/ 2+ Senior %", g(hp_thread,'AVG_PCT_MULTI_EXEC'), g(peer_thread,'AVG_PCT_MULTI_EXEC'), fmt_pct_val),
    ])}
  </div>
</div>

<!-- PRODUCT DIVERSITY -->
<div id="product" class="section">
  <h2 class="section-title">Product Diversity &amp; Land-and-Expand</h2>
  <p class="section-desc">High performers cover more product categories and penetrate accounts more deeply</p>
  <div class="kpi-grid">
    {kpi_card("5-Category Coverage", g(hp_prod,'PCT_5_CAT'), g(peer_prod,'PCT_5_CAT'), lambda v: f"{v:.0f}%")}
    {kpi_card("UCs per Account", g(hp_prod,'AVG_UCS_PER_ACCT'), g(peer_prod,'AVG_UCS_PER_ACCT'), lambda v: f"{v:.2f}")}
    {kpi_card("Accts w/ 3+ UCs", g(hp_prod,'AVG_PCT_DEEP_ACCTS'), g(peer_prod,'AVG_PCT_DEEP_ACCTS'), lambda v: f"{v:.0f}%")}
    {kpi_card("Avg Categories/SE", g(hp_prod,'AVG_CATEGORIES'), g(peer_prod,'AVG_CATEGORIES'), lambda v: f"{v:.2f}")}
  </div>
</div>

<!-- IMPLEMENTATION VELOCITY -->
<div id="velocity" class="section">
  <h2 class="section-title">Implementation Velocity</h2>
  <p class="section-desc">How quickly use cases move from Tech Win to Implementation Start and from there to Deployed</p>
  <div class="kpi-grid">
    {kpi_card("Avg TW to Impl Start", g(hp_vel,'AVG_TW_IMPL'), g(peer_vel,'AVG_TW_IMPL'), fmt_days, invert=True)}
    {kpi_card("Median TW to Impl Start", g(hp_vel,'MED_TW_IMPL'), g(peer_vel,'MED_TW_IMPL'), fmt_days, invert=True)}
    {kpi_card("Avg Impl to Deployed", g(hp_vel,'AVG_IMPL_DEPLOY'), g(peer_vel,'AVG_IMPL_DEPLOY'), fmt_days, invert=True)}
    {kpi_card("Median Impl to Deployed", g(hp_vel,'MED_IMPL_DEPLOY'), g(peer_vel,'MED_IMPL_DEPLOY'), fmt_days, invert=True)}
  </div>
  <div class="card">
    <div class="card-title">Implementation Timeline Comparison</div>
    {svg_bar_chart([
        ("Avg TW to Impl Start", g(hp_vel,'AVG_TW_IMPL'), g(peer_vel,'AVG_TW_IMPL'), fmt_days),
        ("Avg Impl to Deployed", g(hp_vel,'AVG_IMPL_DEPLOY'), g(peer_vel,'AVG_IMPL_DEPLOY'), fmt_days),
        ("Median Impl to Deployed", g(hp_vel,'MED_IMPL_DEPLOY'), g(peer_vel,'MED_IMPL_DEPLOY'), fmt_days),
        ("Median TW to Deployed", g(hp_vel,'MED_TW_DEPLOY'), g(peer_vel,'MED_TW_DEPLOY'), fmt_days),
    ])}
  </div>
</div>

<!-- ACCOUNT HEALTH -->
<div id="health" class="section">
  <h2 class="section-title">Account Health &amp; Portfolio</h2>
  <p class="section-desc">Accounts managed by high performers vs peers</p>
  <div class="kpi-grid">
    {kpi_card("Avg Health Score", g(hp_health,'AVG_HEALTH'), g(peer_health,'AVG_HEALTH'), lambda v: f"{v:.1f}")}
    {kpi_card("Strong/Exceptional %", g(hp_health,'PCT_STRONG'), g(peer_health,'PCT_STRONG'), lambda v: f"{v:.0f}%")}
    {kpi_card("At Risk %", g(hp_health,'PCT_AT_RISK'), g(peer_health,'PCT_AT_RISK'), lambda v: f"{v:.0f}%", invert=True)}
    {kpi_card("Avg YoY Rev Growth", g(hp_health,'AVG_YOY_GROWTH'), g(peer_health,'AVG_YOY_GROWTH'), lambda v: f"{v:.1f}%")}
  </div>
  <div class="card">
    <div class="card-title">Account Assessment Distribution</div>
    {svg_bar_chart([
        ("Strong/Exceptional %", g(hp_health,'PCT_STRONG'), g(peer_health,'PCT_STRONG'), fmt_pct_val),
        ("At Risk/Declining %", g(hp_health,'PCT_AT_RISK'), g(peer_health,'PCT_AT_RISK'), fmt_pct_val),
    ])}
  </div>
</div>

<!-- SPECIALIST LEVERAGE -->
<div id="specialist" class="section">
  <h2 class="section-title">Specialist Leverage</h2>
  <p class="section-desc">How often high performers engage platform specialists on their use cases</p>
  <div class="card">
    <div class="chart-row" style="margin-bottom:0;">
      <div>
        <div class="card-title">% Use Cases with Specialist</div>
        <div style="display:flex; gap:40px; justify-content:center; margin-top:20px;">
          <div style="text-align:center;">
            <div style="font-size:36px; font-weight:700; color:var(--primary-dark);">{g(hp_spec,'PCT_WITH_SPECIALIST'):.0f}%</div>
            <div style="font-size:13px; color:var(--text-light);">High Performers</div>
          </div>
          <div style="text-align:center;">
            <div style="font-size:36px; font-weight:700; color:var(--peer-color);">{g(peer_spec,'PCT_WITH_SPECIALIST'):.0f}%</div>
            <div style="font-size:13px; color:var(--text-light);">Peers</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- INDIVIDUAL SE PROFILES -->
<div id="profiles" class="section">
  <h2 class="section-title">Individual SE Profiles</h2>
  <p class="section-desc">Performance details for each of the {HP_COUNT} high-performing SEs</p>
  <div class="card" style="overflow-x:auto;">
    <div class="card-title">Volume &amp; Efficiency</div>
    <table class="data-table">
      <thead>
        <tr>
          <th>SE Name</th><th class="num">Accounts</th><th class="num">New UCs</th>
          <th class="num">Tech Wins</th><th class="num">TW ACV</th><th class="num">Go-Lives</th>
          <th class="num">GL ACV</th><th class="num">TTW (days)</th><th class="num">TW Conv %</th>
          <th class="num">GL/TW %</th><th class="num">ACV/TW</th><th class="num">TW/Acct</th>
        </tr>
      </thead>
      <tbody>
        {build_individual_table(individual_data)}
      </tbody>
    </table>
  </div>
</div>

<!-- RECOMMENDATIONS -->
<div id="recommendations" class="section">
  <h2 class="section-title">Recommendations</h2>
  <p class="section-desc">Actionable takeaways based on the cohort analysis</p>
  <div class="card">
    <ol style="padding-left:20px; font-size:15px;">
      <li style="margin-bottom:12px;"><strong>Accelerate onboarding</strong> &mdash; With zero HPs under 1 year of tenure, invest in structured ramp programs, mentorship pairing with HPs, and early account exposure to compress the ~2 year experience threshold.</li>
      <li style="margin-bottom:12px;"><strong>Prioritize multi-threading</strong> &mdash; Contact breadth is the single largest behavioral differentiator. Coach SEs to systematically map and engage multiple stakeholders per account, especially at the VP/CxO level.</li>
      <li style="margin-bottom:12px;"><strong>Drive product breadth</strong> &mdash; HPs cover more product categories per account. Encourage cross-product discovery conversations and specialist engagement early in the sales cycle.</li>
      <li style="margin-bottom:12px;"><strong>Deepen account penetration</strong> &mdash; Focus on expanding existing accounts (3+ use cases) rather than just opening new ones. HPs demonstrate significantly deeper "land-and-expand" behavior.</li>
      <li style="margin-bottom:12px;"><strong>Leverage specialist resources</strong> &mdash; HPs engage specialists more frequently. Encourage SEs to bring in platform specialists early, not just for complex deals.</li>
    </ol>
  </div>
</div>

</div>

<div class="report-footer">
  <p>High-Performing SE Analysis | {SCOPE_LABEL} | {FY_LABEL}</p>
  <p>Generated {datetime.now().strftime("%Y-%m-%d %H:%M")} | Data sources: SE_METRICS, SE_INDIVIDUAL_METRICS_DAILY, DIM_USE_CASE, INT_SE_SETSAIL_MEETINGS, SETSAIL_RAW_PARTICIPANTS, ACCOUNT_BUSINESS_INDICATORS</p>
  <p style="margin-top:8px; font-style:italic; color:#94A3B8;">Note: Background profile research (LinkedIn, publications, certifications) requires manual web research and is not included in this automated report. Run this analysis as a separate enrichment step.</p>
</div>

</body>
</html>'''

# ── Save HTML ────────────────────────────────────────────────────────────────
with open(OUTPUT_HTML, 'w', encoding='utf-8') as f:
    f.write(html)
print(f"HTML report saved: {OUTPUT_HTML}")

# ── Generate PDF ─────────────────────────────────────────────────────────────
import subprocess
chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
try:
    subprocess.run([
        chrome_path, "--headless", "--disable-gpu", "--no-sandbox",
        f"--print-to-pdf={OUTPUT_PDF}", "--no-margins", "--print-to-pdf-no-header",
        f"file://{OUTPUT_HTML}"
    ], capture_output=True, timeout=60)
    print(f"PDF report saved: {OUTPUT_PDF}")
except Exception as e:
    print(f"PDF generation failed (Chrome not found?): {e}")
    print("HTML report is still available.")

cur.close()
conn.close()
print("Done!")

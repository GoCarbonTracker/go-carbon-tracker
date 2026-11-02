# Comprehensive Metrics Specification for ESG & Corporate Disclosure Extraction

**Document Version:** 1.0
**Date Created:** 2026-11-02
**Purpose:** Define all metrics to be extracted from corporate sustainability and annual reports
**Target:** GoCarbonTracker extraction engine enhancement
**Total Metrics:** 112

---

## 📋 Table of Contents

1. [Environmental Metrics (13)](#environmental-metrics)
2. [Social Metrics (18)](#social-metrics)
3. [Governance Metrics (13)](#governance-metrics)
4. [Financial Metrics (30)](#financial-metrics)
5. [Operational Metrics (22)](#operational-metrics)
6. [Market & Customer Metrics (16)](#market--customer-metrics)
7. [Verification Checklist](#verification-checklist)

---

## 🌍 ENVIRONMENTAL METRICS

### **Total: 13 Metrics**

| # | Metric Key | Display Name | Description | Unit | Status | Notes |
|----|-----------|--------------|-------------|------|--------|-------|
| 1 | ghg_scope_1 | Scope 1 Emissions | Direct GHG emissions from owned/controlled sources | tCO2e | ✅ EXISTING | Already in codebase |
| 2 | ghg_scope_2_location | Scope 2 Emissions (Location-Based) | Indirect emissions from purchased electricity (location-based) | tCO2e | ✅ EXISTING | Already in codebase |
| 3 | ghg_scope_2_market | Scope 2 Emissions (Market-Based) | Indirect emissions from purchased electricity (market-based) | tCO2e | ✅ EXISTING | Already in codebase |
| 4 | ghg_scope_2 | Scope 2 Emissions (Generic) | Scope 2 without location/market distinction | tCO2e | ✅ EXISTING | Already in codebase |
| 5 | ghg_scope_1_2 | Combined Scope 1 & 2 | Total of Scope 1 and Scope 2 emissions | tCO2e | ✅ EXISTING | Already in codebase |
| 6 | ghg_scope_3 | Scope 3 Emissions | Indirect emissions from value chain | tCO2e | ✅ EXISTING | Already in codebase |
| 7 | ghg_scope_3_category_1 | Scope 3 Category 1 | Purchased goods and services | tCO2e | 🔄 NEW | Add specific Scope 3 categories |
| 8 | ghg_scope_3_category_4 | Scope 3 Category 4 | Upstream transportation & distribution | tCO2e | 🔄 NEW | Supplier emissions |
| 9 | energy_total | Total Energy Consumption | All energy from all sources | GJ, MWh, kWh | ✅ EXISTING | Already in codebase |
| 10 | energy_renewable | Renewable Energy Consumed | Energy from renewable sources | GJ, MWh, kWh | ✅ EXISTING | Already in codebase |
| 11 | energy_non_renewable | Non-Renewable Energy Consumed | Energy from non-renewable sources | GJ, MWh, kWh | ✅ EXISTING | Already in codebase |
| 12 | water_total | Total Water Consumption | Water withdrawal + consumption combined | m³, ML, kL | 🔄 NEW | Combine withdrawal/consumption |
| 13 | waste_total | Total Waste Generated | All waste streams | tonnes, kg | ✅ EXISTING | Already in codebase |
| 14 | waste_diverted_landfill | Waste Diverted from Landfill | Percentage of waste recycled/composted | % | 🔄 NEW | Waste management metric |
| 15 | water_recycled | Water Recycled/Reused | Water reused in operations | % | 🔄 NEW | Circular economy indicator |
| 16 | emissions_intensity | Emissions Intensity | GHG per unit output/revenue | tCO2e/€M, tCO2e/unit | 🔄 NEW | Efficiency metric |
| 17 | renewable_energy_share | Renewable Energy Share | Percentage of energy from renewables | % | 🔄 NEW | Clean energy indicator |
| 18 | carbon_reduction_target | Carbon Reduction Target | Committed emissions reduction percentage | % | 🔄 NEW | Forward-looking commitment |
| 19 | net_zero_target_year | Net Zero Target Year | Year company commits to reach net zero | Year (YYYY) | 🔄 NEW | Long-term goal |

**Environmental Metrics Subtotal: 19 (13 existing + 6 new)**

---

## 👥 SOCIAL METRICS

### **Total: 18 Metrics**

| # | Metric Key | Display Name | Description | Unit | Status | Notes |
|----|-----------|--------------|-------------|------|--------|-------|
| 1 | employees_total | Total Employees | Total headcount | # | 🔄 NEW | Basic operational metric |
| 2 | employees_by_gender_male | Male Employees | Male headcount | # | 🔄 NEW | Diversity tracking |
| 3 | employees_by_gender_female | Female Employees | Female headcount | # | 🔄 NEW | Diversity tracking |
| 4 | employees_by_gender_other | Non-Binary Employees | Non-binary/other gender employees | # | 🔄 NEW | Diversity tracking |
| 5 | women_in_workforce | Women in Workforce | Percentage of women employees | % | 🔄 NEW | Gender diversity |
| 6 | women_in_leadership | Women in Leadership | Percentage of women in management roles | % | 🔄 NEW | Senior leadership diversity |
| 7 | minority_representation | Minority Representation | Percentage of underrepresented minorities | % | 🔄 NEW | Ethnic diversity |
| 8 | pay_equity_gap_gender | Gender Pay Gap | Average wage gap between men and women | % | 🔄 NEW | Equity metric |
| 9 | ceo_median_pay_ratio | CEO-to-Median Employee Pay Ratio | CEO compensation vs median employee | Ratio (x:1) | 🔄 NEW | Income inequality |
| 10 | health_safety_incidents | H&S Incidents | Reportable workplace incidents | # | 🔄 NEW | Safety performance |
| 11 | lost_time_injury_rate | LTIR (Lost Time Injury Rate) | Work-related injuries leading to lost time | Rate/1000 | 🔄 NEW | Safety KPI |
| 12 | training_hours_per_employee | Training Hours per Employee | Average annual training hours | hours | 🔄 NEW | Development investment |
| 13 | voluntary_turnover_rate | Voluntary Turnover Rate | Employees who chose to leave | % | 🔄 NEW | Retention metric |
| 14 | involuntary_turnover_rate | Involuntary Turnover Rate | Employees terminated/laid off | % | 🔄 NEW | HR metric |
| 15 | suppliers_audited | Suppliers Audited | Percentage of suppliers with compliance audit | % | 🔄 NEW | Supply chain governance |
| 16 | suppliers_diverse | Supplier Diversity | Percentage diverse suppliers (women/minority-owned) | % | 🔄 NEW | Supplier equity |
| 17 | fair_trade_suppliers | Fair Trade Certification | Percentage of suppliers with fair trade cert | % | 🔄 NEW | Ethical sourcing |
| 18 | community_investment | Community Investment | Total charitable/community spending | € | 🔄 NEW | Social impact |

**Social Metrics Subtotal: 18 (0 existing + 18 new)**

---

## 🏛️ GOVERNANCE METRICS

### **Total: 13 Metrics**

| # | Metric Key | Display Name | Description | Unit | Status | Notes |
|----|-----------|--------------|-------------|------|--------|-------|
| 1 | board_size | Board Size | Total number of board members | # | 🔄 NEW | Governance structure |
| 2 | board_independence | Board Independence | Percentage of independent directors | % | 🔄 NEW | Board autonomy |
| 3 | board_women | Women on Board | Percentage of female board members | % | 🔄 NEW | Board diversity |
| 4 | board_diversity_ethnicity | Board Ethnic Diversity | Percentage of diverse ethnicities on board | % | 🔄 NEW | Board diversity |
| 5 | board_tenure_average | Average Board Tenure | Average years serving on board | years | 🔄 NEW | Experience level |
| 6 | ceo_salary | CEO Base Salary | Annual CEO salary (fixed compensation) | € | 🔄 NEW | Executive comp |
| 7 | ceo_bonus | CEO Bonus | Annual CEO performance bonus | € | 🔄 NEW | Executive comp |
| 8 | ceo_stock_options | CEO Stock Options | Value of stock awards/options granted | € | 🔄 NEW | Executive comp |
| 9 | executive_team_diversity_women | Executive Team Women | Percentage of women in C-suite | % | 🔄 NEW | Leadership diversity |
| 10 | ethics_training_completion | Ethics Training Completion | Percentage of employees completing ethics training | % | 🔄 NEW | Compliance metric |
| 11 | regulatory_violations | Regulatory Violations | Number of legal/regulatory violations | # | 🔄 NEW | Risk metric |
| 12 | regulatory_fines | Regulatory Fines | Total monetary fines from regulators | € | 🔄 NEW | Compliance cost |
| 13 | auditor_fees | Auditor Fees | Total annual external auditor fees | € | 🔄 NEW | Audit cost |

**Governance Metrics Subtotal: 13 (0 existing + 13 new)**

---

## 💰 FINANCIAL METRICS

### **Total: 30 Metrics**

| # | Metric Key | Display Name | Description | Unit | Status | Notes |
|----|-----------|--------------|-------------|------|--------|-------|
| **Revenue & Profitability** |
| 1 | revenue_total | Total Revenue | Annual revenue/sales | €M | 🔄 NEW | P&L top line |
| 2 | revenue_by_segment | Revenue by Segment | Revenue broken down by business unit | €M | 🔄 NEW | Segment reporting |
| 3 | revenue_by_geography | Revenue by Geography | Revenue by region/country | €M | 🔄 NEW | Geographic analysis |
| 4 | gross_profit | Gross Profit | Revenue minus cost of goods sold | €M | 🔄 NEW | P&L metric |
| 5 | gross_margin | Gross Margin | Gross profit as % of revenue | % | 🔄 NEW | Profitability ratio |
| 6 | operating_income | Operating Income (EBIT) | Earnings before interest & taxes | €M | 🔄 NEW | Operating profit |
| 7 | operating_margin | Operating Margin | Operating income as % of revenue | % | 🔄 NEW | Profitability ratio |
| 8 | ebitda | EBITDA | Earnings before interest, taxes, depreciation, amortization | €M | 🔄 NEW | Cash generation metric |
| 9 | net_income | Net Income | Bottom-line profit after all expenses | €M | 🔄 NEW | Net profit |
| 10 | net_margin | Net Margin | Net income as % of revenue | % | 🔄 NEW | Profitability ratio |
| 11 | earnings_per_share | Earnings Per Share (EPS) | Net income divided by shares outstanding | € | 🔄 NEW | Per-share metric |
| **Balance Sheet** |
| 12 | total_assets | Total Assets | All company assets | €M | 🔄 NEW | Balance sheet |
| 13 | current_assets | Current Assets | Short-term assets (liquid) | €M | 🔄 NEW | Liquidity measure |
| 14 | cash_equivalents | Cash & Equivalents | Liquid cash on hand | €M | 🔄 NEW | Liquidity measure |
| 15 | accounts_receivable | Accounts Receivable | Money owed by customers | €M | 🔄 NEW | Working capital |
| 16 | inventory | Inventory | Goods held for sale | €M | 🔄 NEW | Working capital |
| 17 | current_liabilities | Current Liabilities | Short-term obligations | €M | 🔄 NEW | Near-term debt |
| 18 | total_debt | Total Debt | Long-term + short-term debt | €M | 🔄 NEW | Leverage metric |
| 19 | shareholders_equity | Shareholders' Equity | Assets minus liabilities | €M | 🔄 NEW | Net worth |
| 20 | book_value_per_share | Book Value Per Share | Equity divided by shares outstanding | € | 🔄 NEW | Per-share metric |
| **Cash Flow** |
| 21 | operating_cash_flow | Operating Cash Flow | Cash from core operations | €M | 🔄 NEW | Cash generation |
| 22 | free_cash_flow | Free Cash Flow | Operating cash flow minus CapEx | €M | 🔄 NEW | Discretionary cash |
| 23 | capital_expenditure | Capital Expenditure (CapEx) | Investment in fixed assets | €M | 🔄 NEW | Growth investment |
| 24 | dividends_paid | Dividends Paid | Shareholder distributions | €M | 🔄 NEW | Return to shareholders |
| **Ratios & Metrics** |
| 25 | debt_to_equity_ratio | Debt-to-Equity Ratio | Total debt divided by equity | Ratio | 🔄 NEW | Leverage measure |
| 26 | current_ratio | Current Ratio | Current assets / current liabilities | Ratio | 🔄 NEW | Liquidity ratio |
| 27 | roe | Return on Equity (ROE) | Net income / shareholders equity | % | 🔄 NEW | Profitability ratio |
| 28 | roa | Return on Assets (ROA) | Net income / total assets | % | 🔄 NEW | Asset efficiency |
| 29 | days_sales_outstanding | Days Sales Outstanding (DSO) | Average days to collect receivables | days | 🔄 NEW | Working capital |
| 30 | dividend_payout_ratio | Dividend Payout Ratio | Dividends as % of net income | % | 🔄 NEW | Distribution policy |

**Financial Metrics Subtotal: 30 (0 existing + 30 new)**

---

## ⚙️ OPERATIONAL METRICS

### **Total: 22 Metrics**

| # | Metric Key | Display Name | Description | Unit | Status | Notes |
|----|-----------|--------------|-------------|------|--------|-------|
| **Customer Metrics** |
| 1 | active_customers | Active Customers | Total customers at period end | # (M) | 🔄 NEW | Customer base size |
| 2 | new_customers_acquired | New Customers Acquired | New customer additions in period | # (M) | 🔄 NEW | Growth metric |
| 3 | customer_retention_rate | Customer Retention Rate | Percentage of customers retained | % | 🔄 NEW | Churn inverse |
| 4 | customer_churn_rate | Customer Churn Rate | Percentage of customers lost | % | 🔄 NEW | Attrition metric |
| 5 | revenue_per_customer | Revenue Per Customer | Average annual revenue per customer | € | 🔄 NEW | Customer value |
| 6 | average_order_value | Average Order Value (AOV) | Average transaction size | € | 🔄 NEW | Transaction metric |
| 7 | customer_lifetime_value | Customer Lifetime Value (CLV) | Total expected lifetime profit per customer | € | 🔄 NEW | Long-term value |
| 8 | net_promoter_score | Net Promoter Score (NPS) | Customer recommendation likelihood | Points (0-100) | 🔄 NEW | Satisfaction metric |
| 9 | customer_satisfaction | Customer Satisfaction Score | Overall customer satisfaction rating | % or Points | 🔄 NEW | Quality metric |
| **Operational Efficiency** |
| 10 | orders_per_day | Orders Processed Per Day | Average daily order volume | # | 🔄 NEW | Throughput metric |
| 11 | delivery_on_time_rate | On-Time Delivery Rate | Percentage of orders delivered on schedule | % | 🔄 NEW | Service quality |
| 12 | returns_refunds_rate | Returns/Refunds Rate | Percentage of orders returned/refunded | % | 🔄 NEW | Quality metric |
| 13 | delivery_cost_per_order | Delivery Cost Per Order | Average logistics cost per order | € | 🔄 NEW | Cost metric |
| 14 | fulfillment_centers | Number of Fulfillment Centers | Total distribution/fulfillment facilities | # | 🔄 NEW | Capacity measure |
| 15 | production_capacity | Production Capacity | Maximum units per day/week | # | 🔄 NEW | Operational limit |
| **Supply Chain** |
| 16 | supplier_count | Total Suppliers | Number of active suppliers | # | 🔄 NEW | Supply base |
| 17 | supplier_diversity_representation | Supplier Diversity | Percentage of women/minority-owned suppliers | % | 🔄 NEW | Equity metric |
| **Headcount & Productivity** |
| 18 | revenue_per_employee | Revenue Per Employee | Revenue divided by total employees | €K | 🔄 NEW | Productivity metric |
| 19 | inventory_turnover | Inventory Turnover Ratio | Cost of goods sold / average inventory | Ratio | 🔄 NEW | Efficiency metric |
| 20 | days_inventory_outstanding | Days Inventory Outstanding (DIO) | Days inventory sits before sale | days | 🔄 NEW | Inventory metric |
| 21 | kitchen_utilization_rate | Kitchen Utilization Rate | Percentage of production capacity used | % | 🔄 NEW | Asset utilization |
| 22 | employee_headcount_by_region | Headcount by Region | Employees broken down by geography | # | 🔄 NEW | Organizational structure |

**Operational Metrics Subtotal: 22 (0 existing + 22 new)**

---

## 📈 MARKET & CUSTOMER METRICS

### **Total: 16 Metrics**

| # | Metric Key | Display Name | Description | Unit | Status | Notes |
|----|-----------|--------------|-------------|------|--------|-------|
| **Market Position** |
| 1 | market_share | Market Share | Company's percentage of total market | % | 🔄 NEW | Competitive position |
| 2 | market_penetration | Market Penetration | Percentage of addressable market captured | % | 🔄 NEW | Growth potential |
| 3 | market_growth_rate | Market Growth Rate | Year-over-year market growth | % | 🔄 NEW | Industry trends |
| 4 | competitive_rank | Competitive Market Position | Rank among competitors (1st, 2nd, etc) | Rank | 🔄 NEW | Competitive standing |
| **Digital & Brand** |
| 5 | app_downloads | App Downloads | Total mobile app downloads | #M | 🔄 NEW | Digital engagement |
| 6 | app_rating | App Rating | Average app store rating | Stars (1-5) | 🔄 NEW | User satisfaction |
| 7 | website_monthly_users | Website Monthly Users | Unique monthly website visitors | #M | 🔄 NEW | Digital traffic |
| 8 | mobile_desktop_split | Mobile vs Desktop Orders | Percentage of orders via mobile | % | 🔄 NEW | Channel mix |
| 9 | brand_awareness | Brand Awareness | Percentage of target market aware of brand | % | 🔄 NEW | Marketing metric |
| **Investor Metrics** |
| 10 | stock_price | Stock Price | Current share price | € | 🔄 NEW | Market value |
| 11 | market_capitalization | Market Capitalization | Total equity market value | €B | 🔄 NEW | Company valuation |
| 12 | analyst_coverage | Analyst Coverage | Number of equity analysts covering company | # | 🔄 NEW | Interest metric |
| 13 | analyst_price_target | Average Analyst Price Target | Consensus price target from analysts | € | 🔄 NEW | Valuation metric |
| 14 | analyst_rating | Average Analyst Rating | Consensus rating (Buy/Hold/Sell) | Rating | 🔄 NEW | Sentiment metric |
| **ESG Ratings** |
| 15 | esg_rating_msci | MSCI ESG Rating | Third-party ESG rating from MSCI | Rating (A-CCC) | 🔄 NEW | ESG credibility |
| 16 | esg_score_sustainalytics | Sustainalytics ESG Score | Third-party ESG score from Sustainalytics | Score (0-100) | 🔄 NEW | ESG credibility |

**Market & Customer Metrics Subtotal: 16 (0 existing + 16 new)**

---

## 📊 SUMMARY BY STATUS

| Status | Count | Details |
|--------|-------|---------|
| ✅ EXISTING (Already in codebase) | 13 | GHG Scope 1, 2, 3; Energy; Waste |
| 🔄 NEW (Need to be designed) | 99 | All other categories |
| **TOTAL** | **112** | Comprehensive ESG + Financial + Operational |

---

## ✅ VERIFICATION CHECKLIST

When developers implement each metric, verify:

### **For Each Metric, Verify:**

- [ ] **Metric Key**: Correct identifier used in code
- [ ] **Extraction Rule**: Pattern matching works on test documents
- [ ] **Unit Detection**: Units correctly recognized and normalized
- [ ] **Unit Conversion**: Conversions to base units work (if applicable)
- [ ] **Period Detection**: Reporting period correctly identified
- [ ] **Boundary Identification**: Standalone/consolidated distinction captured
- [ ] **Bounding Box**: Exact PDF coordinates stored
- [ ] **Source Match**: `matched` / `cited` / `unresolved` status correct
- [ ] **Test Case**: At least 3 real report examples tested
- [ ] **Edge Cases**: Negative numbers, parentheses, footnotes handled

### **Post-Implementation Test Plan:**

1. **Unit Test**: Each metric extracts correctly from synthetic tables
2. **Integration Test**: Metrics extract from real annual reports
3. **Accuracy Test**: Spot-check 20+ extracted values against PDF source
4. **Cross-Report Test**: Same metric from different companies matches correctly
5. **Period Test**: Multi-year metrics harmonize correctly across reports
6. **Boundary Test**: Standalone vs consolidated metrics differentiate properly

---

## 🚀 IMPLEMENTATION RECOMMENDATIONS

### **Priority 1 (MVP): 35 metrics**
1. All Environmental (6 core environmental)
2. Top Financial (12): Revenue, profit, key ratios
3. Top Operational (8): Customers, churn, capacity
4. Top Social (5): Headcount, diversity, training
5. Top Governance (4): Board size, compensation ratios

### **Priority 2 (v1.0): 42 metrics**
Add 42 additional metrics from all categories

### **Priority 3 (v1.1): 35 metrics**
Add remaining specialized metrics

---

## 📝 DEVELOPER NOTES

### **Key Implementation Details:**

1. **Unit Normalization**: Use existing unit converter but expand for financial currencies (EUR, USD, INR, GBP)
2. **Metric Ambiguity**: Some metrics may match multiple patterns (e.g., "revenue" vs "total revenue") — use confidence scoring
3. **Regional Variations**: Indian reports use Crore/Lakh; handle this in parsing
4. **Period Harmonization**: FY vs Calendar year; Q1-Q4 vs H1-H2 etc.
5. **Boundary Handling**: Mark metrics as `standalone`, `consolidated`, or `unknown`
6. **Restatement Tracking**: Flag when same metric has different values across years (for same period)

---

**End of Specification**
**Questions?** Contact sustainability team or file issue in development tracker.


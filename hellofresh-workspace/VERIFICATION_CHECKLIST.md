# Metrics Implementation & Verification Checklist

**Document Version:** 1.0
**Total Metrics to Implement:** 112
**Already Implemented:** 13
**New to Implement:** 99

---

## 📋 IMPLEMENTATION PHASES

### **Phase 1: Core ESG Metrics (Priority: CRITICAL + HIGH)**
**Target:** 40 metrics
**Timeline:** Week 1-2

- [ ] Environmental: 6 metrics
  - [ ] ghg_scope_3_category_1
  - [ ] ghg_scope_3_category_4
  - [ ] water_total
  - [ ] waste_diverted_landfill
  - [ ] renewable_energy_share
  - [ ] net_zero_target_year

- [ ] Social: 8 metrics
  - [ ] employees_total
  - [ ] women_in_workforce
  - [ ] women_in_leadership
  - [ ] health_safety_incidents
  - [ ] lost_time_injury_rate
  - [ ] training_hours_per_employee
  - [ ] voluntary_turnover_rate
  - [ ] suppliers_audited

- [ ] Governance: 5 metrics
  - [ ] board_size
  - [ ] board_independence
  - [ ] board_women
  - [ ] executive_team_diversity_women
  - [ ] regulatory_violations
  - [ ] regulatory_fines

- [ ] Financial: 15 metrics
  - [ ] revenue_total
  - [ ] gross_profit
  - [ ] operating_income
  - [ ] ebitda
  - [ ] net_income
  - [ ] total_assets
  - [ ] cash_equivalents
  - [ ] total_debt
  - [ ] shareholders_equity
  - [ ] operating_cash_flow
  - [ ] free_cash_flow
  - [ ] capital_expenditure
  - [ ] debt_to_equity_ratio
  - [ ] roe
  - [ ] roa

- [ ] Operational: 6 metrics
  - [ ] active_customers
  - [ ] new_customers_acquired
  - [ ] customer_retention_rate
  - [ ] customer_churn_rate
  - [ ] revenue_per_customer
  - [ ] average_order_value

---

### **Phase 2: Extended Financial & Operational (Priority: HIGH + MEDIUM)**
**Target:** 35 metrics
**Timeline:** Week 3

- [ ] Financial: 15 metrics (remaining)
- [ ] Operational: 16 metrics (remaining)
- [ ] Market: 4 metrics (critical)

---

### **Phase 3: Complete Implementation (Priority: MEDIUM + LOW)**
**Target:** 24 metrics
**Timeline:** Week 4

- [ ] Governance: 8 metrics (remaining)
- [ ] Social: 10 metrics (remaining)
- [ ] Environmental: 3 metrics (remaining)
- [ ] Market: 12 metrics (remaining)

---

## ✅ PER-METRIC VERIFICATION CHECKLIST

For **each metric**, developers must verify:

### **Code Implementation**
- [ ] Metric key correctly defined in `gct/stages/match.py` METRICS tuple
- [ ] Pattern matching rules added to extraction engine
- [ ] Unit normalization handles all unit variants
- [ ] Unit conversion factors in UNITS dictionary (if applicable)
- [ ] Fallback handling for missing units

### **Extraction Rules**
- [ ] Rule detects metric from table headers
- [ ] Rule detects metric from text/paragraphs
- [ ] Rule handles synonyms/variations
- [ ] Rule excludes false positives (e.g., "revenue growth %" vs "revenue")
- [ ] Rule case-insensitive matching
- [ ] Rule handles footnotes/superscripts

### **Period & Boundary Handling**
- [ ] Period detection works (FY, Calendar year, Q1-Q4)
- [ ] Boundary detection (standalone vs consolidated)
- [ ] Multi-year tracking works correctly
- [ ] Period harmonization across reports

### **Bounding Box & Evidence**
- [ ] PDF coordinates correctly stored
- [ ] Source match status: `matched` / `cited` / `unresolved` correct
- [ ] Box generation works for table cells
- [ ] Box generation works for text figures

### **Test Coverage**
- [ ] Unit test: Synthetic table extraction
- [ ] Integration test: Real annual report extraction
- [ ] Edge case: Negative numbers
- [ ] Edge case: Parenthetical notation (accounting format)
- [ ] Edge case: Different number formats (Western vs Indian)
- [ ] Edge case: Missing units
- [ ] Edge case: Footnotes/superscripts

---

## 🧪 BATCH VERIFICATION TESTS

### **Test 1: Synthetic Data Test**
```
Create synthetic PDF with all 112 metrics in different formats
Run gct read && gct extract && gct match
Verify: 95%+ extraction rate, correct metric assignment
Expected: <5% unmapped metrics
```

### **Test 2: HelloFresh Annual Report**
```
Run against HelloFresh 2025 Annual Report (already in workspace)
Verify: All financial metrics extract correctly
Cross-check: 20+ values manually against PDF source
Expected: 100% accuracy on sampled metrics
```

### **Test 3: Multi-Report Harmonization**
```
Load 3 years of reports from same company
Verify: Same metric across years harmonizes correctly
Check: Restatement detection works
Expected: Period/boundary matching correct, no false restatements
```

### **Test 4: Cross-Company Comparison**
```
Load 2 different companies' reports
Verify: Same metrics are comparable (same unit family)
Check: Metric keys consistent across companies
Expected: Can create comparable dataset
```

### **Test 5: Greenwashing Detection**
```
Create test case: Conflicting claims (e.g., "net zero" claim but 0% renewable)
Verify: Audit stage flags contradiction
Expected: Type 3 greenwashing flag raised
```

---

## 📊 ACCEPTANCE CRITERIA

### **For Development Team**

**Code Quality:**
- [ ] All 112 metrics defined in code
- [ ] All patterns tested and documented
- [ ] No breaking changes to existing extraction
- [ ] Unit tests: >90% pass rate
- [ ] Integration tests: >85% pass rate

**Performance:**
- [ ] Extraction time <5ms per metric per page
- [ ] Harmonization time <1s for 1000 claims
- [ ] Memory usage <500MB for large documents

**Documentation:**
- [ ] Each metric has implementation notes
- [ ] Pattern matching logic documented
- [ ] Unit conversion rules documented
- [ ] Test cases documented

---

### **For ESG Team (Verification)**

**Accuracy Verification:**
- [ ] Spot-check 50+ extracted values
- [ ] Compare against PDF source: 100% match
- [ ] Test period/boundary detection: 100% correct
- [ ] Test restatement detection: >95% precision

**Usability Verification:**
- [ ] Web viewer displays all metrics correctly
- [ ] Filtering by metric type works
- [ ] Exporting metrics to JSON works
- [ ] Cross-report comparison functional

**Business Validation:**
- [ ] Extracted data matches financial statements
- [ ] Extracted data matches company disclosures
- [ ] Greenwashing detection produces actionable insights

---

## 🚀 DEPLOYMENT CHECKLIST

Before releasing to production:

### **Pre-Release**
- [ ] All 112 metrics fully implemented
- [ ] All unit tests passing (>90%)
- [ ] All integration tests passing (>85%)
- [ ] No regressions in existing 13 metrics
- [ ] Documentation complete and reviewed
- [ ] Code reviewed by 2+ team members

### **Beta Testing**
- [ ] Run against 5+ real annual reports
- [ ] Verify accuracy on 100+ sampled values
- [ ] Test with 3 different report formats
- [ ] Collect feedback from ESG team

### **Production Release**
- [ ] Version increment (0.2.0 → 0.3.0)
- [ ] Release notes documenting all new metrics
- [ ] Migration guide for existing workspaces
- [ ] Monitoring/logging for metric extraction

---

## 📈 SUCCESS METRICS

Track these KPIs post-implementation:

| KPI | Target | Baseline |
|-----|--------|----------|
| **Metrics Extraction Rate** | >95% | Currently 13/112 |
| **Accuracy (Spot-Check)** | 100% match with PDF | N/A |
| **Period Harmonization** | >98% correct | N/A |
| **Greenwashing Detection Precision** | >90% | N/A |
| **User Adoption** | >80% using new metrics | N/A |
| **Support Tickets** | <5 per week | Baseline |
| **Performance (read+extract+match)** | <30s per 200-page report | Currently ~40s |

---

## 📞 ESCALATION PATH

If issues arise during implementation:

1. **Minor issues** (syntax, documentation) → Self-resolve
2. **Design questions** → Escalate to architecture team
3. **Unit test failures** → Debug with test author
4. **Integration test failures** → Escalate to QA
5. **Performance issues** → Escalate to DevOps
6. **Business logic disagreements** → Escalate to ESG manager

---

## 📝 SIGN-OFF

**Developer Name:** _________________
**Date Started:** _________________
**Date Completed:** _________________
**Overall Status:** [ ] On Track [ ] At Risk [ ] Complete

**ESG Manager Name:** _________________
**Verification Date:** _________________
**Approval:** [ ] Approved [ ] Needs Revision

---

**End of Checklist**


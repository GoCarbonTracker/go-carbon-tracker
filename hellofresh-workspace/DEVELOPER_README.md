# GoCarbonTracker: 112 Metrics Implementation Guide

**Project:** Extend GoCarbonTracker extraction engine to support 112 ESG + Financial + Operational metrics
**Status:** Ready for Development
**Total Metrics:** 112 (13 existing + 99 new)
**Priority:** MVP with all 112 metrics

---

## 📦 DELIVERABLES PROVIDED

Three specification documents have been created to guide implementation:

### **1. METRICS_SPECIFICATION.md** (20 KB, Human-Readable)
- Complete list of all 112 metrics
- Organized by category: Environmental (19), Social (18), Governance (13), Financial (30), Operational (22), Market (16)
- For each metric:
  - Display name
  - Technical description
  - Unit of measurement
  - Implementation status (existing or new)
  - Implementation notes
  - Priority level
- Includes: Framework support, summary by status, verification checklist, developer notes

**👉 Use this:** For understanding what needs to be built

---

### **2. METRICS_SPECIFICATION.json** (47 KB, Machine-Readable)
- Same 112 metrics in JSON format
- Parseable by build/test automation systems
- Each metric includes:
  - `id`: Unique identifier (env_001, fin_001, etc.)
  - `metric_key`: Code identifier for extraction rules
  - `display_name`: User-friendly name
  - `description`: What this metric captures
  - `unit`: Expected unit(s) of measurement
  - `category`: Sub-category grouping
  - `status`: EXISTING or NEW
  - `implementation_notes`: Extraction patterns to match
  - `priority`: CRITICAL, HIGH, MEDIUM, LOW

**👉 Use this:** For automated validation, CI/CD integration, code generation

---

### **3. VERIFICATION_CHECKLIST.md** (7.9 KB, QA Guide)
- Implementation phases (Phase 1-3 with timelines)
- Per-metric verification tasks
- Batch validation tests (5 different test scenarios)
- Acceptance criteria for development team
- Acceptance criteria for ESG/business team
- Pre-release checklist
- Success metrics to track post-release
- Sign-off template

**👉 Use this:** For QA testing, acceptance verification, release readiness

---

## 🚀 HOW TO USE THESE DOCUMENTS

### **For Developers**

**Step 1: Review the specification**
```bash
cat METRICS_SPECIFICATION.md | less
# Read through all 112 metrics to understand scope
```

**Step 2: Parse the JSON for automation**
```bash
python3 -c "import json; m = json.load(open('METRICS_SPECIFICATION.json')); print(f'Total: {len(m[\"specification\"][\"metrics\"])} categories')"
```

**Step 3: Start implementation with Phase 1**
- 40 critical/high-priority metrics
- See METRICS_SPECIFICATION.md "IMPLEMENTATION RECOMMENDATIONS"
- Roughly 2 weeks for Phase 1

**Step 4: Use VERIFICATION_CHECKLIST.md for QA**
- Test each metric before moving to next
- Run batch tests after phase completion

---

### **For QA/Testing Team**

**Step 1: Set up test environment**
```bash
# You have HelloFresh 2025 Annual Report already loaded
cd hellofresh-workspace
source ../.venv/bin/activate
gct workspace status
```

**Step 2: Run batch tests**
```bash
# Test 1: HelloFresh report extraction
gct read && gct extract && gct match

# Test 2: Export data for manual verification
gct report all --format json --complete
# Then spot-check 50+ values against PDF source
```

**Step 3: Follow VERIFICATION_CHECKLIST.md**
- Check off each metric as it passes validation
- Log failures with metric key and error details
- Report to development team for fixes

---

### **For ESG Manager**

**Step 1: Wait for Phase 1 completion**
- Developers complete 40 critical metrics (1-2 weeks)

**Step 2: Verify against HelloFresh data**
- Download the extracted JSON report
- Cross-reference 20-30 metrics against HelloFresh annual report PDF
- Confirm accuracy, period detection, boundary handling

**Step 3: Sign-off on milestone**
- Use VERIFICATION_CHECKLIST.md "Sign-Off" section
- Approve Phase 1 before proceeding to Phase 2

---

## 📊 METRICS SUMMARY

### **By Category**

| Category | Count | Status | Priority |
|----------|-------|--------|----------|
| Environmental | 19 | 13 existing, 6 new | HIGH |
| Social | 18 | All new | HIGH-MEDIUM |
| Governance | 13 | All new | HIGH-LOW |
| Financial | 30 | All new | CRITICAL |
| Operational | 22 | All new | CRITICAL |
| Market | 16 | All new | HIGH-MEDIUM |
| **TOTAL** | **112** | **13+99** | - |

### **By Priority**

| Priority | Count | Timeline |
|----------|-------|----------|
| CRITICAL | 10 | Phase 1 (Week 1-2) |
| HIGH | 30 | Phase 1 (Week 1-2) |
| MEDIUM | 42 | Phase 2 (Week 3) |
| LOW | 20 | Phase 3 (Week 4) |

### **By Status**

| Status | Count | Notes |
|--------|-------|-------|
| EXISTING | 13 | Already working in codebase |
| NEW | 99 | Need to design extraction rules |

---

## 🔧 IMPLEMENTATION APPROACH

### **Architecture: Add to gct/stages/match.py**

Current code (lines 26-49) defines METRICS tuple with 13 entries:
```python
METRICS = (
    ("ghg_scope_1", ("scope 1", ...), (...)),
    ("ghg_scope_2_location", ("location-based scope 2", ...), (...)),
    # ... 11 more
)
```

**New approach:**
1. Expand METRICS tuple from 13 to 112 entries
2. Add pattern matching rules for each new metric
3. Extend UNITS dictionary for financial units (EUR, USD, INR conversions)
4. Add PREFIXES for Indian currency formats (Crore, Lakh)
5. Update period inference rules for different fiscal year formats
6. Add boundary detection enhancements

### **Key Files to Modify**

1. **gct/stages/match.py**
   - Line 26-49: METRICS tuple (13 → 112 entries)
   - Line 54-66: UNITS dictionary (expand for financial)
   - Line 67-68: PREFIXES (add/verify for all currencies)
   - Line 72-96: Matching logic (_phrase, _excluded functions)

2. **gct/stages/extract.py**
   - Line 18-39: UNITS set (expand for all new unit types)
   - Line 41-56: NUMBER, PERIOD, BOUNDARY regex patterns

3. **gct/stages/infer.py**
   - Period inference rules (FY, fiscal year variations)
   - Boundary statement detection

4. **Tests:**
   - tests/test_match.py: Add test cases for all 112 metrics
   - tests/test_extraction.py: Add unit tests for extraction
   - tests/test_acceptance.py: End-to-end tests

---

## 📋 TESTING STRATEGY

### **Unit Tests (Per Metric)**
```python
# Example test structure
def test_metric_revenue_total():
    """Verify 'revenue_total' extraction"""
    # Test 1: Standard table cell
    assert extract("23,450.5") == ("23450.5", "€M")

    # Test 2: With footnote
    assert extract("23,450.5*") == ("23450.5", "€M")

    # Test 3: Indian format
    assert extract("23,45,000") == ("2345000", "€M")

    # Test 4: Missing unit
    assert extract("23450") == ("23450", None)
```

### **Integration Tests (Per Category)**
```
1. Load HelloFresh report
2. Extract all metrics in one category
3. Verify 90%+ metrics extracted
4. Validate units correctly assigned
5. Check period detection
```

### **Acceptance Tests (Cross-Report)**
```
1. Load 2-3 different companies
2. Same metric should match across companies
3. Units should be comparable (or marked incomparable)
4. Time-series should harmonize correctly
```

---

## 🎯 SUCCESS CRITERIA

### **For Phase 1 (Week 1-2)**
- [ ] 40 critical/high metrics implemented
- [ ] Unit tests: >95% pass rate
- [ ] Integration tests on HelloFresh report: >90% extraction
- [ ] Manual spot-check: 100% accuracy on 20+ sampled values
- [ ] ESG manager sign-off

### **For Phase 2 (Week 3)**
- [ ] Additional 35 metrics implemented
- [ ] Unit tests: >90% pass rate
- [ ] No regressions in Phase 1 metrics
- [ ] Cross-company comparison validated

### **For Phase 3 (Week 4)**
- [ ] Remaining 24 metrics implemented
- [ ] All 112 metrics in production
- [ ] Comprehensive test coverage
- [ ] Documentation complete
- [ ] Ready for public release

---

## 📞 SUPPORT & ESCALATION

### **Questions During Implementation**

**Q: How do I add a new metric?**
A: Follow the pattern in METRICS_SPECIFICATION.json. Add entry to METRICS tuple in match.py with:
```python
("new_metric_key", ("required phrase 1", "required phrase 2"), ("excluded phrase 1",))
```

**Q: How do I test a metric?**
A: See VERIFICATION_CHECKLIST.md "Per-Metric Verification Checklist"

**Q: What if a metric has multiple unit variants?**
A: List all in `implementation_notes`. Add each variant to UNITS dictionary.

**Q: How do I handle Indian number formats?**
A: Use existing INDIAN regex pattern. Already in extract.py line 44.

### **Escalation Path**
1. **Minor issues** → Slack to development team lead
2. **Design questions** → Schedule sync with ESG manager
3. **Test failures** → Escalate to QA with reproduction steps
4. **Performance issues** → Escalate to DevOps/architect

---

## 📚 ADDITIONAL RESOURCES

**GoCarbonTracker Documentation:**
- `/docs/methodology.md` - Extraction principles and algorithm details
- `/docs/framework.md` - Architecture and design decisions
- `/docs/matching.md` - Metric harmonization logic
- `/docs/restatements.md` - Baseline tracking across years

**Code References:**
- `gct/stages/extract.py` - Current extraction engine (lines 12-200)
- `gct/stages/match.py` - Metric mapping engine (lines 26-112)
- `tests/test_match.py` - Metric matching tests

---

## 🚢 DELIVERY TIMELINE

| Phase | Metrics | Timeline | Deliverable |
|-------|---------|----------|------------|
| Phase 1 | 40 | Week 1-2 | Critical/High priority metrics |
| Phase 2 | 35 | Week 3 | Extended financial/operational |
| Phase 3 | 24 | Week 4 | Remaining metrics + documentation |
| **TOTAL** | **112** | **~1 month** | **Complete MVP** |

---

## ✅ NEXT STEPS

1. **Developer**: Review METRICS_SPECIFICATION.md completely
2. **Developer**: Parse METRICS_SPECIFICATION.json for build automation
3. **Developer**: Start Phase 1 implementation
4. **QA**: Set up test environment with HelloFresh data
5. **ESG Manager**: Stand by for Phase 1 sign-off (Week 2-3)
6. **All**: Weekly sync to review progress

---

**Document Created:** 2026-11-02
**Ready for:** Immediate development
**Contact:** [ESG Manager] for questions


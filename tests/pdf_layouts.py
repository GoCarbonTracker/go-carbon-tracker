"""PDF fixtures with the layouts the real reports showed (story 3.5, "What the real reports show"), written by hand:
reportlab is not installed and no dependency is added. Text runs at any text matrix, rules are stroked lines; all
coordinates in points from the top-left. No real report is used."""
from conftest import grid

# Text matrices without the size: upright, rotated 90 degrees anticlockwise (reads bottom to top), and clockwise.
MATRIX = {"ltr": (1, 0, 0, 1), "btt": (0, 1, -1, 0), "ttb": (0, -1, 1, 0)}


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf(pages, size=(612, 792)) -> bytes:
    """A valid PDF, one dict per page: 'text' [(x, y, string[, size[, dir]])] with (x, y) where the baseline starts
    (default 12 pt, ltr) in Helvetica, and 'lines' [(x0, y0, x1, y1)] stroked."""
    w, h = size
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", None, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for p in pages:
        ops = []
        for x, y, s, *rest in p.get("text", []):
            k, d = (rest + [12, "ltr"][len(rest):])[:2]
            a, b, c, e = (v * k for v in MATRIX[d])
            ops.append(f"BT /F1 1 Tf {a} {b} {c} {e} {x} {h - y} Tm ({_esc(s)}) Tj ET")
        ops += [f"{x0} {h - y0} m {x1} {h - y1} l S" for x0, y0, x1, y1 in p.get("lines", [])]
        stream = "\n".join(ops).encode("latin-1")
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] /Resources << /Font << /F1 3 0 R >> >>"
                    f" /Contents {len(objs)} 0 R >>".encode())
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>".encode()
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def _page(*parts) -> dict:
    return {"text": [t for p in parts for t in p.get("text", [])], "lines": [x for p in parts for x in p.get("lines", [])]}


# Finding 1 (Tata AR p380, Mahindra AR p186): rotated text on an unrotated page. A ruled table whose cells are
# printed bottom to top, a rotated text line each way, and an upright title. No value is a palindrome.
ROTATED_TABLE = grid(100, 200, [30, 30, 30], [100], [])
ROTATED = _page(ROTATED_TABLE, {"text": [
    (72, 60, "Balance sheet"),
    (120, 295, "Debt equity", 7, "btt"), (150, 295, "0.29", 7, "btt"), (180, 295, "(1.65)", 7, "btt"),
    (300, 500, "Reserves and surplus 1,234 %", 7, "btt"),
    (400, 300, "Net worth 4,321 %", 7, "ttb"),
]})


def _column(x, lines, top=100, step=10, size=7) -> dict:
    return {"text": [(x, top + step * i, s, size) for i, s in enumerate(lines)]}


# Finding 2 (Mahindra AR p114): the item-13 question, its answer and item c in three columns, one text line each.
QUESTION = ["13 Reporting boundary - Are the disclosures", "under this report made on a standalone basis",
            "(i.e. only for the entity) or on a consolidated", "basis (i.e. for the entity and all the entities",
            "which form a part of its consolidated financial", "statements, taken together)."]
ANSWER = ["The disclosures under this report are", "made on Standalone basis."]
ITEM_C = ["c. A brief on types of customers", "The Company serves its customers", "across many markets in India",
          "and abroad through dealers.", "It sells tractors and cars.", "It also sells spares."]
# As printed: the answer starts 8 pt right of the question's longest line (x 180.46), word gaps are 2 to 4 pt, a
# one-line form item prints its label and answer on one line, and item 12 runs straight across the gutter.
FORM = {"text": [(40, 60, "9 Financial Year reported", 7), (188.5, 60, "1 April 2024 to 31 March 2025", 7),
                 (40, 85, "12 Name and contact details of the person who may be contacted in case of any queries", 7)]}
THREE_COLUMNS = _page(FORM, _column(40, QUESTION), _column(188.5, ANSWER), _column(400, ITEM_C))
QUESTION_ONLY = _page(FORM, _column(40, QUESTION), _column(400, ITEM_C))
NO_ANSWER = _page(FORM, _column(40, QUESTION), _column(188.5, ["Standalone"]), _column(400, ITEM_C))
# Finding 2 (Tata AR p135): two text columns, each line with its own figure.
TWO_COLUMNS = _page(_column(40, ["Scope 1 emissions 1,200 tCO2e", "Energy use rose", "Water withdrawn 3,400 kL"]),
                    _column(320, ["Waste recycled 56 %", "across all plants", "Fleet fuel 7,800 kL"]))

# Finding 3 (Tata AR p134): headers printed above a table whose bbox holds only figures, the row labels left of it.
# Columns x 317-374, 374-431, 431-488; boundary headers at top 158, period headers at top 170.
# Also in the band: PARTICULARS over the labels, the unit note and a fourth value column right of the bbox with its
# own FY23 header; row 3 prints dashes before its figure.
HEADED_TABLE = grid(317, 179, [57, 57, 57], [20, 20, 20],
                    [["1,111", "2,222", "3,333"], ["4,444", "5,555", "6,666"], ["-", "-", "699.80"]])
HEADERS = [(354, 163, "Standalone*", 7), (467, 163, "Consolidated", 7),
           (355, 175, "FY24", 7), (412, 175, "FY23", 7), (469, 175, "FY24", 7), (525, 175, "FY23", 7),
           (53, 169, "PARTICULARS", 7), (513, 150, "(Rs in crore)", 7)]
ROW_LABELS = [(150, 192, "Scope 1 emissions (tCO2e)", 7), (150, 212, "Scope 2 emissions (tCO2e)", 7),
              (150, 232, "Other income", 7), (501, 192, "7,070", 7)]
# A second table with a header-like line more than 30 points above it: never attached.
PLAIN_TABLE = grid(317, 400, [57, 57], [20], [["7,777", "8,888"]])
FAR = [(330, 363, "FY22", 7)]
# A table right under a short one: the line above the short one is never a header of the lower one.
UPPER_TABLE = _page(grid(317, 600, [57, 57], [12], []), {"text": [(321, 609, "Total", 7), (378, 609, "Plants", 7)]})
LOWER_TABLE = grid(317, 616, [57, 57], [20], [["9,999", "1,010"]])
ABOVE_UPPER = [(330, 597, "FY21", 7)]
TATA_P134 = _page(HEADED_TABLE, PLAIN_TABLE, UPPER_TABLE, LOWER_TABLE,
                  {"text": HEADERS + ROW_LABELS + FAR + ABOVE_UPPER + [(72, 500, "Sales grew 5 % in FY24", 7)]})
# Tata AR p134 rows 0 to 5 alone, labels at their printed x: only "amortization," lies past the 6.3 pt gap after
# "depreciation,", a ragged block and no gutter. Row 4's words are drawn at 7.9 pt so they end near their printed x1.
RAGGED_LABELS = _page(grid(317.5, 178.6, [56.7, 56.7, 56.7], [13.4, 13.4, 13.4, 13.4, 23.6, 13.4], [
    ["73,303.08", "65,757.33", "437,927.77"], ["64,328.20", "60,047.46", "367,358.97"],
    ["8,974.88", "5,709.87", "70,568.80"], ["1,149.88", "820.94", "5,949.92"],
    ["10,124.76", "6,530.81", "76,518.72"], ["-", "-", "699.80"]]), {"text": [
    (55, 188.3, "Revenue from operations", 8.5), (55, 201.7, "Total expenditure", 8.5),
    (55, 215.1, "Operating profit", 8.5), (55, 228.4, "Other Income", 8.5),
    *[(x, 241.8, s, 7.9) for x, s in ((55, "Profit"), (80.4, "before"), (109.2, "interest,"), (144.1, "foreign"),
                                      (174.8, "exchange,"), (215.6, "depreciation,"), (267.4, "amortization,"))],
    (55, 252, "exceptional item and tax", 8.5), (55, 265.4, "Share of profit of joint venture and associates (net)", 8.5)]})

# Mahindra AR p75: a label column, then two value columns printed left of the detected table's bbox. Row 1 has no
# wording at all; rows 2 and 3 have numbers inside their wording.
VALUE_COLUMNS = _page(grid(317, 180, [60, 60], [20, 20, 20, 20], [
    ["43,01,848", "38,04,105"], ["1,11,111", "2,22,222"], ["3,333", "4,444"], ["5,555", "6,666"]]), {"text": [
    (55, 194, "Tractors sold", 7), (180, 194, "9,41,115", 7), (212, 194, "Units", 7),
    (245, 194, "4,24,641", 7), (277, 194, "Units", 7),
    (180, 214, "3,92,911", 7), (212, 214, "(3.8)", 7), (245, 214, "5,38,518", 7), (277, 214, "6.0", 7),
    (55, 234, "Scope 1 emissions", 7), (180, 234, "1,234", 7), (212, 234, "tCO2e", 7),
    (55, 254, "Category 1 : Purchased goods", 7), (180, 254, "12", 7), (212, 254, "%", 7)]})

# A table-heavy page: two tables side by side and one across the gutter of a two-column text region printed above
# and below them.
SIDE_A = grid(40, 300, [100, 60], [20, 20], [["Metric", "FY24"], ["Scope 1", "1,234"]])
SIDE_B = grid(330, 300, [100, 60], [20, 20], [["Metric", "FY23"], ["Scope 2", "5,678"]])
ACROSS = grid(40, 400, [200, 200, 100], [20], [["Energy", "4,321", "GJ"]])
TABLES = _page(SIDE_A, SIDE_B, ACROSS,
               _column(40, ["Left text one", "Left text two", "Left text three"], top=100, step=14, size=12),
               _column(330, ["Right text one", "Right text two", "Right text three"], top=100, step=14, size=12),
               _column(40, ["Left text four", "Left text five", "Left text six"], top=500, step=14, size=12),
               _column(330, ["Right text four", "Right text five", "Right text six"], top=500, step=14, size=12))

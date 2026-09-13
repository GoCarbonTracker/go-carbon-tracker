# Contributing to GoCarbonTracker

This repository holds public documentation and static visualizations. The application source code is private and is not open for pull requests. What you can contribute here is review: of sources, of methods, of the visualizations.

## What helps

**Source corrections.** The README and the hypergraph site quote sentences from public Tata Motors documents. If a quote, document name, or page is wrong, open an issue with the document, the page, and the correct text.

**Methods review.** The [architecture documents](docs/architecture/) describe how claims are extracted, linked to evidence, and flagged as candidate conflicts. Every Tata contradiction the system flagged turned out to be an extraction artifact. If you can see another artifact class that would slip through, or a way to catch the known ones, write it up in an issue.

**Case-study review.** If you read sustainability disclosures for a living (CSRD, BRSR, CDP, GRI) and can look at an apparent conflict and say whether it is real, that judgement is the scarcest input this project has.

**Visualization accessibility.** The pages under [visualizations/](visualizations/) are self-contained HTML. Keyboard navigation and screen-reader behaviour have not been reviewed. Issues with a specific page and browser are welcome; pull requests to those HTML files are too.

## How

1. Open an [issue](https://github.com/GoCarbonTracker/go-carbon-tracker/issues). Say which document, page, or file you are talking about.
2. For visualization fixes, fork, change the HTML file, and open a pull request. Keep each pull request to one page.
3. Do not add counts or status claims to any document without a date on the same line.

## Conduct

Be direct and specific. Criticise the evidence, not the person. Corrections that name a page beat opinions that do not.

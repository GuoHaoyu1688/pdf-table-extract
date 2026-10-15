# Version 0.1.0

Offline PDF table extraction with CSV/XLSX/JSON, visual correction, local OCR and MCP tools.

Local verification: 41 tests passed; 90% measured coverage; Ruff lint and formatting checks passed. README quick start was exercised with fictional data.

## Known limitations

Extraction is heuristic. OCR reconstructs one aligned region and may need cropping; mixed ruled and borderless tables should be extracted separately. Auto mode stops after finding ruled tables on a page. Merged-cell filling can propagate values and requires review. Confidence scores are advisory; Camelot and OCR are optional dependencies.

See README and AGENTS.md for installation, configuration, machine-readable CLI/MCP interfaces and operational boundaries.

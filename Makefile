# Postmortem AI — common targets (mac/Linux). On Windows use PowerShell equivalents (see README).

PYTHON ?= python
VENV_PIP = venv/bin/pip
VENV_PYTHON = venv/bin/python

# Create venv and install dependencies
setup:
	$(PYTHON) -m venv venv
	$(VENV_PIP) install -r requirements.txt

# Create/recreate Elasticsearch indices from mappings/
indices:
	$(VENV_PYTHON) scripts/create_indices.py --recreate

# Bulk load synthetic dataset from data/ into Elasticsearch
load:
	$(VENV_PYTHON) scripts/bulk_load.py

# Run Day 5 E2E demo (narrator + auditor) for INC-1042
demo:
	$(VENV_PYTHON) scripts/demo_day5_e2e.py --incident INC-1042

# Run Day 5 verification (narrator + auditor output shape)
verify:
	$(VENV_PYTHON) scripts/verify_day5.py

# Start Streamlit UI
ui:
	$(VENV_PYTHON) -m streamlit run app.py

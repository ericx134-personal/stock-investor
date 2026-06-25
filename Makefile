PYTHON ?= /usr/bin/python3

.PHONY: test test-l1 test-l2 test-l3 test-dashboard safety

test: test-l1

test-l1:
	PYTHON=$(PYTHON) scripts/run_tests.sh L1

test-l2:
	PYTHON=$(PYTHON) scripts/run_tests.sh L2

test-l3:
	PYTHON=$(PYTHON) scripts/run_tests.sh L3

test-dashboard:
	$(PYTHON) -m unittest tests.test_dashboard

safety:
	scripts/check_public_safety.sh

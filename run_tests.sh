#!/bin/bash

pip install -r requirements.txt

python3 -m coverage run --source=src -m pytest \
    tests/test_cognitive_complexity.py \
    tests/test_cohesion_metrics.py \
    tests/test_halstead_metrics.py \
    tests/test_nesting_visitor.py \
    tests/test_sloc_metrics.py \
    tests/test_rfc_metric.py \
    tests/test_all_metrics.py

python3 -m coverage report -m
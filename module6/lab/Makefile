export HOME := $(CURDIR)
export LLM_MODE ?= fake
PY := .venv/bin/python

setup:
	uv venv --python 3.12 .venv
	VIRTUAL_ENV=.venv uv pip install guardrails-ai nemoguardrails pytest \
		guardrails-ai-regex-match guardrails-ai-valid-length guardrails-ai-secrets-present
	printf 'enable_metrics=false\nuse_remote_inferencing=false\n' > .guardrailsrc

attack:            ## крок 1: вразливий агент
	$(PY) -m attacks.run_attacks "L0 baseline"

matrix:            ## кроки 2 і 4: порівняння рівнів захисту
	$(PY) -m attacks.run_attacks "L0 baseline" "L1 guardrails" "L3 containment"

nemo:              ## крок 3: семантичний шар (потрібен OPENAI_API_KEY)
	$(PY) -m attacks.run_attacks "L0 baseline" "L2 +nemo" "L3 containment"

test:              ## крок 5: регресія в CI
	$(PY) -m pytest tests -q

clean:
	rm -f egress.log
.PHONY: setup attack matrix nemo test clean

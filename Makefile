.PHONY: check run release validate bundle

check:
	python3 tools/check.py

run:
	cargo run

release:
	cargo run --release

validate:
	python3 tools/validate_project.py
	node --check web/app.js

bundle:
	python3 tools/package.py

PYTHON ?= python3

.PHONY: check demo diff-check format-check lint markdown sensitive test coverage

check: format-check lint test coverage markdown sensitive diff-check

demo:
	PYTHONPATH=. $(PYTHON) -m tools.owntracks_spike

format-check:
	@! grep -RInE '[[:blank:]]+$$' --include='*.py' --include='*.md' --include='*.json' --include='Makefile' .
	@$(PYTHON) -m tabnanny tools tests

lint:
	@$(PYTHON) -m compileall -q tools tests

test:
	@PYTHONPATH=. $(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v

coverage:
	@trace_dir=$$(mktemp -d); \
	trap 'rm -r "$$trace_dir"' EXIT; \
	stdlib=$$($(PYTHON) -c 'import sysconfig; print(sysconfig.get_paths()["stdlib"])'); \
	PYTHONPATH=. $(PYTHON) -m trace --count --missing --coverdir "$$trace_dir" \
		--ignore-dir "$$stdlib" --module unittest discover -s tests -p 'test_*.py' >/dev/null; \
	files=$$(find "$$trace_dir" -type f \( \
		-name 'tools.__init__.cover' -o \
		-name 'tools.line_coverage.cover' -o \
		-name 'tools.owntracks_spike.*.cover' -o \
		-name 'tests.__init__.cover' -o \
		-name 'test_*.cover' \
	\) -print); \
	test -n "$$files"; \
	PYTHONPATH=. $(PYTHON) -c 'import sys; from tools.line_coverage import main; raise SystemExit(main(sys.argv[1:]))' $$files

markdown:
	@test -f README.md -a -f CHANGELOG.md -a -f docs/BACKLOG.md
	@! grep -RInE '[[:blank:]]+$$' --include='*.md' .
	@for target in docs/HERMODR_PRD.md docs/IMPLEMENTATION_DESIGN.md docs/IMPLEMENTATION_PLAN.md docs/BACKLOG.md CHANGELOG.md; do test -f "$$target"; done

sensitive:
	@! grep -RInE --exclude-dir=.git --exclude='Makefile' '(BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|AKIA[0-9A-Z]{16}|Authorization:[[:space:]]*(Basic|Bearer)[[:space:]]+[A-Za-z0-9+/=_-]{12,})' .

diff-check:
	@git diff --check

PYTHON ?= python3

.PHONY: artifact check demo dependency-check diff-check format-check lint markdown sensitive test coverage

check: format-check lint dependency-check artifact test coverage markdown sensitive diff-check

artifact:
	@artifact_dir=$$(mktemp -d); \
	trap 'rm -r "$$artifact_dir"' EXIT; \
	HERMODR_BUILD_COMMIT=$$(git rev-parse --short=12 HEAD) PYTHONPATH=src:. $(PYTHON) -c 'import sys; import hermodr_build_backend as b; print(b.build_wheel(sys.argv[1]))' "$$artifact_dir"

demo:
	PYTHONPATH=. $(PYTHON) -m tools.owntracks_spike

format-check:
	@! grep -RInE '[[:blank:]]+$$' --include='*.py' --include='*.md' --include='*.json' --include='Makefile' .
	@$(PYTHON) -m tabnanny tools tests

lint:
	@$(PYTHON) -m compileall -q src tools tests
	@PYTHONPATH=src:. $(PYTHON) -m tools.static_analysis src tools tests hermodr_build_backend.py

dependency-check:
	@PYTHONPATH=src:. $(PYTHON) -c 'import tomllib; p=tomllib.load(open("pyproject.toml", "rb")); assert p["project"]["dependencies"] == []; assert p["tool"]["hermodr"]["license-policy"] == "stdlib-only"'

test:
	@PYTHONPATH=src:. $(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v

coverage:
	@trace_dir=$$(mktemp -d); \
	trap 'rm -r "$$trace_dir"' EXIT; \
	stdlib=$$($(PYTHON) -c 'import sysconfig; print(sysconfig.get_paths()["stdlib"])'); \
	PYTHONPATH=src:. $(PYTHON) -m trace --count --missing --coverdir "$$trace_dir" \
		--ignore-dir "$$stdlib" --module unittest discover -s tests -p 'test_*.py' >/dev/null; \
	files=$$(find "$$trace_dir" -type f \( \
		-name 'hermodr.*.cover' -o \
		-name 'hermodr_build_backend.cover' -o \
		-name 'tools.__init__.cover' -o \
		-name 'tools.line_coverage.cover' -o \
		-name 'tools.static_analysis.cover' -o \
		-name 'tools.owntracks_spike.*.cover' -o \
		-name 'tests.__init__.cover' -o \
		-name 'test_*.cover' \
	\) -print); \
	test -n "$$files"; \
	PYTHONPATH=src:. $(PYTHON) -c 'import sys; from tools.line_coverage import main; raise SystemExit(main(sys.argv[1:]))' $$files

markdown:
	@test -f README.md -a -f CHANGELOG.md -a -f docs/BACKLOG.md
	@! grep -RInE '[[:blank:]]+$$' --include='*.md' .
	@for target in docs/HERMODR_PRD.md docs/IMPLEMENTATION_DESIGN.md docs/IMPLEMENTATION_PLAN.md docs/BACKLOG.md CHANGELOG.md docs/m1/VALIDATION.md; do test -f "$$target"; done

sensitive:
	@! grep -RInE --exclude-dir=.git --exclude='Makefile' '(BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|AKIA[0-9A-Z]{16}|Authorization:[[:space:]]*(Basic|Bearer)[[:space:]]+[A-Za-z0-9+/=_-]{12,})' .
	@! rg --pcre2 '"(?:lat|lon|latitude|longitude)"\s*:\s*(?!0(?:\.0)?(?:\s*[,}]))-?[0-9]' testdata

diff-check:
	@git diff --check

# The only entry point for linting, auditing and testing: the same targets run
# on a laptop, in the git hooks (.githooks) and in CI. Written for GNU Make
# 3.81 (macOS) and later.

# Always the pinned tools (make tools), never another copy on PATH.
TOOLS := $(CURDIR)/.tools
VENV := $(TOOLS)/venv
SHELLCHECK := $(TOOLS)/bin/shellcheck
ACTIONLINT := $(TOOLS)/bin/actionlint
GITLEAKS := $(TOOLS)/bin/gitleaks
ZIZMOR := $(VENV)/bin/zizmor
PYTEST := $(VENV)/bin/pytest
export LC_ALL := C

# Conventional commit types, summary 1-72 characters; merge commits pass.
COMMIT_RE := ^((feat|fix|docs|build|chore|test|refactor|ci|perf|revert)(\([A-Za-z0-9.-]+\))?!?: .{1,72}|Merge .+)$$

SHELL_SCRIPTS := $(wildcard scripts/*.sh .githooks/*)
# Explicit paths: only this repository's workflows, Dependabot config and
# actions, never test fixtures or vendored files.
AUDIT_PATHS := .github/workflows .github/dependabot.yml version build-image quay-login publish-chart notify-rm changelog release-declaration release-documents release-manifest compatibility release-inputs release-source promote-image ci-gate draft-release publish-chart-s3
ZIZMOR_FORMAT := $(if $(GITHUB_ACTIONS),github,plain)

.PHONY: ci tools lint audit audit-online test secrets-scan commit-msg commit-msg-check hooks release-prep

# Targets run one at a time, even under `make -j`.
.NOTPARALLEL:

ci: lint audit test secrets-scan commit-msg-check

# Pinned binaries (scripts/install-tools.sh) and the hashed Python tools.
tools: $(VENV)/.installed
	scripts/install-tools.sh

# Rebuilt from scratch whenever requirements-ci.txt changes.
$(VENV)/.installed: requirements-ci.txt
	rm -rf $(VENV)
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --quiet --disable-pip-version-check --require-hashes --no-deps -r requirements-ci.txt
	touch $@

lint: tools
	$(SHELLCHECK) -x $(SHELL_SCRIPTS)
	$(ACTIONLINT)

audit: tools
	$(ZIZMOR) --offline --format $(ZIZMOR_FORMAT) $(AUDIT_PATHS)

# Also checks the pinned actions against GitHub (known vulnerabilities,
# impostor commits): needs GH_TOKEN. Run nightly in CI.
audit-online: tools
	@if [ -z "$$GH_TOKEN" ]; then echo "audit-online: GH_TOKEN is required" >&2; exit 64; fi
	$(ZIZMOR) --format $(ZIZMOR_FORMAT) $(AUDIT_PATHS)

# The pinned yq (scripts/compatibility.sh) comes first on PATH.
test: tools
	PATH="$(TOOLS)/bin:$$PATH" $(PYTEST) -q tests

# The whole history, or with STAGED=1 the staged changes (pre-commit hook).
# gitleaks:allow comments are ignored: exceptions go in .gitleaksignore.
GITLEAKS_FLAGS := --redact --no-banner --verbose --ignore-gitleaks-allow --config .gitleaks.toml
secrets-scan: tools
ifeq ($(STAGED),1)
	$(GITLEAKS) git --pre-commit --staged $(GITLEAKS_FLAGS) .
else
	$(GITLEAKS) git $(GITLEAKS_FLAGS) .
endif

# One commit message file (commit-msg hook, CI commits job).
commit-msg:
	@if [ -z "$(MSG)" ] || [ ! -f "$(MSG)" ]; then echo "usage: make commit-msg MSG=<message file>" >&2; exit 64; fi
	@if ! head -n 1 "$(MSG)" | grep -Eq '$(COMMIT_RE)'; then \
		echo "commit-msg: first line must be '<type>[(scope)][!]: <summary>' (types feat fix docs build chore test refactor ci perf revert, summary 1-72 characters) or start with 'Merge '" >&2; \
		exit 1; \
	fi
	@if [ -n "$$(sed -n 2p "$(MSG)")" ]; then echo "commit-msg: the second line must be empty" >&2; exit 1; fi

# The commit-msg rule against its fixtures: every ok-* message must pass,
# every bad-* message must fail.
commit-msg-check:
	@for f in testdata/commit-msg/ok-*; do \
		$(MAKE) -s commit-msg MSG="$$f" || { echo "commit-msg-check: $$f refused, it must pass" >&2; exit 1; }; \
	done
	@for f in testdata/commit-msg/bad-*; do \
		if $(MAKE) -s commit-msg MSG="$$f" 2>/dev/null; then \
			echo "commit-msg-check: $$f accepted, it must fail" >&2; exit 1; \
		fi; \
	done

# Versioned hooks: pre-commit lints and scans the staged changes, commit-msg
# checks the message.
hooks:
	git config core.hooksPath .githooks

# Point dev-build.yml at the release about to be tagged: make release-prep VERSION=vX.Y.Z
release-prep:
	@if [ -z "$(VERSION)" ]; then echo "usage: make release-prep VERSION=vX.Y.Z" >&2; exit 64; fi
	scripts/set-release-ref.sh "$(VERSION)"

# setu build, test and install. `make install` builds the web app and the binary, writes the
# launchd agent dev.setu, retires the old dev.aiw.ui agent and starts the new one.

BIN        ?= $(HOME)/.local/bin/setu
LABEL      := dev.setu
PLIST      := $(HOME)/Library/LaunchAgents/$(LABEL).plist
OLD_LABEL  := dev.aiw.ui
OLD_PLIST  := $(HOME)/Library/LaunchAgents/$(OLD_LABEL).plist
UID        := $(shell id -u)
VERSION    ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)
COMMIT     ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo none)
LDFLAGS    := -X main.version=$(VERSION) -X main.commit=$(COMMIT)

.PHONY: build web test install restart uninstall

# The web app is committed (internal/web/dist), so `go build` alone also works.
web:
	cd web && npm ci && npm run build

build: web
	go build -ldflags "$(LDFLAGS)" -o bin/setu ./cmd/setu

test:
	go vet ./...
	go test -race ./...
	cd web && npm run typecheck && npm test

# PATH for the agent: the usual tool dirs, the dirs of the tools setu runs, then the system dirs.
install: web
	mkdir -p $(dir $(BIN)) $(HOME)/.setu/logs $(HOME)/Library/LaunchAgents
	go build -ldflags "$(LDFLAGS)" -o $(BIN) ./cmd/setu
	@tooldirs=""; for t in claude gh slackcli jev tailscale terminal-notifier; do \
	  p=$$(command -v $$t 2>/dev/null) && tooldirs="$$tooldirs:$$(dirname $$p)"; done; \
	agentpath="/opt/homebrew/bin:/usr/local/bin:$(HOME)/.local/bin$$tooldirs:/usr/bin:/bin:/usr/sbin:/sbin"; \
	agentpath=$$(printf '%s' "$$agentpath" | awk -v RS=: '!seen[$$0]++ { printf "%s%s", (n++ ? ":" : ""), $$0 }'); \
	sed -e "s|@BIN@|$(BIN)|g" -e "s|@HOME@|$(HOME)|g" -e "s|@PATH@|$$agentpath|g" \
	    deploy/dev.setu.plist > $(PLIST).tmp && mv $(PLIST).tmp $(PLIST)
	@for v in CLAUDE_CONFIG_DIR SETU_HOME; do \
	  eval "val=\$${$$v}"; \
	  if [ -n "$$val" ]; then /usr/libexec/PlistBuddy -c "Add :EnvironmentVariables:$$v string $$val" $(PLIST); fi; done
	@plutil -lint $(PLIST)
	@if launchctl print gui/$(UID)/$(OLD_LABEL) >/dev/null 2>&1; then \
	  launchctl bootout gui/$(UID)/$(OLD_LABEL) || true; fi
	@if [ -f $(OLD_PLIST) ]; then mv $(OLD_PLIST) $(OLD_PLIST).disabled; fi
	@launchctl bootout gui/$(UID)/$(LABEL) >/dev/null 2>&1 || true
	@# bootout returns before the old agent is gone; bootstrap then fails with EIO, so retry
	@for i in 1 2 3 4 5 6 7 8 9 10; do launchctl bootstrap gui/$(UID) $(PLIST) 2>/dev/null && exit 0; sleep 1; done; launchctl bootstrap gui/$(UID) $(PLIST)
	launchctl kickstart -k gui/$(UID)/$(LABEL)
	@echo "setu installed: $(BIN), agent $(LABEL), logs in ~/.setu/logs/"

# Rebuild the web app and the binary, then restart the agent.
restart: web
	go build -ldflags "$(LDFLAGS)" -o $(BIN) ./cmd/setu
	launchctl kickstart -k gui/$(UID)/$(LABEL)

# Stop and remove the agent and the binary. State in ~/.setu is kept.
uninstall:
	-launchctl bootout gui/$(UID)/$(LABEL)
	rm -f $(PLIST) $(BIN)
	@if [ -f $(OLD_PLIST).disabled ]; then echo "the old agent is kept as $(OLD_PLIST).disabled"; fi

.PHONY: restart

# Rebuild the UI into run-engine/ui_dist/ and restart the server: the launchd agent dev.aiw.ui
# when it is loaded, else the supervisord program aiw-ui.
restart:
	cd ui && npm run build
	@if launchctl print gui/$$(id -u)/dev.aiw.ui >/dev/null 2>&1; then \
		launchctl kickstart -k gui/$$(id -u)/dev.aiw.ui; \
	else \
		supervisorctl restart aiw-ui; \
	fi

.PHONY: restart

# Rebuild the UI into run-engine/ui_dist/ and restart the server (LaunchAgent, else supervisord).
restart:
	cd ui && npm run build
	bin/aiw service restart

.PHONY: restart

# Rebuild the UI into run-engine/ui_dist/ and restart the supervisord-managed server.
restart:
	cd ui && npm run build
	supervisorctl restart aiw-ui

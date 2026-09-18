# Push the working tree to the Pi for hardware iteration. Not a deploy:
# commit and `git pull --ff-only` on the Pi once the change is settled.
#
# The Pi needs an editable install, or synced library changes are ignored:
#   sudo pip3 install -e ~/picrawler --break-system-packages --no-deps

PI_HOST ?= picrawler
PI_DIR  ?= picrawler
SERVICE ?= petronilo

# Pi-local state that --delete must never remove. .git has no trailing
# slash because it is a file, not a directory, inside a worktree.
EXCLUDES := \
	.git \
	.claude/ \
	.vscode/ \
	__pycache__/ \
	'*.egg-info/' \
	build/ \
	'secret*' \
	examples/petronilo_memory/ \
	'examples/petronilo_memory.json*' \
	examples/img_input.jpeg \
	examples/musics/reggaeton_dembow.wav \
	'.lgd-nfy*' \
	.DS_Store

RSYNC := rsync -az --delete --itemize-changes $(addprefix --exclude ,$(EXCLUDES))

# Servo offsets written by examples/0_calibration.py. The examples run under
# sudo, so robot_hat keeps them in root's home.
CALI_PI   := /root/.config/.picrawler.config
CALI_REPO := calibration/picrawler.config

.PHONY: sync sync-dry restart deploy logs cali-pull cali-push

sync: ## Push the working tree to the Pi
	$(RSYNC) ./ $(PI_HOST):$(PI_DIR)/

sync-dry: ## Show what sync would change
	$(RSYNC) --dry-run ./ $(PI_HOST):$(PI_DIR)/

restart: ## Restart the voice assistant service
	ssh $(PI_HOST) sudo systemctl restart $(SERVICE)

deploy: sync restart ## Sync, then restart

logs: ## Follow the service logs
	ssh -t $(PI_HOST) journalctl -u $(SERVICE) -f

cali-pull: ## Copy the Pi's servo calibration into the repo (commit it afterwards)
	ssh $(PI_HOST) sudo cat $(CALI_PI) > $(CALI_REPO).tmp
	grep -q picrawler_servo_offset_list $(CALI_REPO).tmp
	mv $(CALI_REPO).tmp $(CALI_REPO)

cali-push: ## Overwrite the Pi's servo calibration with the repo copy
	ssh $(PI_HOST) 'sudo mkdir -p $(dir $(CALI_PI)) && sudo tee $(CALI_PI) > /dev/null' < $(CALI_REPO)

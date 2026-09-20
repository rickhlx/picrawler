# Deploy by rsync: the Pi's ~/picrawler is a copy of this working tree, never
# pulled with git. `make deploy` syncs and restarts the service; each sync
# leaves a DEPLOYED stamp on the Pi (commit, dirty flag, branch, time) since
# the Pi's own git history no longer says what is running.
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
	examples/petronilo_mcp.json \
	'examples/petronilo_memory.json*' \
	examples/img_input.jpeg \
	examples/musics/reggaeton_dembow.wav \
	'.lgd-nfy*' \
	.DS_Store \
	DEPLOYED

RSYNC := rsync -az --delete --itemize-changes $(addprefix --exclude ,$(EXCLUDES))

# Servo offsets written by examples/0_calibration.py. The examples run under
# sudo, so robot_hat keeps them in root's home.
CALI_PI   := /root/.config/.picrawler.config
CALI_REPO := calibration/picrawler.config

.PHONY: sync sync-dry deployed restart deploy logs cali-pull cali-push ask say stop status jobs \
        wifi wifi-list wifi-status

sync: ## Push the working tree to the Pi and stamp what was deployed
	$(RSYNC) ./ $(PI_HOST):$(PI_DIR)/
	printf '%s %s %s\n' "$$(git describe --always --dirty)" "$$(git branch --show-current)" "$$(date -u +%FT%TZ)" \
		| ssh $(PI_HOST) 'cat > $(PI_DIR)/DEPLOYED'

deployed: ## Show what the Pi is running
	ssh $(PI_HOST) cat $(PI_DIR)/DEPLOYED

sync-dry: ## Show what sync would change
	$(RSYNC) --dry-run ./ $(PI_HOST):$(PI_DIR)/

# -t gives sudo a terminal to ask for the password on
restart: ## Restart the voice assistant service
	ssh -t $(PI_HOST) sudo systemctl restart $(SERVICE)

deploy: sync restart ## Sync, then restart

logs: ## Follow the service logs
	ssh -t $(PI_HOST) journalctl -u $(SERVICE) -f

cali-pull: ## Copy the Pi's servo calibration into the repo (commit it afterwards)
	ssh $(PI_HOST) sudo cat $(CALI_PI) > $(CALI_REPO).tmp
	grep -q picrawler_servo_offset_list $(CALI_REPO).tmp
	mv $(CALI_REPO).tmp $(CALI_REPO)

cali-push: ## Overwrite the Pi's servo calibration with the repo copy
	ssh $(PI_HOST) 'sudo mkdir -p $(dir $(CALI_PI)) && sudo tee $(CALI_PI) > /dev/null' < $(CALI_REPO)

# Wi-Fi: teach him a network *before* you take him there. NetworkManager joins
# whichever known network is in range, so a pre-seeded profile means he comes up
# on the new Wi-Fi with no screen and no keyboard. See docs/wifi.md.
#
# The password is typed at a prompt, never in argv or make's environment: it
# goes into a keyfile written 600 in the Pi user's home, then installed as root.
NM_DIR := /etc/NetworkManager/system-connections

wifi: ## Teach him a network before you move him: make wifi SSID="Casa de Ana" [HIDDEN=yes]
	@test -n "$(SSID)" || { echo 'usage: make wifi SSID="network name" [HIDDEN=yes]' >&2; exit 1; }
	@case '$(SSID)' in */*) echo 'SSID cannot contain "/"' >&2; exit 1;; esac
	@printf 'Wi-Fi password for %s: ' '$(SSID)'; stty -echo; read PASS; stty echo; printf '\n'; \
	printf '[connection]\nid=%s\ntype=wifi\nautoconnect=true\n\n[wifi]\nssid=%s\nhidden=%s\npowersave=2\n\n[wifi-security]\nkey-mgmt=wpa-psk\npsk=%s\n\n[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=auto\n' \
		'$(SSID)' '$(SSID)' '$(if $(HIDDEN),true,false)' "$$PASS" \
		| ssh $(PI_HOST) 'umask 077 && cat > ~/.wifi-new.nmconnection'
	@ssh -t $(PI_HOST) "sudo install -m 600 -o root -g root ~/.wifi-new.nmconnection '$(NM_DIR)/$(SSID).nmconnection' \
		&& rm -f ~/.wifi-new.nmconnection && sudo nmcli connection reload"
	@echo "'$(SSID)' saved. He joins it whenever it is in range."

wifi-list: ## Networks he already knows
	ssh $(PI_HOST) nmcli -f NAME,TYPE,AUTOCONNECT connection show

wifi-status: ## Which network he is on right now, and his address
	ssh $(PI_HOST) "nmcli -t -f GENERAL.CONNECTION,IP4.ADDRESS device show wlan0; iwgetid -r || true"

# Talk to the running service through its control socket (examples/control.py)
CTL := ssh -t $(PI_HOST) sudo python3 $(PI_DIR)/examples/petronilo_ctl.py

ask: ## Ask him something, spoken aloud on the Pi: make ask MSG="qué hora es"
	$(CTL) ask "$(MSG)"

say: ## Make him say a line verbatim: make say MSG="ya llegó la pizza"
	$(CTL) say "$(MSG)"

stop: ## Cut the current answer and moves
	$(CTL) stop

status: ## Battery, idle, spend today, pending reminders
	$(CTL) status

jobs: ## List pending reminders and tasks
	$(CTL) jobs

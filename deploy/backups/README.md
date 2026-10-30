# Nightly database backups (Hetzner server)

One job backs up every app database on the Kadena Nexus server each night, checks each dump can be read back, keeps
14 days on the server and copies them to off-server storage. It replaces the per-app "confirm backups" items
(marketplace #5, earn #1, adoption-index #1). Earn's own local backup process can keep running alongside it.

| File | Installed as |
|---|---|
| `backup-databases.sh` | `/usr/local/bin/kadena-backup-databases` |
| `restore-test.sh` | `/usr/local/bin/kadena-restore-test` |
| `kadena-backups.conf.example` | `/etc/kadena-backups.conf` (edited, mode 600) |
| `kadena-backups.service`, `kadena-backups.timer` | `/etc/systemd/system/` |

It runs at **03:15 UTC** (06:15 Riyadh), dumps as the `postgres` user (no database passwords anywhere), and never
prints or copies the apps' `.env` files.

## 1. Off-server storage (Saudi.KDA, once)

In the Hetzner console, order the smallest **Storage Box** (in a different location from the server if offered). Then,
in its settings:
- turn on **SSH support** (port 23);
- turn on **automatic snapshots** (daily, keep at least 14). Snapshots are the protection if this server is ever
  compromised: the server's key can change files, but cannot delete the box's snapshots.

Send whoever runs step 2 the box's username (`u123456`) in a disappearing message. Its password is only needed once,
in step 2.

## 2. Install on the server (Mustafa, about 15 minutes)

    # from a checkout of KadenaNexus/homepage on the server
    sudo install -m 755 deploy/backups/backup-databases.sh /usr/local/bin/kadena-backup-databases
    sudo install -m 755 deploy/backups/restore-test.sh    /usr/local/bin/kadena-restore-test
    sudo install -m 600 deploy/backups/kadena-backups.conf.example /etc/kadena-backups.conf
    sudo install -m 644 deploy/backups/kadena-backups.service deploy/backups/kadena-backups.timer /etc/systemd/system/
    sudo apt-get install -y rsync

    # which databases exist
    sudo -u postgres psql -Atc "SELECT datname FROM pg_database WHERE NOT datistemplate"

Edit `/etc/kadena-backups.conf`: put every app database in `DATABASES` (marketplace `kadena_nexus`, preview
`kadena_advanced`, plus Earn's and the Adoption Index's), and leave `REMOTE` empty for now. Then run it once by hand:

    sudo kadena-backup-databases
    sudo kadena-restore-test kadena_nexus        # repeat for each database; prints tables and rows restored

### Connect the Storage Box

    sudo ssh-keygen -t ed25519 -N '' -f /root/.ssh/kadena-backups -C kadena-backups
    # install the key on the box (asks for the box password once)
    sudo cat /root/.ssh/kadena-backups.pub | ssh -p 23 u123456@u123456.your-storagebox.de install-ssh-key
    # pin the box's host key, then make the folder
    sudo ssh -p 23 -i /root/.ssh/kadena-backups u123456@u123456.your-storagebox.de mkdir -p kadena-db

Set in `/etc/kadena-backups.conf`:

    REMOTE=u123456@u123456.your-storagebox.de:kadena-db

Run `sudo kadena-backup-databases` again; it should end with "Off-server copy done". Then turn the schedule on:

    sudo systemctl daemon-reload
    sudo systemctl enable --now kadena-backups.timer
    systemctl list-timers kadena-backups.timer

### Optional alert when a night is missed

Create a free check at healthchecks.io (period 1 day, grace 2 hours, email Saudi.KDA) and put its ping URL in
`HEALTHCHECK_URL`. A failed or skipped night then sends an email.

## Checking and restoring

- Last runs: `journalctl -u kadena-backups --since -3d`
- Files: `sudo ls -lh /var/backups/kadena-db`
- Prove a restore any time (uses a throwaway database, never the live one): `sudo kadena-restore-test <database>`
- Do one restore test a month and note the date in the matching repository's DEPLOY.md.

To restore for real, stop the app's PM2 process first, then:

    sudo -u postgres pg_restore --clean --if-exists --no-owner --dbname=<database> < /var/backups/kadena-db/<file>.dump

Older days than the server keeps are on the Storage Box (`kadena-db/`) and in its snapshots.

## Not covered here

- Kadena Garden runs on the Saudi node, not this server; its backups follow the Garden repository.
- The apps' `.env` files and keys are deliberately not backed up here. Keep their secrets where they are kept today.

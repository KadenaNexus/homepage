# nginx DNS and reboot recovery

Prepared after the 5 November 2026 outage: a package update restarted nginx
while systemd-resolved was starting. Resolving the crawler hostname during
nginx's configuration test prevented every vhost from starting.

The crawler snippet in `../kadena-ws-update/crawler-proxy.conf` now resolves
through `127.0.0.53` during requests, with a 300 second DNS cache and a five
second resolver timeout. It is currently included by both kadena.ws and
nodes.kadena.ws. TLS verification, SNI, the Host header and read-only routes
are preserved. `$is_args$args` explicitly preserves parameters such as
`history?horas=48` when using variable `proxy_pass` URLs
([nginx documentation](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass)).

`nginx-restart.conf` retries a failed nginx service after five seconds.
`apt-daily-upgrade-schedule.conf` replaces the inherited calendar with
00:30 UTC every day, removes randomized delay, and narrows timer accuracy
to one second. The vendor's `Persistent=true` is retained, so missed upgrades
can still run after the server next boots.

Run from a current checkout on the server:

```sh
sudo bash deploy/nginx-resilience/install.sh
```

For a standalone staging directory, place `install.sh`, the two systemd
drop-ins and a copy of `crawler-proxy.conf` together. The installer snapshots
the inputs, refuses an unexpected existing crawler configuration, saves the
previous files and incident journal under `/var/backups/kadena-nginx-recovery`,
then installs and validates the DNS fix before applying the systemd changes.
It reloads nginx and reschedules only the upgrade timer; it does not reboot
the server, restart nginx/DNS, restart current PM2 managers, or change firewall
rules. A failed configuration phase restores that phase's previous files.

It also stops and disables `pm2-tahir`, `pm2-developer` and `pm2-earnest` when
present, as these are retired services. On inspection, only `pm2-tahir` was
present and active after the reboot, with the old GeoPoints and Strapi apps;
`pm2-root` and `pm2-mustafa` manage the current apps and are retained.

The final checks print the effective restart/timer settings and check the
nodes JSON endpoint plus `history?horas=1`. If the external crawler is down,
the installer reports that validation failure while retaining the completed
DNS resilience fix.

# Event-Day Runbook — Sparky's DNA Bet

For the live event (~75 guests, mostly on phones, in concentrated bursts: the betting
window and the results-reveal moment). The site is served Cloudflare → cloudflared tunnel →
this container on `localhost:9999`. The home uplink is the single shared pipe, so the goal of
this checklist is to keep that pipe and the origin healthy while everyone hits the site at once.

## Before each session
- [ ] **Free up upstream bandwidth.** Pause qBittorrent and SABnzbd; avoid Plex remote
      streaming / transcoding during the session. The tunnel competes with these for upload.
- [ ] **Freeze deploys.** Do NOT rebuild or restart the `sparky-dog-bet-web-1` or `cloudflared`
      containers during the event — a stop→start gap shows up as `connection refused` for
      every guest at once. Make any changes well beforehand.
- [ ] **Pre-warm the edge cache** so the first guest isn't the one paying for the origin fetch,
      and confirm `cf-cache-status: HIT`:
      ```
      for u in / /gallery /about /venmo-qr.png; do curl -sI "https://sparky.koubalabs.com$u" | grep -i cf-cache-status; done
      ```
- [ ] **Pre-authenticate the admin panel** on one device (log in at `/admin`) so revealing
      results is a single tap — no password typing under pressure.

## During the session — keep an eye on
- Origin request timing (each line ends with the request duration in seconds):
  ```
  docker logs -f sparky-dog-bet-web-1
  ```
- Tunnel health / reconnects:
  ```
  docker logs -f cloudflared
  ```
  Healthy looks like `Registered tunnel connection ... protocol=http2`. Watch for repeated
  `network is unreachable` or `Unable to reach the origin service`.

## If the site feels slow
1. Check `docker logs cloudflared` for reconnects → it's the tunnel/uplink, not the app.
   Most likely a download/stream resumed and is starving the uplink — pause it.
2. Check `docker logs sparky-dog-bet-web-1` timings → if requests themselves are slow (rare),
   the origin is the issue.
3. `docker stats --no-stream sparky-dog-bet-web-1` for CPU/memory.

## Admin password
Stored in the SQLite `config` table (not in a file, no UI to change it). To change:
```
docker exec sparky-dog-bet-web-1 python -c "from app import db; db.set_config('AdminPassword', 'NEW_PASSWORD')"
```

## After the event
- Resume qBittorrent / SABnzbd as desired.
- Deploys can resume normally (`docker compose up -d --build`).

# Deploying: Vercel (front end) + AWS (back end)

## Simple path: one GPU instance (recommended when the monthly bill is not a concern)

One `g4dn.xlarge` (NVIDIA T4) runs everything in `full` mode: it fetches NOAA, runs the model every time a new GFS cycle or hour
arrives, and serves the API over HTTPS. About **$385 / month** (us-east-1 on-demand; check your region). The front end lives in its own
repo (`bangkok-flood-dashboard-frontend`) and goes to Vercel.

1. **GPU quota first.** New AWS accounts have 0 vCPUs of "Running On-Demand G and VT instances". Service Quotas > Amazon EC2 >
   *Running On-Demand G and VT instances* > request **4** (approved in minutes to a day). Without it the launch is refused.
2. **Launch**: open **AWS CloudShell** (the `>_` icon in the console's top bar, in the region you want) and paste:
   ```
   curl -fsSL https://raw.githubusercontent.com/gojosatorou999/bangkok-flood-surrogate/main/deploy/aws/launch_in_cloudshell.sh | bash
   ```
   It creates a security group (ports 80/443 only), launches the instance with `userdata_single_gpu.sh`, attaches an Elastic IP and
   prints the API address, e.g. `https://203-0-113-10.nip.io`. First boot needs about 10-15 minutes (installs CUDA torch and the
   packages) plus ~2 minutes for the first forecast. Check `curl https://<that address>/api/dash/health`.
3. **Vercel**: import the front-end repo, add the environment variable `FD_API_BASE` = that address, deploy.

The instance bills 24/7 while it exists; stop it from the console when you do not need it. Logs: `/var/log/flood-setup.log` (first
boot), `journalctl -u flood-api -f`. The public API is read-only (every write is refused; the admin token in `/etc/flood.env`
enables CCTV uploads via header `X-Admin-Token`).

The rest of this file describes the cheaper two-machine split (small web box + GPU worker that starts 4 times a day).

---

## The idea, and why it is cheap

Only one step needs a GPU: running the model for the new NOAA forecast (about 46 s on an RTX 4060). NOAA publishes a new
GFS cycle every 6 hours, so that step is needed **4 times a day**, not on every page view. Everything after it (maps,
alerts, point queries) is light work on arrays that already exist.

```
 browser ──► Vercel  (static pages; /api/* is forwarded)
                │
                ▼
          EC2 "web"  t3.small, 24/7, no GPU ── reads ──► S3 bucket  ◄── writes ── EC2 "worker"  g4dn.xlarge
          serves the API from the published bundle        (one bundle,             GPU, powered on by a schedule
                                                           replaced each run)      4x/day, ~6 min, then stops itself
```

| | always-on GPU box | this setup |
|---|---|---|
| compute | g4dn.xlarge 24/7: about **$385 / month** | web t3.small ~ $15 + worker ~ 0.4 h/day ~ **$6** |
| storage | EBS | S3 bundle ~ 17 MB (replaced, never grows) + two small disks |
| total (us-east-1, on-demand, rough) | ~ $390 | **~ $25-30 / month** |

Run the worker only twice a day (06:30 and 18:30 UTC) and it is about $3 instead of $6. Prices vary by region (Singapore is
roughly 30 % higher). Check the AWS pricing page; these are estimates, not a quote.

**There is no database.** The "live data" is (a) NOAA subsets cached as ~200 tiny JSON files and (b) the forecast bundle.
Both are replaced, not accumulated:

* the bundle in S3 is overwritten (`sync --delete`) every run, and a lifecycle rule (below) expires anything older than 2 days,
* the NOAA cache on the worker deletes files older than 36 h (`FLOOD_KEEP_HOURS`),
* the web machine keeps only the newest bundle on disk and in memory,
* the journal is capped at 200 MB.

So yesterday's forecast is gone as soon as today's is published, and storage stays flat.

## 0. Modes of the same code

| `FLOOD_MODE` | what it does | where |
|---|---|---|
| `full` (default) | fetch NOAA, run the model, serve everything | your PC |
| `worker` | `python flood_surrogate.py worker`: one forecast cycle, writes `FLOOD_BUNDLE_DIR`, exits | GPU instance |
| `web` | serves pages + API from the bundle; no model runs; every POST is refused (`FLOOD_READONLY=1`) | small CPU instance |

Other settings: `FLOOD_HOST` (bind address), `PORT`, `FLOOD_CORS_ORIGINS` (comma list, only for direct API calls),
`FLOOD_ADMIN_TOKEN` (enables writes such as CCTV upload via header `X-Admin-Token`), `FLOOD_KEEP_HOURS`.

## 1. GitHub

Already done by the push. Repo: `https://github.com/gojosatorou999/bangkok-flood-surrogate` (public, so it contains no photos,
keys or credentials; the CCTV photos stay on your PC).

## 2. AWS

Pick one region and use it for everything (for Bangkok users `ap-southeast-1`, Singapore, is closest).

1. **S3 bucket** (private), then the expiry rule:
   ```
   aws s3 mb s3://YOUR-BUCKET --region ap-southeast-1
   aws s3api put-bucket-lifecycle-configuration --bucket YOUR-BUCKET --lifecycle-configuration file://deploy/aws/lifecycle.json
   ```
2. **IAM roles** for the two instances and the scheduler: policies in `deploy/aws/iam-policies.md`.
3. **Worker instance** (create it first, you need its id)
   * AMI: *Deep Learning OSS Nvidia Driver AMI GPU PyTorch (Ubuntu)*; type `g4dn.xlarge`; 40 GB gp3; role `flood-worker-role`;
     security group with no inbound rules at all (it needs none).
   * SSH in (or use Session Manager) and run:
     `sudo REPO=https://github.com/gojosatorou999/bangkok-flood-surrogate.git S3_BUCKET=YOUR-BUCKET bash /dev/stdin < <(curl -s https://raw.githubusercontent.com/gojosatorou999/bangkok-flood-surrogate/main/deploy/aws/setup_worker.sh)`
     (or clone the repo and run `deploy/aws/setup_worker.sh`).
   * Test one run: `echo FLOOD_KEEP_RUNNING=1 | sudo tee -a /etc/flood.env`, `sudo /opt/flood/app/deploy/aws/run_worker.sh`,
     read `/var/log/flood-worker.log` (expect "published"), then remove that line from `/etc/flood.env` and **stop the instance**.
4. **Web instance**: Ubuntu 24.04, `t3.small`, 20 GB gp3, role `flood-web-role`, an **Elastic IP**; security group inbound
   80 and 443 from anywhere, 22 from your IP only. Then:
   `sudo REPO=https://github.com/gojosatorou999/bangkok-flood-surrogate.git S3_BUCKET=YOUR-BUCKET API_HOST=<ELASTIC-IP-with-dashes>.nip.io bash deploy/aws/setup_web.sh`
   (for IP `203.0.113.10` the host is `203-0-113-10.nip.io`; with your own domain use that name instead).
   Check: `curl https://203-0-113-10.nip.io/api/dash/health`
5. **Schedule the worker**: GFS cycles 00/06/12/18 UTC are complete about 4 h later, so start it at :30 past 04, 10, 16, 22 UTC.
   ```
   aws scheduler create-schedule --name flood-worker-start --flexible-time-window Mode=OFF \
     --schedule-expression "cron(30 4,10,16,22 * * ? *)" \
     --target '{"Arn":"arn:aws:scheduler:::aws-sdk:ec2:startInstances","RoleArn":"arn:aws:iam::ACCOUNT:role/flood-scheduler-role","Input":"{\"InstanceIds\":[\"i-WORKERID\"]}"}'
   ```
   Each start runs `flood-worker.service` once (boot), the script publishes to S3 and shuts the instance down (instance
   stop behaviour must be *Stop*, the default). A 30-minute watchdog stops it even if something hangs.
   The first time, start it by hand once so the page has data; the web instance picks it up within 5 minutes.

## 3. Vercel

1. Edit `vercel.json` at the repo root: replace `YOUR-API-HOST` with your API host (`203-0-113-10.nip.io`) and push.
2. Vercel: *Add New Project*, import the repo. Framework preset *Other*. The build command, output directory
   (`frontend`) and rewrites come from `vercel.json`. Deploy.
3. `/` is the dashboard and `/workbench` the model workbench (read-only there: running the model is disabled on the web box).

Why a rewrite and not calls straight to AWS: pages and API share one origin (no CORS, no mixed content), your server's
address is hidden, and Vercel's CDN caches the map PNGs (`s-maxage`), so EC2 serves each map frame about once.
Alternative (no proxy): set the Vercel environment variable `FD_API_BASE=https://203-0-113-10.nip.io` and on the web box
`FLOOD_CORS_ORIGINS=https://your-site.vercel.app` in `/etc/flood.env`.

## 4. Operating it

* Logs: worker `/var/log/flood-worker.log`; web `journalctl -u flood-web -f`.
* "Forecast issued ..." in the weather card shows the age of the data. The page marks *now* on the timeline by the clock.
* If the worker fails, the web keeps serving the previous bundle until the next successful run.
* Update code: `git pull` in `/opt/flood/app` and `sudo systemctl restart flood-web` (worker picks it up on its next boot).
* Camera photos are not in the repo (legal review: no redistribution). The *During flood* page works with readings only; to show
  photos copy `data/cctv/thumbs` and `data/cctv/raw` to the web box yourself, and only if you may.

## 5. Further savings and limits

* Worker on **spot**: ~60 % cheaper, may be interrupted (then the previous bundle keeps being served). Not set up here.
* Worker **on your own PC**: run `FLOOD_MODE=worker python flood_surrogate.py worker` then
  `aws s3 sync cache/bundle s3://YOUR-BUCKET/bundle --delete`: AWS GPU cost becomes $0 (only works while your PC is on).
* Memory of the web machine (measured on a CPU-only local run): about 1.1 GB for the live forecast, +0.4 GB while the demo is in use
  (it is loaded on demand and dropped after 10 idle minutes). A `t3.small` (2 GB) plus the 2 GB swap file from `setup_web.sh` is enough;
  a `t3.micro` (1 GB, free tier) is not. If you see the service being killed, use `t3.medium`.
* Not tested on real AWS from here: the scripts were written from the AWS docs; the worker to bundle to web path was
  tested locally on CPU, see the commit message. Expect to fix small things (AMI names, package versions) on the first run.
* Public API: the server refuses every write and has no login. If traffic grows, add rate limiting at Caddy or AWS WAF.

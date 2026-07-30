<!-- repo-convergence:readme-header:start -->
<!-- repo-convergence:language=FILL_ME -->
# yt-dlp-site

<p align="center">
  <a href="https://github.com/whisprer-s-webspinners/yt-dlp-site/releases">
    <img src="https://img.shields.io/github/v/release/whisprer-s-webspinners/yt-dlp-site?color=4CAF50&label=release" alt="Release Version">
  </a>
  <a href="https://github.com/whisprer-s-webspinners/yt-dlp-site/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/license-Hybrid-green.svg" alt="License">
  </a>
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg" alt="Platform">
  <a href="https://github.com/whisprer-s-webspinners/yt-dlp-site/actions">
    <img src="https://img.shields.io/badge/build-workflow%20not%20set-lightgrey.svg" alt="Build Status">
  </a>
</p>

[![GitHub](https://img.shields.io/badge/GitHub-whisprer-s-webspinners%2Fyt-dlp-site-blue?logo=github&style=flat-square)](https://github.com/whisprer-s-webspinners/yt-dlp-site)
![Commits](https://img.shields.io/github/commit-activity/m/whisprer-s-webspinners/yt-dlp-site?label=commits)
![Last Commit](https://img.shields.io/github/last-commit/whisprer-s-webspinners/yt-dlp-site)
![Issues](https://img.shields.io/github/issues/whisprer-s-webspinners/yt-dlp-site)
[![Version](https://img.shields.io/badge/version-3.1.1-blue.svg)](https://github.com/whisprer-s-webspinners/yt-dlp-site)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey.svg)](https://www.microsoft.com/windows)
[![Language](https://img.shields.io/badge/language-FILL_ME-blue.svg)](#)
[![Status](https://img.shields.io/badge/Status-Alpha%20Release-orange?style=flat-square)](#)

<p align="center">
  <img src="/assets/yt-dlp-site-banner.png" width="850" alt="yt-dlp-site Banner">
</p>
<!-- repo-convergence:readme-header:end -->

\# yt.cafe





<p align="center">
  <img src="assets/screenshot-audacity.png" alt="Extracted track in Audacity at 24-bit 48kHz" width="800">
  <br>
  <em>22-minute Veritasium analog computing video, extracted as 24-bit 48kHz stereo WAV</em>
</p>


\*\*A self-hosted, browser-based front-end for `yt-dlp`, designed for VPS deployment behind Cloudflare Zero Trust.\*\*



Live at \[yt.cafe](https://yt.cafe). Paste a URL, hit detect, pick your settings, hit download. The agent runs on the server, the file lands in your browser.



\---



\## What this is



`wofl-dlp` is a thin FastAPI wrapper around `yt-dlp` that gives you a polished web UI for media extraction. It exists because:



\- The CLI is powerful but unfriendly for ad-hoc use from a phone or someone else's machine

\- Hosting it on a VPS lets you keep cookies and config in one place and access from anywhere

\- Cloudflare Zero Trust handles auth so the public surface stays small



The site does one thing well: take a URL, give you the file. Audio extracts can land as 24-bit 48kHz WAV (lossless, mastering-ready), MP3, M4A, FLAC, or Opus. Video can come down as MP4, WebM, MKV, or AVI. Time-range clipping is supported via `?t=` parameters or manual entry — useful for grabbing a specific section of a long video without pulling the whole thing.



The default audio postprocessor chain is set up for music production rather than podcast-grade compression: PCM 24-bit at 48k, stereo, no video/subtitle streams, ffmpeg stream-copy where possible.



\## Architecture



```

┌─────────────┐        Cloudflare Tunnel        ┌──────────────────────┐

│   Browser       │ ──────────────────────►  │       Cloudflare Edge       │

└─────────────┘                                 │       (Zero Trust auth)     │

&#x20;                                                    └──────────┬───────────┘

&#x20;                                            		            │

&#x20;                                           		            ▼

&#x20;                                        	     ┌──────────────────────┐

&#x20;                                       	     │          VPS: cloudflared   │

&#x20;                                       	     │             ↓               │

&#x20;                                       	     │          FastAPI/uvicorn    │

&#x20;                                       	     │             ↓               │

&#x20;                                      	             │          yt-dlp subprocess  │

&#x20;                                        	     │             ↓               │

&#x20;                                       	     │          ffmpeg (imageio)   │

&#x20;                                        	     └──────────┬───────────┘

&#x20;                                                 		   │

&#x20;                                     		                   ▼

&#x20;                                       	     ┌──────────────────────┐

&#x20;                                      	     	     │         bgutil POT provider │

&#x20;                                       	     │         (127.0.0.1:4416)    │

&#x20;                                     	  	     └──────────────────────┘

```



The backend is FastAPI on uvicorn, served as a systemd unit. Cloudflared maintains a persistent tunnel to Cloudflare's edge, where Zero Trust gates access. There's no inbound port open on the VPS — all traffic flows out through the tunnel.



For YouTube specifically, `bgutil-ytdlp-pot-provider` runs as a separate local service that completes BotGuard challenges and hands `yt-dlp` valid Proof-of-Origin tokens. This is what makes downloads work from a datacenter IP that YouTube would otherwise treat as a bot.



\## What's under the hood



\- \*\*FastAPI + uvicorn\*\* for the HTTP layer

\- \*\*yt-dlp\*\* as the extraction engine, invoked as a subprocess so each job runs in isolation

\- \*\*imageio-ffmpeg\*\* for a vendored ffmpeg binary (no system ffmpeg required)

\- \*\*bgutil-ytdlp-pot-provider\*\* for YouTube PO Token attestation

\- \*\*deno\*\* as the JS runtime for solving YouTube's `n` cipher challenges

\- \*\*yt-dlp-ejs\*\* for the challenge solver script distribution

\- \*\*Cloudflare Tunnel + Zero Trust Access\*\* for auth and ingress

\- \*\*systemd\*\* for service management on the VPS



The UI is plain HTML, vanilla JS, and CSS — no framework, no build step. It talks to the FastAPI backend over a small JSON API: probe a URL for available formats, start a job, poll for status, fetch the resulting file.



\## Why all those moving parts



YouTube extraction in 2026 is a moving target. Late 2025 saw YouTube ship a new `n` parameter cipher requiring a JavaScript runtime to solve. Early 2026 added per-client PO Token requirements that vary by IP reputation — VPS IPs get served the `tv\_downgraded` emergency player whose challenge can't be cracked at all. The current working setup requires:



1\. A modern JS runtime (deno, not node 18) on the same machine as yt-dlp

2\. The EJS solver script distribution, fetched from the official yt-dlp/ejs GitHub release

3\. A POT provider running locally to mint PO Tokens for the `web\_safari` and other clients

4\. Explicit exclusion of the `tv` / `tv\_downgraded` clients from yt-dlp's default selection

5\. Cookies (for age-gated and member-only content)



`wofl-dlp` wires all of this up so the user just sees a URL field and a download button.



\## Features



\- URL probe with format detection — see exactly what streams are available before committing

\- Auto-detection of `?t=` timecodes for instant five-minute clip generation

\- Clipping with stream-copy for audio (no quality loss, no re-encode)

\- 24-bit 48kHz WAV output for audio mastering workflows

\- Lossless audio paths for MP3 (V0), M4A, FLAC, and Opus

\- Configurable JS runtime selection with auto-detection

\- Optional cookies file for authenticated downloads

\- Job-isolated cache directories so concurrent downloads don't collide

\- Live progress streaming to the UI

\- "Save file" button that hands the result to the browser via standard download



\## Security model



The site is publicly reachable but \*\*login-gated by Cloudflare Access\*\*. Access policy is configured in the Cloudflare Zero Trust dashboard — typically email-based with a list of allowed addresses, but anything Cloudflare supports (Google SSO, GitHub, one-time PIN, hardware key) works.



Origin validation in the FastAPI app can be relaxed (`Public mode` toggle in Settings) when running behind Cloudflare Access, since auth has already happened upstream.



There is no rate limiting in the app itself — Cloudflare's own rules handle that at the edge.



The cookies file is stored on the VPS only. It's never transmitted to the browser.



\## Acknowledgements \& dependencies



This project stands on a tower of excellent open-source work:



\- \[yt-dlp](https://github.com/yt-dlp/yt-dlp) — the extraction engine that does the actual work

\- \[yt-dlp-ejs](https://github.com/yt-dlp/ejs) — the challenge solver script distribution

\- \[bgutil-ytdlp-pot-provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider) — the POT provider that makes VPS-hosted YouTube extraction viable

\- \[FastAPI](https://github.com/fastapi/fastapi) and \[uvicorn](https://github.com/encode/uvicorn) — the web framework and ASGI server

\- \[imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) — vendored ffmpeg binaries

\- \[Cloudflare Tunnel](https://github.com/cloudflare/cloudflared) — the secure ingress layer

\- \[Deno](https://github.com/denoland/deno) — the JS runtime that solves the `n` cipher challenges



\## Notes on legitimate use



`yt-dlp` and tools like it are dual-use: they make personal archival, accessibility transcoding, transcript extraction, and offline use cases possible, but they're also capable of being used in ways that violate platform terms of service or copyright. `wofl-dlp` is intended for media you own, created, or have the right to download — research and educational use, format-shifting your own purchases, archiving public-domain or Creative Commons material, capturing your own livestreams, and similar. The UI says this on the front page; the reminder bears repeating here.



\## Status



Functional and used daily as of May 2026. The yt-dlp/YouTube interaction surface changes frequently; the codebase is structured to make those updates one-line changes rather than rewrites.



\---



Built by \[Wofl](https://whispr.dev) — with help from Claude on the gnarlier debugging stretches.


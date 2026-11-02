# ADR 001: native workstation delivery

Accepted by the implementation plan. Native Linux supersedes the historical Colab-first acceptance path. Use mise for host tool selection, uv and its lock for Python dependencies, and npm ci for the React website. No privileged install or shell-profile modification is required. Ubuntu 24.04 ARM64 is the locally exercised host; CI declares additional targets but does not constitute evidence until it runs.

The repository remains `tresata`; the Python distribution remains `index-earnings-nowcast`, imported as `nowcast`. Renaming is deferred until an explicit naming decision and migration plan exist.

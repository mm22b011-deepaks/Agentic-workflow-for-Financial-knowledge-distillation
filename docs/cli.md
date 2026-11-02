# CLI reference

Generated from Typer.

```text
                                                                                
 Usage: root [OPTIONS] COMMAND [ARGS]...                                        
                                                                                
 Tresata: index-level earnings proxies and workstation controls.                
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --install-completion          Install completion for the current shell.      │
│ --show-completion             Show completion for the current shell, to copy │
│                               it or customize the installation.              │
│ --help                        Show this message and exit.                    │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ build-constituents  Run the build-constituents pipeline stage.               │
│ estimate-scope      Run the estimate-scope pipeline stage.                   │
│ ingest              Run the ingest pipeline stage.                           │
│ aggregate           Run the aggregate pipeline stage.                        │
│ run-all             Run the run-all pipeline stage.                          │
│ validate-config     Validate configuration; strict also checks environment   │
│                     credentials.                                             │
│ extract             Extract releases; limits and sampling are explicit       │
│                     verification controls.                                   │
│ rebuild-index       Rebuild a candidate into the configured target,          │
│                     preserving its backup.                                   │
│ model-bakeoff       Run isolated, ledger-backed model comparison on the same │
│                     sample.                                                  │
│ validate-index      Check an index and raw hashes in place; never replace    │
│                     any artifacts.                                           │
│ supersede-stale     Explicitly archive results with a verifiably stale       │
│                     settings fingerprint.                                    │
│ demo                Run the deterministic 500-release offline verification.  │
│ freeze-panel        Freeze the private seeded 150-company verification       │
│                     panel, offline.                                          │
│ serve               Serve the workstation website and API on all IPv4        │
│                     interfaces.                                              │
╰──────────────────────────────────────────────────────────────────────────────╯


```

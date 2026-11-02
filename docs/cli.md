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
│ validate-config     check config values and required env                     │
│ build-constituents  build the point-in-time constituents CSV                 │
│ estimate-scope      estimate documents and tokens, offline                   │
│ ingest              download and index earnings documents                    │
│ rebuild-index       validate an index into data.document_index               │
│ extract             run LLM extraction over indexed documents                │
│ aggregate           aggregate extractions into index-level rows              │
│ model-bakeoff       measure every configured model on one sample             │
│ run-all             run every stage in order                                 │
│ doctor              check credentials, contact, models, disk and quota       │
│ freeze-panel        freeze the selected fixed panel                          │
│ validate-index      validate an index in place                               │
│ supersede-stale     explicitly archive stale extraction results              │
│ demo                run the 500-release offline verification                 │
│ serve               serve the workstation website on all IPv4 interfaces     │
│ export              export identifier-free index artifacts                   │
│ prepare-labels      prepare a private thirty-record label sheet              │
│ quality-summary     write the quality and human-gate summary                 │
│ report              write the current quality report                         │
│ cohort              execute cohort phase                                     │
│ discover            execute discover phase                                   │
│ download            execute download phase                                   │
│ parse               execute parse phase                                      │
│ validate            execute validate phase                                   │
│ consolidate         execute consolidate phase                                │
│ review              execute review phase                                     │
│ gate                execute gate phase                                       │
│ publish             execute publish phase                                    │
│ suppressed          execute suppressed phase                                 │
│ schedule            plan and run quota-aware tasks                           │
╰──────────────────────────────────────────────────────────────────────────────╯


```

## nowcast

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |

## validate-config

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |
| --strict | False | also require the secret environment variables to be set |

## build-constituents

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## estimate-scope

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## ingest

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## rebuild-index

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |
| --source |  | index to validate (default: the pre-v2 index) |
| --force | False | replace a populated data.document_index after backing it up |

## extract

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |
| --limit | 0 | only the first N documents |
| --sample | 0 | N documents, one per company first and spread across seasons |
| --seed | None | seed for --sample |

## aggregate

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## model-bakeoff

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |
| --sample | 10 | documents each model is measured on |
| --model | [] | model (repeatable) |
| --labels | None | supplied human labels |

## run-all

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |
| --limit | 0 | only the first N documents |
| --sample | 0 | N documents, one per company first and spread across seasons |
| --seed | None | seed for --sample |

## doctor

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |
| --verify-provider | False | verify authenticated quota and zero model pricing |

## freeze-panel

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## validate-index

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |
| --source | None | index to validate in place |

## supersede-stale

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## demo

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## serve

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |
| --port | 8767 | website TCP port |

## export

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## prepare-labels

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## quality-summary

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## report

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## cohort

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## discover

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## download

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## parse

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## validate

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## consolidate

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## review

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## gate

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## publish

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## suppressed

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## schedule

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |

## schedule plan

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## schedule status

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## schedule run

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |
| --start-models | False | start the approved model day now after Day 0 |
| --once | False | perform due work and exit (default) |
| --daemon | False | wait and perform due work continuously |
| --automatic | False | respect the configured daily UTC run time |

## schedule pause

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |

## schedule resume

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |
| --confirm-models | False | human approval of model batches |

## schedule install

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |
| --confirm | False | approve the displayed timer changes |

## schedule uninstall

| Flag | Default | Meaning |
|---|---|---|
| -h, --help | ==SUPPRESS== | show this help message and exit |
| --config | configs/config.yaml | path to config YAML |
| --set | None | override a dotted config key (repeatable) |
| --confirm | False | approve the displayed timer changes |

# Shared Codex setup for every workstation

The authoritative personal setup repository is:
[time2makecents-ops/codex-personal-setup](https://github.com/time2makecents-ops/codex-personal-setup).
It contains personal rules, settings, reusable commands, and the port registry.
Keep changes there so other workstations can receive them. Keep Veridex-specific
instructions in this repository.

## Normal startup

Open PowerShell in your Veridex checkout and run:

```powershell
codexxx
```

The command checks the shared repository, safely applies clean fast-forward
updates with backups, verifies personal and project rules, and starts Codex with
full access and approval mode `never`. Local edits or conflicting settings stop
startup. If GitHub is unavailable, it may use the last verified installed setup;
that does not verify the freshness needed to allocate new ports.

`codexxx -Check` performs startup verification without opening an interactive
Codex session. Starting plain `codex` or a desktop chat does not guarantee that
the shared-repository check ran.

## Install on another Windows computer

Install Git, Python 3.11 or newer, and Codex; authenticate separately on that
computer. Clone the private setup repository using the intended GitHub account:

```powershell
git clone https://github.com/time2makecents-ops/codex-personal-setup.git "$HOME\codex-personal-setup"
python "$HOME\codex-personal-setup\setup.py" preview
python "$HOME\codex-personal-setup\setup.py" apply
```

If that checkout already exists, inspect its local changes first and use
`git pull --ff-only` from a clean checkout instead of cloning again. Then run
preview and apply. Do not overwrite or discard local changes to make setup pass.

Open a new PowerShell window, return to the Veridex checkout, and run
`codexxx -Check`, then `codexxx`. Setup manages a marked profile block while
preserving existing commands, including any machine-local `veridex` definition.
See the setup repository's README for customized `CODEX_HOME` locations and
loading commands into an already-open shell. Its `COMMANDS.md` explains adding
portable commands to `shared/commands.json`.

## Existing Codex session

If there is no successful launcher check for this session, run the shared setup
diagnostic once, using the actual Veridex checkout as the workspace:

```powershell
python "$HOME\codex-personal-setup\setup.py" diagnose --workspace . --verify-prompt --check-remote --brief
```

If the source was installed elsewhere, resolve it from the local setup state at
`<CODEX_HOME>/.personal-setup/state.json`; the default source above is a convention,
not a required machine path. Follow the setup repository's update instructions
when updates are reported. Installed copies are not the policy editing authority.

Do not copy credentials, browser profiles, transcripts, or the entire `.codex`
directory between computers. A successful check on one workstation does not
verify another workstation's authentication or installed dependencies.


## Pending shared setup publication (separate from Veridex app folder)

The canonical `codex-personal-setup` repository currently has two local unpublished changes for HTTPS port 9228: `shared/ports.json` and `bundle-lock.json`. Its dirty-source guard still applies. Publication authorization is unresolved; do not treat a Veridex commit or push as publishing these setup changes, and do not claim a global 9228 reservation before publication. HTTP 9227 is separately published.

- [ ] Resolve explicit authorization for the two-file shared setup publication, then follow that repository's preview/apply and commit/push workflow.
- [ ] After publication and a clean source checkout, run `codexxx -Check` on this workstation and record its actual result.
- [ ] On the other workstation, run its setup diagnostic, authenticate Codex/GitHub separately, and confirm its logical machine role and existing port assignments before using it.

The setup repository's 51-test result is historical and was not rerun for this checkpoint. The Veridex app folder is a separate checkout. A Veridex commit/push does not publish shared setup policy or registry files. See `handoffs/workspace-checkpoint.md` for the current repository checkpoint.
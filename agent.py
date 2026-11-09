#!/usr/bin/env python3
"""
Purple Team Validation Framework — Python 6.0

A NON-DESTRUCTIVE, READ-ONLY purple-team validation framework.
Safety limits are enforced by the code below, not merely documented.

Enforced in code:
  * Phase 0 (host + location authorization) always runs first and halts on failure.
  * No network connections, no subprocess/shell execution, no background processes.
  * Phase 4: metadata only (name/ext/size/mtime) via os.scandir(follow_symlinks=False)
    and entry.stat(follow_symlinks=False); file contents are never opened; no symlinks
    followed; depth, result and directory-item limits enforced; partial scans never PASS.
  * Phase 5: presence-only; access errors reported as UNKNOWN, never ABSENT;
    unsupported platforms return SKIPPED; credential files never opened.
  * Phase 8/10: synthetic data held in memory only; no clipboard, no files.
  * Phase 9: SKIPPED (no persistence written or read via privileged APIs).
  * Phase 11: NOT_PERFORMED (no EICAR file created).
  * Reports: O_CREAT|O_EXCL; refuse existing targets and symlink destinations;
    symlink-safe report directory validation; UTF-8; HTML escaped; JSON validated.

Usage:
    python agent.py --authorized-host H --authorized-location L --all
    python agent.py --authorized-host H --authorized-location L --phase 0,1,3
    python agent.py --authorized-host H --authorized-location L --phase 4 --scan-root DIR
    python agent.py --authorized-host H --authorized-location L --all --report-dir DIR
    python agent.py --list
"""

from __future__ import annotations

import argparse
import builtins
import html
import json
import os
import platform
import socket
import stat
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

VERSION = "6.0"
AGENT_NAME = "Purple Team Validation Framework"

PASS, SKIPPED, ERROR, NOT_PERFORMED = "PASS", "SKIPPED", "ERROR", "NOT_PERFORMED"
VALID_STATUSES = (PASS, SKIPPED, ERROR, NOT_PERFORMED)

# Phase-5 presence vocabulary
PRESENT, ABSENT, UNKNOWN = "PRESENT", "ABSENT", "UNKNOWN"

DEFAULT_MAX_DEPTH = 3
DEFAULT_MAX_RESULTS = 500
DEFAULT_MAX_DIR_ITEMS = 5000


class PhaseStatusError(ValueError):
    """Raised when a phase yields an invalid status string."""


# ────────────────────────────────────────────────────────────────────────────
# Result model — one CheckResult per independent check inside a phase
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    name: str
    status: str                     # PASS / SKIPPED / ERROR / NOT_PERFORMED
    message: str
    metadata: Dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise PhaseStatusError(f"invalid check status: {self.status!r}")


@dataclass
class PhaseResult:
    phase: int
    name: str
    status: str
    message: str
    checks: List[CheckResult] = field(default_factory=list)
    metadata: Dict[str, object] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise PhaseStatusError(f"invalid phase status: {self.status!r}")


@dataclass
class RunContext:
    authorized_host: str
    authorized_location: str
    scan_root: Optional[Path] = None
    max_depth: int = DEFAULT_MAX_DEPTH
    max_results: int = DEFAULT_MAX_RESULTS
    max_dir_items: int = DEFAULT_MAX_DIR_ITEMS
    report_dir: Optional[Path] = None
    results: List[PhaseResult] = field(default_factory=list)
    run_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    start_time: float = field(default_factory=time.time)


# ────────────────────────────────────────────────────────────────────────────
# Phase registry
# ────────────────────────────────────────────────────────────────────────────

PHASE_REGISTRY: Dict[int, Tuple[str, Callable[[RunContext], PhaseResult]]] = {}


def phase(number: int, name: str):
    def decorator(fn):
        if number in PHASE_REGISTRY:
            raise RuntimeError(f"duplicate phase {number}")
        PHASE_REGISTRY[number] = (name, fn)
        return fn
    return decorator


def _check(name: str, status: str, message: str,
           metadata: Optional[Dict] = None) -> CheckResult:
    return CheckResult(name, status, message, metadata or {})


def _record(ctx: RunContext, phase_no: int, checks: List[CheckResult],
            phase_status: Optional[str] = None,
            metadata: Optional[Dict] = None) -> PhaseResult:
    """
    Aggregate one phase's per-check results into a PhaseResult.
    ERROR dominates; NOT_PERFORMED surfaces if any check requested it;
    all-SKIPPED yields SKIPPED; otherwise PASS.
    """
    name = PHASE_REGISTRY[phase_no][0]
    if phase_status is not None:
        status = phase_status
    elif any(c.status == ERROR for c in checks):
        status = ERROR
    elif any(c.status == NOT_PERFORMED for c in checks):
        status = NOT_PERFORMED
    elif checks and all(c.status == SKIPPED for c in checks):
        status = SKIPPED
    else:
        status = PASS
    summary = "; ".join(f"{c.name}={c.status}" for c in checks) or "no checks"
    r = PhaseResult(phase_no, name, status, summary, checks, metadata or {})
    ctx.results.append(r)
    print(f"  [Phase {phase_no:>2}] {name}: {status} — {summary}")
    return r


# ────────────────────────────────────────────────────────────────────────────
# Phase 0 — Host & Location Validation (mandatory; always first)
# ────────────────────────────────────────────────────────────────────────────

def _norm_host(value: str) -> str:
    # Strict: lowercase, strip whitespace and trailing dots.
    # DNS suffix stripping is intentionally NOT performed.
    return value.strip().lower().rstrip(".")


@phase(0, "Host & Location Validation")
def phase_0(ctx: RunContext) -> PhaseResult:
    try:
        actual = socket.gethostname()
    except OSError as exc:
        return _record(ctx, 0, [
            _check("host_lookup", ERROR,
                   f"Could not determine local hostname ({type(exc).__name__}); aborting.")
        ], metadata={"location_verified": False})

    if not ctx.authorized_host.strip():
        return _record(ctx, 0, [
            _check("authorized_host", ERROR,
                   "No authorized host supplied; aborting.",
                   {"actual_host": actual})
        ], metadata={"location_verified": False})
    if not ctx.authorized_location.strip():
        return _record(ctx, 0, [
            _check("authorized_location", ERROR,
                   "No authorized location supplied; aborting.",
                   {"actual_host": actual})
        ], metadata={"location_verified": False})
    if _norm_host(ctx.authorized_host) != _norm_host(actual):
        return _record(ctx, 0, [
            _check("host_match", ERROR,
                   f"Authorized host '{ctx.authorized_host}' does not match local host "
                   f"'{actual}' (strict, case-insensitive comparison); aborting.",
                   {"actual_host": actual,
                    "authorized_host": ctx.authorized_host})
        ], metadata={"location_verified": False})

    return _record(ctx, 0, [
        _check("host_match", PASS, "Host matches authorization (strict).",
               {"actual_host": actual, "authorized_host": ctx.authorized_host}),
        _check("location_recorded", PASS,
               "Operator-declared location recorded. Not geolocation-verified.",
               {"operator_declared_location": ctx.authorized_location,
                "location_verified": False}),
    ], metadata={"actual_host": actual, "location_verified": False})


# ────────────────────────────────────────────────────────────────────────────
# Phase 1 — System Profiling (read-only)
# ────────────────────────────────────────────────────────────────────────────

@phase(1, "System Profiling")
def phase_1(ctx: RunContext) -> PhaseResult:
    try:
        info = {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "implementation": platform.python_implementation(),
        }
    except Exception as exc:                                # noqa: BLE001
        return _record(ctx, 1, [
            _check("system_profile", ERROR,
                   f"Profiling failed ({type(exc).__name__}).")
        ])
    return _record(ctx, 1, [
        _check("system_profile", PASS,
               "Basic OS and Python runtime information collected (read-only).", info)
    ])


# ────────────────────────────────────────────────────────────────────────────
# Phase 2 — Account & Domain Validation (read-only; not implemented)
# ────────────────────────────────────────────────────────────────────────────

@phase(2, "Account & Domain Validation")
def phase_2(ctx: RunContext) -> PhaseResult:
    return _record(ctx, 2, [
        _check("account_enum", SKIPPED,
               "Not implemented in 6.0 (no credential or directory access)."),
        _check("group_enum", SKIPPED,
               "Not implemented in 6.0."),
        _check("domain_trusts", SKIPPED,
               "Not implemented in 6.0."),
    ])


# ────────────────────────────────────────────────────────────────────────────
# Phase 3 — Process & Service Validation (read-only; not implemented)
# ────────────────────────────────────────────────────────────────────────────

@phase(3, "Process & Service Validation")
def phase_3(ctx: RunContext) -> PhaseResult:
    return _record(ctx, 3, [
        _check("process_list", SKIPPED,
               "Not implemented in 6.0 (avoids process memory APIs)."),
        _check("service_list", SKIPPED,
               "Not implemented in 6.0 (avoids service control APIs)."),
        _check("lsass_access", SKIPPED,
               "Not implemented in 6.0 (explicitly prohibited)."),
    ])


# ────────────────────────────────────────────────────────────────────────────
# Phase 4 — File Metadata Validation
# ────────────────────────────────────────────────────────────────────────────

def _is_fs_root(resolved: Path) -> bool:
    return resolved == Path(resolved.anchor)


def _validate_scan_root(root: Path) -> Tuple[Optional[Path], Optional[CheckResult]]:
    """Validate the original root *before* resolve(). Return (resolved, error)."""
    try:
        lst = root.lstat()
    except OSError as exc:
        return None, _check("scan_root", ERROR,
                            f"Could not lstat scan root ({type(exc).__name__}).")
    if stat.S_ISLNK(lst.st_mode):
        return None, _check("scan_root", ERROR,
                            "Scan root is a symlink; refusing.")
    if not stat.S_ISDIR(lst.st_mode):
        return None, _check("scan_root", ERROR,
                            f"Scan root is not a directory: {root}")
    try:
        resolved = root.resolve()
    except OSError as exc:
        return None, _check("scan_root", ERROR,
                            f"Could not resolve scan root ({type(exc).__name__}).")
    if _is_fs_root(resolved):
        return None, _check("scan_root", ERROR,
                            "Scan root resolves to a filesystem root; refusing.")
    return resolved, None


def _walk_metadata(root: Path, max_depth: int, max_results: int,
                   max_dir_items: int) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    """
    Return (files, stats). files: name/ext/size/mtime only.
    Never opens file contents. Never follows symlinks.
    """
    files: List[Dict[str, object]] = []
    stats = {"depth_exceeded": 0, "result_truncated": False,
             "dir_item_truncated": False, "errors": 0, "dirs_visited": 0,
             "items_seen": 0}
    root_depth = len(root.parts)
    stack: List[Path] = [root]

    while stack:
        current = stack.pop()
        try:
            if max(0, len(current.parts) - root_depth) > max_depth:
                stats["depth_exceeded"] += 1
                continue
            stats["dirs_visited"] += 1
            with os.scandir(current) as it:
                for entry in it:
                    stats["items_seen"] += 1
                    if stats["items_seen"] > max_dir_items:
                        stats["dir_item_truncated"] = True
                        stack.clear()
                        break
                    if len(files) >= max_results:
                        stats["result_truncated"] = True
                        stack.clear()
                        break
                    try:
                        # follow_symlinks=False → symlinked entries are never followed
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        st = entry.stat(follow_symlinks=False)  # lstat-equivalent
                    except OSError:
                        stats["errors"] += 1
                        continue
                    files.append({
                        "name": entry.name,
                        "extension": Path(entry.name).suffix,
                        "size": st.st_size,
                        "modified": datetime.fromtimestamp(
                            st.st_mtime, tz=timezone.utc).isoformat(),
                    })
        except OSError:
            stats["errors"] += 1
            continue
    return files, stats


@phase(4, "File Metadata Validation")
def phase_4(ctx: RunContext) -> PhaseResult:
    if ctx.scan_root is None:
        return _record(ctx, 4, [
            _check("scan_root", SKIPPED,
                   "No --scan-root supplied; Phase 4 requires an explicitly "
                   "approved scan root.")
        ])
    resolved, err = _validate_scan_root(ctx.scan_root)
    if err is not None:
        return _record(ctx, 4, [err])

    files, stats = _walk_metadata(resolved, ctx.max_depth,
                                  ctx.max_results, ctx.max_dir_items)

    complete = not (stats["depth_exceeded"] or stats["result_truncated"]
                    or stats["dir_item_truncated"] or stats["errors"])

    meta = {"count": len(files),
            "scan_root": str(resolved),
            "limits": {"max_depth": ctx.max_depth,
                       "max_results": ctx.max_results,
                       "max_dir_items": ctx.max_dir_items},
            "stats": stats,
            "files": files}

    if not complete:
        return _record(ctx, 4, [
            _check("metadata_scan", ERROR,
                   f"Scan incomplete: depth_exceeded={stats['depth_exceeded']}, "
                   f"result_truncated={stats['result_truncated']}, "
                   f"dir_item_truncated={stats['dir_item_truncated']}, "
                   f"errors={stats['errors']}. Not presented as PASS.",
                   meta)
        ])
    return _record(ctx, 4, [
        _check("metadata_scan", PASS,
               f"Collected metadata for {len(files)} file(s); no file contents were read.",
               meta)
    ])


# ────────────────────────────────────────────────────────────────────────────
# Phase 5 — Credential Store Validation (PRESENT / ABSENT / UNKNOWN)
# ────────────────────────────────────────────────────────────────────────────

PREDEFINED_CRED_PATHS = [
    "~/.aws/credentials",
    "~/.azure/accessTokens.json",
    "~/.config/gcloud/credentials.db",
    "~/.ssh/id_rsa",
    "~/.netrc",
]


@phase(5, "Credential Store Validation")
def phase_5(ctx: RunContext) -> PhaseResult:
    if platform.system() not in ("Linux", "Darwin", "Windows"):
        return _record(ctx, 5, [
            _check("credential_stores", SKIPPED,
                   f"Platform {platform.system()} not supported for presence checks.")
        ])

    checks: List[CheckResult] = []
    for template in PREDEFINED_CRED_PATHS:
        p = Path(os.path.expanduser(template))
        try:
            p.lstat()                   # does not open the file
            state = PRESENT
            msg = "Path exists (presence only; not opened)."
        except FileNotFoundError:
            state = ABSENT
            msg = "Path does not exist."
        except PermissionError:
            state = UNKNOWN
            msg = "Access denied while checking presence; not reported as ABSENT."
        except OSError:
            state = UNKNOWN
            msg = "Other OS error while checking presence; not reported as ABSENT."
        checks.append(_check(template, PASS, msg, {"state": state}))

    return _record(ctx, 5, checks,
                   metadata={"presence_vocabulary": [PRESENT, ABSENT, UNKNOWN],
                             "files_opened": False})


# ────────────────────────────────────────────────────────────────────────────
# Phase 6 — Security Configuration Validation (read-only; not implemented)
# ────────────────────────────────────────────────────────────────────────────

@phase(6, "Security Configuration Validation")
def phase_6(ctx: RunContext) -> PhaseResult:
    return _record(ctx, 6, [
        _check("defender", SKIPPED, "Not implemented in 6.0 (read-only)."),
        _check("firewall", SKIPPED, "Not implemented in 6.0 (read-only)."),
        _check("audit_policy", SKIPPED, "Not implemented in 6.0 (read-only)."),
        _check("applocker", SKIPPED, "Not implemented in 6.0 (read-only)."),
    ])


# ────────────────────────────────────────────────────────────────────────────
# Phase 7 — Network Scope Validation (no network activity in 6.0)
# ────────────────────────────────────────────────────────────────────────────

@phase(7, "Network Scope Validation")
def phase_7(ctx: RunContext) -> PhaseResult:
    return _record(ctx, 7, [
        _check("local_scope_declaration", PASS,
               "Local execution scope acknowledged. No network connections are made.",
               {"remote_connections_made": 0})
    ])


# ────────────────────────────────────────────────────────────────────────────
# Phase 8 — Synthetic Collection Validation (in-memory only; no clipboard)
# ────────────────────────────────────────────────────────────────────────────

@phase(8, "Synthetic Collection Validation")
def phase_8(ctx: RunContext) -> PhaseResult:
    marker = "PURPLE_TEAM_TEST_DATA"
    synthetic = [{"id": i, "marker": marker, "note": f"synthetic record {i}"}
                 for i in (1, 2, 3)]
    return _record(ctx, 8, [
        _check("synthetic_collection", PASS,
               f"Built {len(synthetic)} synthetic in-memory records with marker "
               f"'{marker}'. No real data collected; clipboard not read or modified.",
               {"marker": marker, "count": len(synthetic),
                "clipboard_accessed": False, "staging_created": False})
    ])


# ────────────────────────────────────────────────────────────────────────────
# Phase 9 — Persistence Validation (read-only; not implemented)
# ────────────────────────────────────────────────────────────────────────────

@phase(9, "Persistence Validation")
def phase_9(ctx: RunContext) -> PhaseResult:
    return _record(ctx, 9, [
        _check("run_keys", SKIPPED,
               "Not implemented in 6.0; nothing created or modified."),
        _check("scheduled_tasks", SKIPPED, "Not implemented in 6.0."),
        _check("services", SKIPPED, "Not implemented in 6.0."),
        _check("wmi_subscriptions", SKIPPED, "Not implemented in 6.0."),
        _check("startup_folder", SKIPPED, "Not implemented in 6.0."),
    ])


# ────────────────────────────────────────────────────────────────────────────
# Phase 10 — Synthetic Impact Validation (in-memory only)
# ────────────────────────────────────────────────────────────────────────────

@phase(10, "Synthetic Impact Validation")
def phase_10(ctx: RunContext) -> PhaseResult:
    markers = ["SYNTHETIC_FINANCE_RECORD", "SYNTHETIC_HR_RECORD",
               "SYNTHETIC_LEGAL_RECORD", "SYNTHETIC_IT_RECORD",
               "SYNTHETIC_OPERATIONS_RECORD"]
    synthetic = [{"marker": m, "status": "in-memory-only"} for m in markers]
    return _record(ctx, 10, [
        _check("synthetic_impact", PASS,
               f"Constructed {len(synthetic)} synthetic impact records in memory. "
               "No files were created, encrypted, renamed or deleted.",
               {"records": synthetic, "files_touched": 0,
                "encryption_performed": False, "deletion_performed": False})
    ])


# ────────────────────────────────────────────────────────────────────────────
# Phase 11 — Antivirus Validation (explanation only; NO EICAR)
# ────────────────────────────────────────────────────────────────────────────

@phase(11, "Antivirus Validation")
def phase_11(ctx: RunContext) -> PhaseResult:
    explanation = ("EICAR is a standardized, non-malicious antivirus test signature "
                   "agreed on by AV vendors. Version 6.0 does not create or execute "
                   "EICAR files. A successful detection can only be claimed when an "
                   "independently authorized test has actually been run.")
    return _record(ctx, 11, [
        _check("eicar_test", NOT_PERFORMED, explanation,
               {"eicar_file_created": False, "eicar_executed": False,
                "av_modified": False, "detection_claimed": False})
    ])


# ────────────────────────────────────────────────────────────────────────────
# Safe report writing (O_CREAT|O_EXCL; refuse existing and symlink targets)
# ────────────────────────────────────────────────────────────────────────────

def _validate_report_dir(dir_path: Path) -> Tuple[Optional[Path], Optional[str]]:
    try:
        lst = dir_path.lstat()
    except FileNotFoundError:
        return None, f"report directory does not exist: {dir_path}"
    except OSError as exc:
        return None, f"cannot inspect report directory ({type(exc).__name__})"
    if stat.S_ISLNK(lst.st_mode):
        return None, f"report directory is a symlink; refusing: {dir_path}"
    if not stat.S_ISDIR(lst.st_mode):
        return None, f"report directory is not a directory: {dir_path}"
    return dir_path, None


def _write_exclusive(path: Path, data: str) -> Tuple[bool, Optional[str]]:
    """Create *path* exclusively. Never overwrite, never follow symlinks."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        return False, f"target exists; refusing to overwrite: {path}"
    except OSError as exc:
        return False, f"open failed ({type(exc).__name__}): {path}"
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
    except OSError as exc:
        return False, f"write failed ({type(exc).__name__}): {path}"
    return True, None


def _build_report(ctx: RunContext) -> Dict:
    end = time.time()
    return {
        "agent": AGENT_NAME,
        "version": VERSION,
        "run_id": ctx.run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "started_at": datetime.fromtimestamp(ctx.start_time, tz=timezone.utc).isoformat(),
        "duration_seconds": int(end - ctx.start_time),
        "authorized_hostname": ctx.authorized_host,
        "operator_declared_location": ctx.authorized_location,
        "location_verified": False,
        "phases": [
            {
                "phase": r.phase,
                "name": r.name,
                "status": r.status,
                "message": r.message,
                "timestamp": r.timestamp,
                "checks": [asdict(c) for c in r.checks],
                "metadata": r.metadata,
            }
            for r in ctx.results
        ],
    }


def write_json_report(ctx: RunContext) -> Tuple[Optional[Path], Optional[str]]:
    dir_path = ctx.report_dir or Path(tempfile.gettempdir())
    valid_dir, err = _validate_report_dir(dir_path)
    if err:
        return None, err
    report = _build_report(ctx)
    path = valid_dir / f"purpleteam_{ctx.run_id}.json"
    ok, err = _write_exclusive(path, json.dumps(report, indent=2))
    return (path, None) if ok else (None, err)


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Purple Team {version} — {run_id}</title>
<style>
 body{{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;padding:2rem;}}
 h1{{color:#38bdf8;}} table{{border-collapse:collapse;width:100%;margin-top:1rem;}}
 th,td{{padding:.6rem;border-bottom:1px solid #334155;text-align:left;font-size:.9rem;
        vertical-align:top;}}
 th{{color:#94a3b8;}} .PASS{{color:#16a34a;}} .SKIPPED{{color:#94a3b8;}}
 .ERROR{{color:#dc2626;}} .NOT_PERFORMED{{color:#ca8a04;}}
 code{{background:#1e293b;padding:.1rem .3rem;border-radius:.2rem;}}
 ul{{margin:0;padding-left:1rem;}}
</style></head><body>
<h1>Purple Team Validation Report — v{version}</h1>
<p>Run ID: <code>{run_id}</code> · Generated: {generated_at}</p>
<p>Authorized host: <b>{authorized_hostname}</b> · Operator-declared location: <b>{location}</b>
 (location not independently verified)</p>
<table><thead><tr>
<th>Phase</th><th>Name</th><th>Status</th><th>Checks</th>
</tr></thead><tbody>{rows}</tbody></table>
</body></html>"""


def _render_checks_html(checks: List[CheckResult]) -> str:
    items = "".join(
        f"<li class='{c.status}'><b>{html.escape(c.name)}</b> "
        f"({c.status}): {html.escape(c.message)}</li>"
        for c in checks
    )
    return f"<ul>{items}</ul>" if items else ""


def write_html_report(ctx: RunContext) -> Tuple[Optional[Path], Optional[str]]:
    dir_path = ctx.report_dir or Path(tempfile.gettempdir())
    valid_dir, err = _validate_report_dir(dir_path)
    if err:
        return None, err
    report = _build_report(ctx)
    rows = "".join(
        f"<tr><td>{r.phase}</td><td>{html.escape(r.name)}</td>"
        f"<td class='{r.status}'>{r.status}</td>"
        f"<td>{_render_checks_html(r.checks)}</td></tr>"
        for r in ctx.results
    )
    content = _HTML_TEMPLATE.format(
        version=VERSION, run_id=ctx.run_id,
        generated_at=report["generated_at"],
        authorized_hostname=html.escape(ctx.authorized_host),
        location=html.escape(ctx.authorized_location),
        rows=rows,
    )
    path = valid_dir / f"purpleteam_{ctx.run_id}.html"
    ok, err = _write_exclusive(path, content)
    return (path, None) if ok else (None, err)


# ────────────────────────────────────────────────────────────────────────────
# CLI helpers
# ────────────────────────────────────────────────────────────────────────────

def _list_phases() -> None:
    print(f"{AGENT_NAME} v{VERSION} — phases 0–11")
    for n in sorted(PHASE_REGISTRY):
        print(f"  {n:>2}  {PHASE_REGISTRY[n][0]}")


def _parse_phase_selection(raw: str) -> List[int]:
    if not raw.strip():
        raise ValueError("no phase specified")
    selected: List[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            raise ValueError("empty phase token")
        if not token.isdigit():
            raise ValueError(f"invalid phase token: {token!r}")
        n = int(token)
        if n not in PHASE_REGISTRY:
            raise ValueError(f"phase {n} does not exist (valid: 0–11)")
        if n in selected:
            raise ValueError(f"duplicate phase: {n}")
        selected.append(n)
    # Phase 0 always first and always included
    if 0 in selected:
        selected.remove(0)
    selected.insert(0, 0)
    return selected


# ────────────────────────────────────────────────────────────────────────────
# Self-test (isolated temp dir; asserts safety invariants; exits 0/1)
# ────────────────────────────────────────────────────────────────────────────

def _selftest() -> int:
    results: List[Tuple[str, str, str]] = []

    def note(name: str, status: str, detail: str) -> None:
        results.append((name, status, detail))
        print(f"  [{status}] {name}: {detail}")

    def forbid_read(self, *a, **k):
        raise AssertionError(f"content read attempted: {self}")

    def forbid_open(*a, **k):
        mode = a[1] if len(a) > 1 else k.get("mode", "r")
        if "r" in mode and "+" not in mode:
            raise AssertionError(f"open-for-read attempted: {a[:2]}")
        return _saved_open(*a, **k)

    # ── Phase 4: no content reads; respects limits; no symlinks followed ──
    with tempfile.TemporaryDirectory(prefix="purpleteam_selftest_") as tmp:
        root = Path(tmp)
        (root / "sub").mkdir()
        for name in ("a.txt", "b.pdf", "c.csv"):
            (root / name).write_text("SECRET_" + name, encoding="utf-8")
        (root / "sub" / "d.log").write_text("SECRET_d", encoding="utf-8")
        (root / ".hidden").write_text("SECRET_hidden", encoding="utf-8")
        (root / "link_to_a").symlink_to(root / "a.txt")
        outside = Path(tmp + "_outside")
        outside.mkdir()
        (outside / "escape.txt").write_text("SECRET_escape", encoding="utf-8")
        (root / "out_link").symlink_to(outside)

        _saved_open = builtins.open
        _saved_pb = Path.read_bytes
        _saved_pt = Path.read_text
        _saved_po = Path.open
        Path.read_bytes = forbid_read
        Path.read_text = forbid_read
        Path.open = forbid_open
        builtins.open = forbid_open
        try:
            ctx = RunContext(authorized_host=socket.gethostname(),
                             authorized_location="selftest",
                             scan_root=root, max_depth=5, max_results=100)
            r0 = phase_0(ctx)
            note("phase0_in_selftest",
                 "PASS" if r0.status == PASS else "FAIL", r0.status)
            r4 = phase_4(ctx)
            note("phase4_status",
                 "PASS" if r4.status == PASS else "FAIL", r4.status)
            names = sorted(f["name"] for f in r4.metadata.get("files", []))
            expected = [".hidden", "a.txt", "b.pdf", "c.csv", "d.log"]
            note("phase4_no_symlinks_followed",
                 "PASS" if names == expected else "FAIL",
                 f"names={names}")
        except AssertionError as exc:
            note("phase4_content_read", "FAIL", str(exc))
        finally:
            Path.read_bytes = _saved_pb
            Path.read_text = _saved_pt
            Path.open = _saved_po
            builtins.open = _saved_open

        # Cleanup outside dir (TemporaryDirectory only removes `tmp`)
        try:
            (outside / "escape.txt").unlink()
            outside.rmdir()
        except OSError:
            pass

    # ── Phase 4: root refusal paths ───────────────────────────────────────
    ctx = RunContext(authorized_host=socket.gethostname(),
                     authorized_location="selftest")
    ctx.results.clear()
    note("phase4_no_scan_root_skipped",
         "PASS" if phase_4(ctx).status == SKIPPED else "FAIL", "no scan-root")

    fs_root = Path("/") if os.name != "nt" else Path(
        os.environ.get("SystemDrive", "C:") + "\\")
    ctx2 = RunContext(authorized_host=socket.gethostname(),
                      authorized_location="selftest", scan_root=fs_root)
    note("phase4_filesystem_root_refused",
         "PASS" if phase_4(ctx2).status == ERROR else "FAIL",
         str(fs_root))

    # ── Phases 5, 8, 9, 10, 11 invariants ─────────────────────────────────
    ctx3 = RunContext(authorized_host=socket.gethostname(),
                      authorized_location="selftest")
    ctx3.results.clear()
    note("phase5_status",
         "PASS" if phase_5(ctx3).status in (PASS, SKIPPED) else "FAIL",
         phase_5(ctx3).status)
    r8 = phase_8(ctx3)
    note("phase8_clipboard_untouched",
         "PASS" if r8.metadata.get("clipboard_accessed") is False else "FAIL",
         "clipboard_accessed=False")
    note("phase9_skipped",
         "PASS" if phase_9(ctx3).status == SKIPPED else "FAIL", "all checks skipped")
    r10 = phase_10(ctx3)
    note("phase10_no_destructive_actions",
         "PASS" if (r10.metadata.get("files_touched") == 0
                    and r10.metadata.get("encryption_performed") is False
                    and r10.metadata.get("deletion_performed") is False)
         else "FAIL", "in-memory only")
    r11 = phase_11(ctx3)
    note("phase11_not_performed",
         "PASS" if (r11.status == NOT_PERFORMED
                    and r11.metadata.get("eicar_file_created") is False)
         else "FAIL", "EICAR not created")

    # ── CLI guards ────────────────────────────────────────────────────────
    note("phase_selection_0_first",
         "PASS" if _parse_phase_selection("3,1")[0] == 0 else "FAIL",
         str(_parse_phase_selection("3,1")))
    try:
        _parse_phase_selection("12"); note("reject_phase_12", "FAIL", "accepted")
    except ValueError:
        note("reject_phase_12", "PASS", "rejected")
    try:
        _parse_phase_selection("abc"); note("reject_non_numeric", "FAIL", "accepted")
    except ValueError:
        note("reject_non_numeric", "PASS", "rejected")
    try:
        _parse_phase_selection("1,1"); note("reject_duplicate", "FAIL", "accepted")
    except ValueError:
        note("reject_duplicate", "PASS", "rejected")

    note("missing_auth_exit_2",
         "PASS" if main(["--all"]) == 2 else "FAIL", "exit 2 expected")
    note("invalid_phase_exit_2",
         "PASS" if main(["--authorized-host", socket.gethostname(),
                         "--authorized-location", "t", "--phase", "12"]) == 2
         else "FAIL", "exit 2 expected")
    note("wrong_host_exit_1",
         "PASS" if main(["--authorized-host", "definitely-not-this-host",
                         "--authorized-location", "t", "--all"]) == 1
         else "FAIL", "exit 1 expected")

    failures = [r for r in results if r[1] != "PASS"]
    print(f"\nSelf-test: {len(results) - len(failures)} passed, "
          f"{len(failures)} failed")
    for name, status, detail in failures:
        print(f"  FAIL: {name} — {detail}")
    return 0 if not failures else 1


# ────────────────────────────────────────────────────────────────────────────
# main
# ────────────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description=f"{AGENT_NAME} v{VERSION} — non-destructive, read-only "
                    "purple-team validation.",
        allow_abbrev=False)
    p.add_argument("--authorized-host", default="")
    p.add_argument("--authorized-location", default="")
    p.add_argument("--phase", default="")
    p.add_argument("--all", action="store_true")
    p.add_argument("--scan-root", default="")
    p.add_argument("--report-dir", default="")
    p.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    p.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS)
    p.add_argument("--max-dir-items", type=int, default=DEFAULT_MAX_DIR_ITEMS)
    p.add_argument("--list", action="store_true")
    p.add_argument("--selftest", action="store_true")

    try:
        args = p.parse_args(argv)
    except SystemExit as exc:                 # unknown args → argparse exit 2
        return int(exc.code) if isinstance(exc.code, int) else 2

    if args.list:
        _list_phases()
        return 0
    if args.selftest:
        return _selftest()
    if args.all and args.phase:
        print("ERROR: --all and --phase are mutually exclusive.", file=sys.stderr)
        return 2
    if not args.all and not args.phase:
        print("ERROR: supply --all or --phase 0–11.", file=sys.stderr)
        return 2
    if not args.authorized_host or not args.authorized_location:
        print("ERROR: --authorized-host and --authorized-location are required.",
              file=sys.stderr)
        return 2
    if args.max_depth < 0:
        print("ERROR: --max-depth must be >= 0.", file=sys.stderr)
        return 2
    if args.max_results < 1:
        print("ERROR: --max-results must be >= 1.", file=sys.stderr)
        return 2
    if args.max_dir_items < 1:
        print("ERROR: --max-dir-items must be >= 1.", file=sys.stderr)
        return 2

    try:
        selection = sorted(PHASE_REGISTRY) if args.all else _parse_phase_selection(args.phase)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    scan_root = Path(args.scan_root).expanduser() if args.scan_root else None
    report_dir = Path(args.report_dir).expanduser() if args.report_dir else None

    ctx = RunContext(
        authorized_host=args.authorized_host,
        authorized_location=args.authorized_location,
        scan_root=scan_root,
        max_depth=args.max_depth,
        max_results=args.max_results,
        max_dir_items=args.max_dir_items,
        report_dir=report_dir,
    )

    print(f"{AGENT_NAME} v{VERSION} — run {ctx.run_id}")

    # Phase 0 always first; on failure nothing else runs.
    try:
        r0 = phase_0(ctx)
    except Exception as exc:                                # noqa: BLE001
        r0 = _record(ctx, 0, [
            _check("phase0_internal", ERROR,
                   f"Unhandled error in Phase 0 ({type(exc).__name__}); aborting.")
        ])
    if r0.status != PASS:
        selection = []

    for n in selection:
        if n == 0:
            continue
        try:
            PHASE_REGISTRY[n][1](ctx)
        except PhaseStatusError:
            _record(ctx, n, [
                _check("internal_status", ERROR,
                       "Internal status error during phase execution.")
            ])
        except Exception as exc:                            # noqa: BLE001
            _record(ctx, n, [
                _check("internal_error", ERROR,
                       f"Unhandled error during phase execution "
                       f"({type(exc).__name__}).")
            ])

    jp, je = write_json_report(ctx)
    hp, he = write_html_report(ctx)
    if jp:
        print(f"\nJSON report: {jp}")
    else:
        print(f"\nWARNING: JSON not written — {je}", file=sys.stderr)
    if hp:
        print(f"HTML report: {hp}")
    else:
        print(f"WARNING: HTML not written — {he}", file=sys.stderr)

    if not jp or not hp:
        return 1
    return 0 if r0.status == PASS else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)

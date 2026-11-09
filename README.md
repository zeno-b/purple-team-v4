
# Purple Team Validation Agent

**Versie:** 6.0  
**Platform:** Python 3.10+  
**Type:** Gecontroleerde, niet-destructieve securityvalidatie  
**Uitgangspunt:** Read-only, tenzij expliciet anders toegestaan voor synthetische tests

---

## 1. Overzicht

De Purple Team Validation Agent is ontwikkeld voor gecontroleerde validatie van endpointbeveiliging en beveiligingsmaatregelen binnen een expliciet goedgekeurde omgeving.

De agent ondersteunt securityteams bij het controleren van systeeminformatie, beperkte metadata, beveiligingsconfiguraties en synthetische testscenario's.

De nieuwe versie is bewust beperkt tot niet-destructieve controles.

### Veiligheidsprincipes

| Principe | Beschrijving |
|---|---|
| Autorisatie | Uitvoering uitsluitend op een expliciet goedgekeurde host |
| Locatie | De goedgekeurde uitvoeringslocatie wordt geregistreerd |
| Read-only | Systeemcontroles wijzigen geen bestaande configuraties |
| Geen dataverzameling | Geen extractie, dumping of staging van echte gegevens |
| Geen credential harvesting | Geen wachtwoorden, tokens of credentials uitlezen |
| Geen laterale beweging | Geen automatische toegang tot andere hosts |
| Expliciete toestemming | Een andere host vereist afzonderlijke goedkeuring |
| Synthetische data | Impact- en collectietests gebruiken uitsluitend testgegevens |
| Geen persistentie | Geen aanmaak of wijziging van persistentieobjecten |
| Geen ransomware | Geen encryptie, bestandswijziging of verwijdering |
| EICAR | Alleen een afzonderlijk geautoriseerde antivirustest |

---

## 2. Autorisatie en scope

Voor uitvoering zijn twee verplichte parameters vereist:

| Parameter | Beschrijving |
|---|---|
| `--authorized-host` | De expliciet goedgekeurde hostnaam |
| `--authorized-location` | De door de operator opgegeven uitvoeringslocatie |

De agent vergelijkt de opgegeven hostnaam met de lokale hostnaam.

De locatie wordt als operatorverklaring geregistreerd en wordt niet onafhankelijk via GPS of geolocatie geverifieerd.

### Scopebeperkingen

| Onderdeel | Toegestaan |
|---|---|
| Lokale hostvalidatie | Ja |
| Lokale systeeminformatie | Ja |
| Metadata-inspectie binnen goedgekeurde map | Ja |
| Externe host discovery | Nee |
| Remote command execution | Nee |
| Remote shares | Nee |
| Laterale beweging | Nee |
| Automatische host-pivoting | Nee |
| Toegang tot andere hosts | Alleen na afzonderlijke autorisatie en in een toekomstige goedgekeurde implementatie |

Het ontdekken van een andere host betekent nooit automatisch dat toegang tot die host is toegestaan.

---

## 3. Overzicht van de 12 fasen

| Fase | Naam | Doel | Beperking |
|---|---|---|---|
| 0 | Host- en scopevalidatie | Controleren van host en uitvoeringslocatie | Verplichte autorisatie |
| 1 | Systeemprofilering | Basisinformatie over het besturingssysteem | Read-only |
| 2 | Account- en domeinvalidatie | Controleren van domeinomgevingsmetadata | Read-only |
| 3 | Proces- en servicevalidatie | Proces- en servicecontroles | Niet geïmplementeerd |
| 4 | Bestandsmetadatavalidatie | Namen en metadata controleren | Geen inhoud uitlezen |
| 5 | Credential-store-controle | Aanwezigheid van bekende opslaglocaties controleren | Geen extractie |
| 6 | Securityconfiguratievalidatie | Beveiligingsconfiguraties controleren | Niet geïmplementeerd |
| 7 | Netwerkscopevalidatie | Bevestigen van de lokale scope | Geen netwerkverkenning |
| 8 | Synthetische collectievalidering | Testen met synthetische gegevens | Geen echte dataverzameling |
| 9 | Persistentieconfiguratievalidatie | Bestaande persistentie controleren | Niet geïmplementeerd |
| 10 | Synthetische impactvalidatie | Impactscenario met testgegevens voorbereiden | Geen echte bestanden wijzigen |
| 11 | Antivirusdetectievalidatie | Antivirusdetectie documenteren | Geen automatische EICAR-aanmaak |

---

## 4. Fasebeschrijvingen

### Fase 0 — Host- en scopevalidatie

**Doel:** Bevestigen dat de agent op de goedgekeurde host wordt uitgevoerd.

| Controle | Beschrijving |
|---|---|
| Hostnaam | Vergelijking met de goedgekeurde hostnaam |
| Locatie | Registratie van de opgegeven uitvoeringslocatie |
| Autorisatie | Verplichte parameters controleren |
| Remote toegang | Niet toegestaan |
| Privilege escalation | Niet uitgevoerd |

**Verwacht resultaat:** De uitvoering wordt alleen voortgezet wanneer de hostnaam overeenkomt.

### Fase 1 — Systeemprofilering

**Doel:** Basisinformatie over het lokale systeem verzamelen.

| Controle | Beschrijving |
|---|---|
| Operating system | Besturingssysteem |
| OS release | Versie van het besturingssysteem |
| Architecture | Systeemarchitectuur |
| Python runtime | Python-versie |
| Systeeminventaris | Niet uitgevoerd |
| Configuratiewijzigingen | Niet toegestaan |

**Beperking:** Alleen basisinformatie wordt geregistreerd. Er worden geen gevoelige configuraties geëxporteerd.

### Fase 2 — Account- en domeinvalidatie

**Doel:** Basisinformatie over de domeinomgeving controleren.

| Controle | Beschrijving |
|---|---|
| Domeinomgevingsvariabelen | Aanwezigheid controleren |
| Domeinnaam | Registreren indien beschikbaar |
| Accountinventaris | Niet uitgevoerd |
| Wachtwoorden | Niet uitlezen |
| Credentials | Niet verzamelen |
| Accountwijzigingen | Niet toegestaan |
| Groepswijzigingen | Niet toegestaan |

**Beperking:** De huidige implementatie voert geen volledige Active Directory-enumeratie uit.

### Fase 3 — Proces- en servicevalidatie

**Doel:** Proces- en servicevalidatie binnen de endpointomgeving.

| Controle | Status |
|---|---|
| Procesinventaris | Niet geïmplementeerd |
| Service-inventaris | Niet geïmplementeerd |
| Procesgeheugen uitlezen | Niet toegestaan |
| Proceswijzigingen | Niet toegestaan |
| Servicewijzigingen | Niet toegestaan |

**Resultaat:** De fase wordt als `SKIPPED` gerapporteerd.

### Fase 4 — Bestandsmetadatavalidatie

**Doel:** Beperkte zichtbaarheid verkrijgen in bestandsnamen en metadata binnen een expliciet goedgekeurde map.

| Controle | Beschrijving |
|---|---|
| Bestandsnaam | Toegestaan |
| Bestandsextensie | Toegestaan |
| Bestandsgrootte | Toegestaan |
| Laatste wijzigingsdatum | Toegestaan |
| Bestandsinhoud | Niet toegestaan |
| Documentinhoud | Niet toegestaan |
| Secrets uitlezen | Niet toegestaan |
| Bestanden kopiëren | Niet toegestaan |
| Bestanden verzamelen | Niet toegestaan |
| Staging | Niet toegestaan |

**Technische beperkingen:**

| Parameter | Waarde |
|---|---|
| Maximale traversaldiepte | 3 niveaus |
| Maximaal aantal resultaten | 100 |
| Symlinks volgen | Nee |
| Scanroot | Expliciet opgeven |
| Bestandstoegang | Alleen metadata |

De scanroot moet vooraf door de systeemeigenaar zijn goedgekeurd.

### Fase 5 — Credential-store-controle

**Doel:** Alleen controleren of bekende credential-store-locaties aanwezig zijn.

| Controle | Beschrijving |
|---|---|
| Bekende opslaglocaties | Aanwezigheidscontrole |
| Browsercredentialdatabases | Geen inhoud uitlezen |
| Wachtwoorden | Geen toegang |
| Tokens | Geen toegang |
| LSASS-geheugen | Geen toegang |
| Memory dumps | Niet toegestaan |
| Credential-extractie | Niet toegestaan |

**Resultaat:** Alleen de aanwezigheid van vooraf bekende paden wordt geregistreerd.

### Fase 6 — Securityconfiguratievalidatie

**Doel:** Beveiligingsconfiguraties controleren via goedgekeurde read-only interfaces.

| Controle | Status |
|---|---|
| Security policies | Niet geïmplementeerd |
| Configuratie-export | Niet uitgevoerd |
| Configuratiewijzigingen | Niet toegestaan |
| Defender-configuratie | Niet geïmplementeerd |
| Firewallwijzigingen | Niet toegestaan |

**Resultaat:** De fase wordt als `SKIPPED` gerapporteerd.

### Fase 7 — Netwerkscopevalidatie

**Doel:** Bevestigen dat de agent binnen de lokale uitvoeringsscope blijft.

| Controle | Beschrijving |
|---|---|
| Lokale scope | Bevestigen |
| Netwerkscanning | Niet uitgevoerd |
| Port scanning | Niet uitgevoerd |
| DNS-verkenning | Niet uitgevoerd |
| Remote shares | Niet toegestaan |
| Remote commands | Niet toegestaan |
| Laterale beweging | Niet toegestaan |
| Automatische host-pivoting | Niet toegestaan |

**Expliciete toestemming:**

Een gevonden host, domeinrelatie of netwerkresource geeft geen toestemming om deze te benaderen.

Een eventuele toekomstige uitbreiding naar andere hosts vereist afzonderlijke expliciete autorisatie, inclusief hostidentificatie en toegestane testactiviteiten.

### Fase 8 — Synthetische collectievalidering

**Doel:** Een gecontroleerd collectiescenario voorbereiden met uitsluitend synthetische gegevens.

| Controle | Beschrijving |
|---|---|
| Synthetische testdata | Toegestaan |
| Echte bestanden | Niet verzamelen |
| E-mailarchieven | Geen toegang |
| Downloads | Niet verzamelen |
| Clipboard uitlezen | Niet toegestaan |
| Clipboard wijzigen | Niet automatisch toegestaan |
| Stagingdirectory | Niet toegestaan |
| Businessgegevens | Niet gebruiken |

**Testmarker:**

`PURPLE_TEAM_TEST_DATA`

De synthetische gegevens blijven uitsluitend in het geheugen.

Er worden geen bestaande clipboardgegevens gelezen of overschreven.

### Fase 9 — Persistentieconfiguratievalidatie

**Doel:** Bestaande persistentieconfiguraties kunnen controleren zonder wijzigingen uit te voeren.

| Onderdeel | Beschrijving |
|---|---|
| Registry Run Keys | Niet geïmplementeerd |
| Scheduled Tasks | Niet geïmplementeerd |
| Services | Niet geïmplementeerd |
| Startup folders | Niet geïmplementeerd |
| WMI subscriptions | Niet geïmplementeerd |
| Nieuwe persistentie | Niet toegestaan |
| Bestaande persistentie wijzigen | Niet toegestaan |

**Resultaat:** De fase wordt als `SKIPPED` gerapporteerd.

### Fase 10 — Synthetische impactvalidatie

**Doel:** Een impactscenario voorbereiden met uitsluitend synthetische testgegevens.

| Testgegevens | Beschrijving |
|---|---|
| Finance | Synthetisch financieel testrecord |
| HR | Synthetisch HR-testrecord |
| Operations | Synthetisch operationeel testrecord |

**Beperkingen:**

| Activiteit | Toegestaan |
|---|---|
| Synthetische gegevens in geheugen | Ja |
| Echte documenten uitlezen | Nee |
| Bestanden encrypten | Nee |
| Bestanden hernoemen | Nee |
| Ransom notes aanmaken | Nee |
| Bestanden verwijderen | Nee |
| Productiedata wijzigen | Nee |
| Decryptie uitvoeren | Nee |

De fase valideert uitsluitend het synthetische testscenario en voert geen daadwerkelijke ransomware- of recoverytest uit.

### Fase 11 — Antivirusdetectievalidatie

**Doel:** De antivirusvalidatieprocedure documenteren.

EICAR is een gestandaardiseerde antivirustestsignatuur. Het is geen functionerend virus, ransomware of uitvoerbare malwarepayload.

| Onderdeel | Beschrijving |
|---|---|
| EICAR-bestand automatisch aanmaken | Niet toegestaan |
| Antivirusinstellingen wijzigen | Niet toegestaan |
| Antivirus uitschakelen | Niet toegestaan |
| Quarantaine wijzigen | Niet toegestaan |
| Antivirusdetectie claimen | Niet toegestaan zonder testresultaat |
| Afzonderlijk geautoriseerde EICAR-test | Mogelijk volgens goedgekeurde procedure |

**Belangrijk:** Antivirusproducten kunnen een EICAR-testbestand detecteren, blokkeren of in quarantaine plaatsen. EICAR is daarom niet volledig zonder operationele impact.

De huidige implementatie maakt geen EICAR-bestand aan en rapporteert `NOT_PERFORMED`.

---

## 5. Logging en rapportage

De agent genereert twee rapporten.

| Bestand | Doel |
|---|---|
| JSON | Machineleesbaar overzicht |
| HTML | Visueel rapport voor analyse |

Standaard uitvoermap:

`./purple_team_reports/`

### Rapportinhoud

| Veld | Beschrijving |
|---|---|
| Agentversie | Versie van de agent |
| Timestamp | Tijdstip van uitvoering |
| Phase ID | Fasenummer |
| Phase name | Fasebeschrijving |
| Status | Resultaat van de controle |
| Message | Korte toelichting |
| Metadata | Beperkte niet-gevoelige informatie |

Rapporten moeten worden behandeld volgens het informatieclassificatiebeleid van de organisatie.

Een gegenereerd rapport bewijst niet automatisch dat een beveiligingsproduct een detectie of alert heeft gegenereerd.

---

## 6. Installatie

### Vereisten

| Component | Vereiste |
|---|---|
| Python | 3.10 of hoger |
| Dependencies | Python standard library |
| Externe packages | Niet vereist |
| Platform | Python-compatibele omgeving |

### Repository ophalen

```bash
git clone https://github.com/zeno-b/purple-team-v4.git
cd purple-team-v4
```

---

## 7. Uitvoering

### Alle fasen uitvoeren

```bash
python agent.py \
  --all \
  --authorized-host HOSTNAME \
  --authorized-location APPROVED_LOCATION
```

### Geselecteerde fasen uitvoeren

```bash
python agent.py \
  --phase 0,1,2,4,7,8,10,11 \
  --authorized-host HOSTNAME \
  --authorized-location APPROVED_LOCATION
```

### Metadata-inspectie uitvoeren

```bash
python agent.py \
  --phase 0,4 \
  --authorized-host HOSTNAME \
  --authorized-location APPROVED_LOCATION \
  --metadata-root "C:\Approved\TestDirectory"
```

### Alternatieve rapportmap

```bash
python agent.py \
  --all \
  --authorized-host HOSTNAME \
  --authorized-location APPROVED_LOCATION \
  --output "./reports"
```

Vervang `HOSTNAME` en `APPROVED_LOCATION` door de daadwerkelijk goedgekeurde waarden.

De metadata-scanroot moet afzonderlijk zijn goedgekeurd.

---

## 8. Statuscodes

| Status | Betekenis |
|---|---|
| PASS | De geïmplementeerde controle is uitgevoerd |
| SKIPPED | De fase is niet geïmplementeerd of niet van toepassing |
| ERROR | Er is een uitvoeringsfout opgetreden |
| NOT_PERFORMED | De test is gedocumenteerd maar niet uitgevoerd |

Een `PASS` betekent niet dat het systeem volledig veilig is.

Het betekent uitsluitend dat de betreffende controle succesvol is uitgevoerd.

---

## 9. Veiligheidsgrenzen

De huidige Python-implementatie bevat geen functionaliteit voor:

| Functionaliteit | Status |
|---|---|
| Shell-command execution | Niet aanwezig |
| PowerShell-command execution | Niet aanwezig |
| Netwerkcommunicatie | Niet aanwezig |
| Remote-host pivoting | Niet aanwezig |
| Credential harvesting | Niet aanwezig |
| Memory dumping | Niet aanwezig |
| Echte dataverzameling | Niet aanwezig |
| Bestandsextractie | Niet aanwezig |
| Clipboardtoegang | Niet aanwezig |
| Persistentie aanmaken | Niet aanwezig |
| Ransomware-encryptie | Niet aanwezig |
| Bestandsverwijdering | Niet aanwezig |
| Automatische EICAR-aanmaak | Niet aanwezig |

Fase 4 leest uitsluitend metadata binnen de opgegeven scanroot en de vastgelegde grenzen.

Het genereren van rapporten schrijft JSON- en HTML-bestanden naar de opgegeven uitvoermap.

Deze veiligheidsverklaringen gelden uitsluitend voor de Python 6.0-implementatie.

---

## 10. Implementatiestatus

| Bestand | Status | Opmerking |
|---|---|---|
| `agent.py` | Referentie-implementatie | Python 6.0 |
| `agent.ps1` | Legacy | Moet afzonderlijk worden aangepast |
| `agent.sh` | Legacy | Moet afzonderlijk worden aangepast |
| `README.md` | Nieuwe documentatie | Beschrijft Python 6.0 |

De PowerShell- en Bash-implementaties mogen niet als conform aan dit veiligheidsmodel worden beschouwd voordat ze afzonderlijk zijn herschreven en getest.

---

## 11. Beperkingen

De huidige versie biedt bewust geen:

- Volledige Active Directory-enumeratie.
- Proces- en service-inventaris.
- Export van security policies.
- Persistentie-inventaris.
- Netwerkverkenning.
- Actieve adversary emulation.
- Endpoint detection rule execution.
- Daadwerkelijke ransomware-simulatie.
- Geautomatiseerde antivirustest.

Deze beperkingen zijn bewust ingevoerd om de operationele impact te beperken.

De prioriteit ligt bij gecontroleerde validatie, gegevensminimalisatie en veiligheid.

---

## 12. Verantwoord gebruik

Gebruik deze agent uitsluitend op systemen waarvoor expliciete toestemming is verkregen.

Breid de uitvoeringsscope niet uit zonder aanvullende goedkeuring.

De aanwezigheid van een host, account, bestand of netwerkresource betekent niet dat toegang daartoe is toegestaan.

Iedere toekomstige uitbreiding moet het niet-destructieve veiligheidsmodel behouden.

**Kernprincipe: iedere veiligheidsbeperking die in deze README wordt beschreven, moet technisch door de implementatie worden afgedwongen.**

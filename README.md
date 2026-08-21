# Auto Finn-Søk

Automatisk bilsøker for Finn.no. Følger med på merker/modeller du velger selv,
samler alle annonser i et Google Sheet med statistikk og grafer, vurderer om
hver bil er et godt eller dårlig kjøp sammenlignet med lignende biler,
arkiverer annonser som forsvinner (antatt solgt), og sender deg e-post når
noe ser ut som et godt kjøp. Kjører gratis i skyen via GitHub Actions --
PC-en din trenger aldri å være på.

## Viktig om Finn.no sine vilkår

Finn.no sin `robots.txt` sier eksplisitt at automatisert/systematisk henting
av data krever skriftlig samtykke fra dem. Dette prosjektet er et bevisst
avvik fra det, til personlig bruk i lavt volum -- ikke videresalg eller
publisering av dataene. For å holde belastningen lav og skånsom:

- Skanning skjer sjelden (standard én gang i døgnet, du kan justere selv -- se under).
- Hver kjøring gjør få kall (kun søkesider + detaljside for *nye* annonser),
  med tilfeldige pauser mellom hvert kall.
- Ved tegn på blokkering (403/429) gir kjøringen opp med det samme i stedet
  for å presse på.

Du bør selv vurdere om dette er greit for ditt bruk. Vurder å redusere
frekvens/antall merker ytterligere hvis du ser gjentatte "Blokkert"-meldinger
i Kjørelogg-fanen.

## Étt-gangs oppsett

1. **Google Cloud-prosjekt**: opprett et på https://console.cloud.google.com,
   skru på **Google Sheets API** og **Google Drive API**.
2. **Service-account**: opprett en service-account i prosjektet, generer en
   JSON-nøkkel og last den ned (IKKE commit denne filen noe sted).
3. **Google Sheet**: opprett et nytt regneark. Del det med
   service-account-ens e-postadresse (finnes i JSON-nøkkelen, feltet
   `client_email`) som **Redigerer**. Kopier ark-ID-en fra URL-en
   (`https://docs.google.com/spreadsheets/d/<HER>/edit`).
4. **Gmail app-passord**: skru på 2-trinnsverifisering på Gmail-kontoen din,
   og opprett et app-passord for e-postvarsling
   (https://myaccount.google.com/apppasswords).
5. **GitHub-repo**: opprett et offentlig repo og push denne koden dit.
   (Offentlig repo gir ubegrenset gratis kjøretid for GitHub Actions --
   ingen av hemmelighetene under havner i koden, kun i krypterte secrets.)
6. **GitHub-secrets** (Settings -> Secrets and variables -> Actions):
   - `GOOGLE_SERVICE_ACCOUNT_JSON` -- hele innholdet i JSON-nøkkelfilen fra steg 2
   - `SHEET_ID` -- ark-ID-en fra steg 3
   - `SMTP_USER` -- din Gmail-adresse
   - `SMTP_APP_PASSWORD` -- app-passordet fra steg 4
   - `ALERT_EMAIL_TO` -- e-postadressen som skal motta varsler
7. **Kjør workflowen manuelt én gang**: gå til Actions-fanen i GitHub-repoet
   -> "Periodisk skann av Finn.no" -> "Run workflow". Dette oppretter alle
   fanene i arket automatisk (Merker, Aktive Annonser, Historikk, Statistikk,
   Kjørelogg, Innstillinger) hvis de ikke finnes fra før.
8. **Fyll ut Merker-fanen**: legg inn minst én rad med Merke + Modell og
   kryss av Aktiv=TRUE. Kjør workflowen manuelt igjen for å bekrefte at den
   plukker opp innstillingen.
9. **Lag graf-objektene i Statistikk-fanen**: dataene skrives automatisk til
   faste tabeller der (Prisutvikling per uke, Pris vs. kilometerstand, Nye/
   fjernet per uke, Fordeling av vurdering) -- sett opp et diagram i Sheets
   manuelt én gang som peker på hver tabell, så oppdateres grafen automatisk
   etter hvert som tabellen fylles på nytt hver kjøring.

Etter dette går alt av seg selv på cronen.

## Endre hvor ofte det skannes

Rediger `cron`-linjen i [.github/workflows/periodic_scan.yml](.github/workflows/periodic_scan.yml):

```yaml
- cron: "0 6 * * *"     # én gang i døgnet, kl 06 UTC (standard)
- cron: "0 6,18 * * *"  # to ganger i døgnet
- cron: "0 */6 * * *"   # hver 6. time
- cron: "0 * * * *"     # hver time (høyere risiko for blokkering)
```

Tidene er i UTC. Commit endringen -- GitHub Actions plukker den opp automatisk.

## Sjekk én annonse raskt

Gå til Actions-fanen -> "Sjekk én annonse" -> "Run workflow", lim inn en
Finn-URL. Du får svar på e-post (og en rad i "Sjekk enkeltannonse"-fanen) med
en gang jobben er ferdig -- fungerer fint fra telefonen via GitHub sin app
eller mobilnettleser.

## Justere terskler uten kodeendring

Innstillinger-fanen i arket lar deg justere:

- `GodtKjopTerskel` -- score (0-100) som utløser e-postvarsel (standard 75)
- `MinKohort` -- minimum sammenligningsbiler før noen vurdering gis (standard 5)
- `RegresjonKohort` -- minimum sammenligningsbiler før regresjon brukes i
  stedet for enkel persentilrangering (standard 15)
- `LookbackDager` -- hvor mange dager bakover som telles med i
  sammenligningsgrunnlaget (standard 90)

## Lokal testing før du setter opp cronen

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Test søk + parsing uten å skrive noe til Google Sheets:
python scripts/local_dry_run.py --brand Toyota --model Corolla

# Kjør enhetstester (ingen nettverkskall, bruker lagrede eksempelsider):
python -m pytest tests/ -v

# Når du har satt opp .env (se .env.example) kan du teste ekte skriving:
python scripts/local_dry_run.py --brand Toyota --model Corolla --write
```

## Hvordan "godt kjøp" beregnes

Se docstringen øverst i [src/scoring.py](src/scoring.py) -- kort fortalt:
prisen sammenlignes med andre annonser av samme merke+modell. Med for få
sammenligningsbiler gis ingen vurdering. Med noen flere rangeres prisen som
persentil i gruppen. Med mange nok brukes en enkel modell som justerer for
år og kilometerstand. Modellen blir automatisk mer presis etter hvert som
data samles opp over uker.

## Arkets faner

| Fane | Innhold |
|---|---|
| Merker | Du redigerer: hvilke merker/modeller som følges, med filtre |
| Aktive Annonser | Script skriver: alle annonser som er live nå, med vurdering |
| Historikk | Script skriver: annonser som har forsvunnet (antatt solgt) |
| Statistikk | Script skriver: tabeller grafene dine peker på |
| Kjørelogg | Script skriver: én rad per kjøring, for feilsøking |
| Innstillinger | Du redigerer: terskler for vurdering og varsling |
| Sjekk enkeltannonse | Script skriver: resultat fra manuelle enkelt-sjekk |

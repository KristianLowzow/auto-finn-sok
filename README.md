# Auto Finn-Søk

Automatisk bilsøker for Finn.no. Følger med på merker/modeller du velger selv,
samler alle annonser i et Google Sheet med statistikk og grafer, vurderer om
hver bil er et godt eller dårlig kjøp sammenlignet med lignende biler,
arkiverer annonser som forsvinner (antatt solgt), og sender deg én samlet
e-postrapport når noen annonser skiller seg **tydelig** positivt ut på pris,
kilometerstand og (for elbiler) rekkevidde. Kjører gratis i skyen via GitHub
Actions -- PC-en din trenger aldri å være på.

## Viktig om Finn.no sine vilkår

Finn.no sin `robots.txt` sier eksplisitt at automatisert/systematisk henting
av data krever skriftlig samtykke fra dem. Dette prosjektet er et bevisst
avvik fra det, til personlig bruk i lavt volum -- ikke videresalg eller
publisering av dataene. For å holde belastningen lav og skånsom:

- Skanning skjer sjelden (standard én gang i døgnet, du kan justere selv -- se under).
- Hver kjøring henter kun søkesider + detaljside for *nye* annonser (aldri på
  nytt for annonser som allerede er kjent), med tilfeldige pauser mellom
  hvert kall.
- Ved tegn på blokkering (403/429) gir kjøringen opp med det samme i stedet
  for å presse på.

Du bør selv vurdere om dette er greit for ditt bruk. Vurder å redusere
frekvens/antall merker ytterligere hvis du ser gjentatte "Blokkert"-meldinger
i Kjørelogg-fanen.

**Merk:** det finnes ikke lenger noe tak på hvor mange nye annonser som
hentes i én kjøring -- alt innenfor filteret i Merker-fanen hentes samme
kjøring, uansett hvor mange det er. I praksis betyr det at en kjøring rett
etter at Aktive Annonser er tømt (eller etter en lang periode uten skanning)
kan ta betydelig lengre tid -- potensielt over en time -- og gjøre langt
flere kall til Finn.no enn en vanlig "vedlikeholds"-kjøring der de fleste
annonsene allerede er kjent. Hvis du følger flere merker/modeller med veldig
mange treff hver, bør du selv vurdere om dette fortsatt er innenfor det du
er komfortabel med.

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
9. **Statistikk-fanen**: dataene skrives automatisk til faste tabeller der.
   Følgende scatter-diagram (pris mot kilometerstand) opprettes og
   oppdateres helt automatisk hver kjøring -- ingenting å sette opp manuelt:
   - **Ett per bilmerke**, fargekodet på **batteristørrelse**.
   - **To samlede diagram på tvers av alle merker/modeller**: ett for 4x4 og
     ett for 2-hjulsdrift, fargekodet på **merke** -- slik kan du sammenligne
     f.eks. Škoda Enyaq mot VW ID.4 innenfor samme hjuldrift-type.
     Batterikapasitet (kWh) vises som egen kolonne i tabellen bak diagrammet,
     men er ikke en del av selve plottet (Google Sheets sin bobbel-diagramtype
     avviste konsekvent gyldige forespørsler under utvikling, så vi bruker et
     vanlig, pålitelig scatter-diagram i stedet).

   I tillegg finnes tabellen **"Škoda Enyaq vs. VW ID.4 (per hjuldrift)"**
   med snittpris/-km/-kr-per-gjenværende-km brutt ned på hjuldrift, som et
   direkte tallsvar på "hva får jeg for pengene" for de to modellene.

   For de andre tabellene (Prisutvikling per uke/årsmodell, Nye/fjernet per
   uke, Fordeling av vurdering) må du sette opp ett diagram i Sheets manuelt
   én gang per tabell; grafen oppdateres automatisk etter hvert som tabellen
   fylles på nytt hver kjøring. Depresieringskurve: X=Årsmodell, Y=Snittpris,
   én serie per Merke+Modell.

   I tillegg fargelegges radene i **Aktive Annonser** automatisk hver kjøring:
   grønt = Godt kjøp, gult = Gjennomsnittlig, rødt = Dyrt, og gull/fet skrift
   for annonser markert **Fremragende** (se under).

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

## Hvordan varsling fungerer ("Fremragende kjøp")

Du får **ikke** e-post for hver "Godt kjøp" -- det ville fort blitt for mange.
E-post sendes bare for annonser som er markert **Fremragende**, altså biler
som har lavest kr per gjenværende km (se under) for merke+modellen sin, over
`GodtKjopTerskel`-persentilen, OG -- for elbiler -- også har lengst
rekkevidde. En bensinbil trenger bare slå ut på kr/gjenværende km;
rekkevidde er ikke relevant der.

Alle Fremragende-treff i én kjøring samles i **én** e-postrapport (ikke én
e-post per bil), med pris/km/rekkevidde-persentilene så du ser hvorfor bilen
ble plukket ut.

## Merke-regresjon ("Regresjonsavvik %")

I tillegg til Deal Label (som sammenligner mot samme MODELL) regnes det ut en
egen **regresjonslinje per bilMERKE**: pris forklares med årsmodell,
kilometerstand OG rekkevidde samtidig, på tvers av alle modellene til merket
(f.eks. slås "ID.4" og "ID.4 GTX" sammen -- fordi rekkevidde er med som
forklaringsvariabel, forklares GTX-ens høyere pris av at den har mer
rekkevidde/kraft, ikke bare av at det er "en annen modell"). Bare elbiler med
rekkevidde over `MinRekkevidde` (standard 400 km) regnes med, slik at korte
og lange rekkevidder ikke sammenlignes rått mot hverandre.

Kolonnen **"Regresjonsavvik %"** i Aktive Annonser viser hvor mange prosent
annonsens pris ligger under (negativt) eller over (positivt) denne
merke-linja. Langt under linja = godt kjøp. Celler under -15 % fargelegges
grønt, over +15 % rødt. Denne vurderingen er uavhengig av og påvirker
foreløpig ikke Deal Label/Fremragende/e-postvarsling -- si fra hvis du vil at
den skal styre varslingen i stedet.

**Maks pris (varsel)** i Merker-fanen er en egen prisgrense *kun* for om noe
er verdt et varsel -- den påvirker ikke hva som hentes/vises i statistikken.
Alt innenfor merke+modell hentes og telles med i Aktive Annonser og
Statistikk uansett pris, slik at dyre biler også bidrar til
sammenligningsgrunnlaget. Stå tom for en rad betyr at
`StandardMaksPrisVarsel` (se under) brukes i stedet.

## Justere terskler uten kodeendring

Innstillinger-fanen i arket lar deg justere:

- `GodtKjopTerskel` -- persentil (0-100) kr/gjenværende km (og for elbiler
  rekkevidde) må slå for å telle som Fremragende og utløse e-postvarsel
  (standard 75)
- `MinKohort` -- minimum sammenligningsbiler før noen vurdering gis (standard 5)
- `LookbackDager` -- hvor mange dager bakover som telles med i
  sammenligningsgrunnlaget (standard 90)
- `StandardMaksPrisVarsel` -- brukes når en Merker-rad ikke har egen "Maks
  pris (varsel)" (standard 230 000)
- `MinRekkevidde` -- kun elbiler med rekkevidde (WLTP) over dette telles med
  i merke-regresjonen (standard 400 km)

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

## Hvordan "godt kjøp" (Deal Label) beregnes

Se docstringen øverst i [src/scoring.py](src/scoring.py) -- kort fortalt:
i stedet for å bare se på rå pris regnes bilens antatte **gjenværende
levetid i kilometer** ut først. Bilen regnes som "ferdig" ved det som
inntreffer først av:

- **18 år** gammel, eller
- **260 000 km** totalt, gitt en antatt kjørelengde på **~14 000 km/år**
  fra i dag.

`Kr per gjenværende km` = pris delt på denne gjenværende kilometerstanden --
lavere er bedre, siden det belønner både lav pris OG mye kjørelengde igjen
(en bil med høy km-stand men også høy gjenværende-levetid kan fortsatt være
et godt kjøp). Denne verdien rangeres som persentil mot andre annonser av
samme merke+modell for å gi Deal Label (Godt kjøp/Gjennomsnittlig/Dyrt). Med
for få sammenligningsbiler gis ingen vurdering. Kolonnene
**"Gjenvaerende km"** og **"Kr per gjenvaerende km"** i Aktive Annonser viser
tallene bak vurderingen. Den strengere "Fremragende"-vurderingen som utløser
e-post er beskrevet over.

## Arkets faner

| Fane | Innhold |
|---|---|
| Merker | Du redigerer: hvilke merker/modeller som følges, årsfilter, km-filter og "Maks pris (varsel)" |
| Aktive Annonser | Script skriver: alle annonser som er live nå, med Deal Label, Fremragende, Regresjonsavvik % (fargelagt), hjuldrift, batterikapasitet, utstyrspakke og utstyrsflagg (varmepumpe, head-up display, ratt-/setevarme, trådløs mobillading) |
| Historikk | Script skriver: annonser som har forsvunnet (antatt solgt) |
| Statistikk | Script skriver: tabeller + auto-genererte pris/km-scatterdiagram (per merke, og samlet per hjuldrift) + Enyaq/ID.4-sammenligning |
| Kjørelogg | Script skriver: én rad per kjøring, for feilsøking |
| Innstillinger | Du redigerer: terskler for vurdering og varsling |
| Sjekk enkeltannonse | Script skriver: resultat fra manuelle enkelt-sjekk |

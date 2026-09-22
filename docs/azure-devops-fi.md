# Azure DevOps: stagingista hallittuun tuotantojulkaisuun

Tämä toteutus käyttää projektin **DevOpsYAMKOpenDemo / DevOpsDemo** Azure Repos
-repositoriota `cyberwatch-rs`. [Putken YAML](../azure-pipelines.yml) on versionoitu
koodin kanssa. Nykyinen Azure-VM säilyy tuotantokohteena. Staging tarvitsee oman
VM:n, tietolevyn, salaisuudet ja resurssiryhmän. Opintojakson tehtävänannot ja
palautukset ovat edelleen vain Moodlen kurssioppaassa.

## Käyttöönoton tila 22.9.2026

CI/CD-koodi on valmisteltu, mutta **Azure-julkaisut ovat aluksi poissa käytöstä**
(`enableDeployments: false`). Stagingin `storageAccount` on tarkoituksella `null`,
kunnes infrastruktuurin luonti palauttaa sen todellisen nimen. Julkaisuskripti
kieltäytyy käyttämästä keskeneräistä kohdetta.

Azure DevOpsiin tuodun repositorion oletushaara korjattiin Dependabot-haarasta
`main`-haaraksi. Tarkastuksessa projektissa ei ollut palveluyhteyksiä tai
deployment environment -ympäristöjä. Azure-tilin resurssioikeuksista puuttuu
`Microsoft.Authorization/roleAssignments/write`; pipeline-identiteettien roolit
on myönnettävä erikseen siihen oikeutetulla tilillä.

CI:n `verifyReleaseArtifact: true` mahdollistaa ARM64-kuvan rakentamisen ja
testaamisen työhaarasta ennen yhdistämistä. Se ei julkaise työhaaraa Azureen:
stagingin julkaisuehto edellyttää edelleen `main`-haaraa. Infrastruktuurin
ylläpidolle on [oma IaC-putki ja ohje](azure-iac-fi.md). Se käyttää erillisiä
identiteettejä, jotta sovelluksen julkaisu ei saa oikeutta muuttaa verkkoa tai
tallennustilin määrityksiä. Kaikkien neljän identiteetin nimet ja oikeusrajat ovat
[koneellisesti luettavassa käyttöönottosuunnitelmassa](../deploy/azure/access-plan.json).

Automaattinen hyväksyntätarkistus esti managed identityjen, federointien ja
palveluyhteyksien luomisen ennen erillistä, kohteet ja oikeuksien laajuuden
nimeävää hyväksyntää. Nykyiseen Azure-sovellukseen ei tehty CI/CD-muutosta.

## Haarat, tagit ja sama julkaisupaketti

1. Kehitä työhaarassa ja tee pull request `main`-haaraan. Azure Reposissa PR:n
   build validation kytketään haarakäytäntöön (*branch policy*); YAML:n `pr`
   ei määritä Azure Repos -PR-tarkistusta. [Microsoft: Azure Repos triggers](https://learn.microsoft.com/en-us/azure/devops/pipelines/repos/azure-repos-git?view=azure-devops).
2. CI ajaa Rust-, Python-, HTTP- ja määritystestit, Semgrepin sekä Trivyn.
   HIGH/CRITICAL-löydös pysäyttää Trivy-vaiheen. Porttia ei ohiteta julkaisua varten.
3. `main`-haaran onnistunut tarkistus rakentaa yhden Linux ARM64 -konttikuvan.
   Kuva testataan offline-aineistolla ja tiedostosta luettavalla harjoitustokenilla.
   Artefakti sisältää Docker-arkiston, sen SHA-256-tiivisteen, kuvan configuration
   digestin, lähdecommitin ja build-tunnisteen. Tämä on jäljitettävyysnäyttö,
   ei ulkopuolisen tahon allekirjoittama provenance-todistus.
4. Kun Azure-julkaisut on aktivoitu, `main` julkaistaan automaattisesti stagingiin.
   Palvelun pitää käynnistyä juuri odotetulla kuvalla ja läpäistä `/ready`-pohjainen
   konttitarkistus. Azure-julkaisu ei käytä CI:n synteettistä tietokantaa.
5. Luo tuotantotagi, esimerkiksi `v0.4.2`, vasta onnistuneesti stagingiin julkaistulle
   commitille. Tagiajo etsii **saman commitin** onnistuneen `main`-ajon ja tarkistaa,
   että sen `DeployStaging`-vaihe todella onnistui. Pelkkä onnistunut CI tai
   ohitettu staging-vaihe ei kelpaa. Haku kattaa 100 viimeisintä onnistunutta
   `main`-ajoa; vanhemman version julkaisu tarvitsee uuden staging-ajon.
6. Hyväksy tuotantojulkaisu DevOpsin environment-/service connection -tarkistuksessa.
   Putki lataa löydetyn buildin täsmällisen artefaktin. **Tuotannolle ei rakenneta
   uutta kuvaa.** Jos artefakti on vanhentunut ja poistettu, julkaisu epäonnistuu.
   Säilytä julkaisuun liittyvä onnistunut staging-build ja artefakti retention-asetuksilla.

Tagi yksilöi julkaisuaikeen. Tagin nimi tai YAML:n `condition` ei yksin ole
käyttöoikeussuoja. `main`-haaran katselmointi, tuotantotagien luontioikeudet,
palveluyhteyden käyttöoikeus ja YAML:n ulkopuolinen hyväksyntä muodostavat yhdessä
julkaisun hallinnan. [Microsoft: approvals and checks](https://learn.microsoft.com/en-us/azure/devops/pipelines/process/approvals?view=azure-devops).

## Azure-yhteys ja täsmällinen oikeusraja

Käytä kahta **user-assigned managed identityä** ja **workload identity federation**
-palveluyhteyttä. Entra-sovellusrekisteröintiä tai pitkäikäistä client secretia ei
tarvita. Federationin `issuer` ja `subject` otetaan juuri luodun DevOps-yhteyden
vastauksesta; niitä ei päätellä organisaation nimestä. [Microsoft: manual WIF setup](https://learn.microsoft.com/en-us/azure/devops/pipelines/release/configure-workload-identity?view=azure-devops).

Suunnitellut, vielä hyväksyntää odottavat kohteet tilauksessa
`afe8ae0d-d866-47a9-bc56-e1f4475e6cc6`:

| Kohde | Staging | Tuotanto |
| --- | --- | --- |
| Resurssiryhmä | `rg-cyberwatch-staging-swe` | nykyinen `rg-cyberwatch-yamk-swe` |
| VM | uusi `cyberwatch-staging` | nykyinen `cyberwatch-yamk` |
| Identity | `id-cyberwatch-ado-staging` | `id-cyberwatch-ado-prod` |
| Service connection | `cyberwatch-staging-wif` | `cyberwatch-prod-wif` |
| DevOps environment | `cyberwatch-staging` | `cyberwatch-production` |

Kummallekin identiteetille myönnetään vain oman ympäristön oikeudet:

- **Virtual Machine Contributor** täsmälleen kyseiseen VM-resurssiin. Run Command
  ajaa VM:llä ylläpitäjän komentoja: tämä on käytännössä pääsy myös sovelluksen
  paikallisiin salaisuuksiin ja tietokantaan. Siksi tuotannon palveluyhteys
  suojataan erikseen. CI-tarkistusjobit eivät saa tätä yhteyttä.
- **Storage Blob Data Contributor** kyseisen tallennustilin `artifacts`-konttiin.
- **Storage Blob Delegator** kyseiseen tallennustiliin lyhytaikaisen user delegation
  SAS -osoitteen muodostamiseen. Tallennustilin avaimia ei lueta tai anneta putkelle.
  [Microsoft: user delegation SAS](https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blob-user-delegation-sas-create-cli).

Palveluyhteyden Azure-tilaus on valintakonteksti. Se ei tarkoita tilauksen laajuista
Contributor-roolia: todellinen pääsy määräytyy yllä nimetyistä resurssikohtaisista
Azure RBAC -määrityksistä. Identiteetti ei tarvitse Owner-roolia eikä oikeutta
muokata roolimäärityksiä. LUCIT-tenantin mahdolliset rajoitteet tarkistetaan
erikseen. [Microsoft: Run Command](https://learn.microsoft.com/en-us/azure/virtual-machines/linux/run-command).

## Käyttöönottojärjestys

1. Hyväksy yllä nimetyt pilvi-identiteetit, federoinnit, palveluyhteydet ja erillinen
   staging-infrastruktuuri. Staging käyttää samaa ARM64 `Standard_B2pts_v2`
   -VM-kokoa kuin nykyinen esimerkki, omaa 4 GiB datalevyä, 32 GiB käyttöjärjestelmälevyä,
   yksityistä Blob-konttia ja julkista HTTPS-osoitetta. Nämä ovat laskutettavia
   resursseja. Stagingin pysäytyksestä ja käytön seurannasta sovitaan omistajan kanssa.
2. Luo staging alkuperäisellä `deploy/azure/main.bicep`-määrityksellä käyttäen
   erillisiä nimiä ja DNS-labelia `cyberwatch-staging-afe8ae-20260922`. Bootstrap
   tehdään kerran ylläpitäjän toimesta [olemassa olevan runbookin](azure-deployment.md)
   mukaan. Sovelluksen ja tietolevyn tulee olla toimintakunnossa ennen uutta
   application-only-julkaisua. Älä aja stagingin luontia tuotannon nimillä.
3. Tallenna palautunut tallennustilin nimi `deploy/azure/targets.json`-tiedostoon.
   Älä tuo tuotannon tietokantaa, admin-tokenia tai reader-salasanaa stagingiin.
4. Luo kaksi identityä ja DevOps-yhteysluonnosta. Lisää kummankin yhteyden oma
   federated credential kyseiseen identityyn. Azure-roolien myöntämiseen oikeutettu
   ylläpitäjä lisää kolme yllä kuvattua resurssikohtaista roolia.
   Federation hoitaa tunnistautumisen; se ei myönnä RBAC-oikeuksia. Resurssien
   luonnin jälkeen ylläpitäjä tarkastaa suunnitelman komennolla
   `python deploy/azure/grant_pipeline_roles.py` ja toteuttaa sen komennolla
   `python deploy/azure/grant_pipeline_roles.py --apply`. Skripti hakee molempien
   luotujen identityjen principal ID:t Azuresta ja tarkistaa resurssit ennen
   ensimmäistä roolimääritystä. Ilman `--apply`-valintaa se vain lukee ja tulostaa
   kuusi määritystä. Azure CLI:hin kirjautuneella tilillä on oltava oikeus
   `Microsoft.Authorization/roleAssignments/write` näissä kohteissa.
5. Luo DevOps-ympäristöt. Salli kummankin environmentin ja service connectionin
   käyttö vain Cyberwatchin nimetylle pipeline-määritykselle. **Grant access
   permission to all pipelines** jätetään pois. Tuotantoon lisätään opettajan
   hyväksyntä YAML:n ulkopuolella sekä ympäristöön että palveluyhteyteen.
   Ympäristöihin lisätään exclusive lock, jotta samanaikaiset julkaisut eivät kilpaile.
6. Suojaa `main`: vaadittu build validation ja katselmointi, ei yleistä policy bypass
   -oikeutta. Rajaa tuotantotagien luonti ja force push -oikeudet julkaisusta
   vastaaville. Varmista erikseen, kuka saa muuttaa approval/check-asetuksia.
7. Tarkista Azure Pipelines -agenttikapasiteetti. YAML käyttää `ubuntu-24.04`
   -agenttia. AMD64-agentti kääntää ARM64-sovelluksen omalla suorittimellaan
   (*cross-compilation*): Rustin ARM64-kohde ja Debian Bookwormin ARM64 C-kääntäjä
   tuottavat saman Debian-version ajonaikaiseen ympäristöön sopivan binäärin.
   Näin koko käännöstä ei tarvitse emuloida. QEMU käynnistää valmiin ARM64-kuvan
   agentilla HTTP- ja terveystarkistuksia varten; staging testaa sen vielä aidolla
   ARM64-VM:llä. Dockerfile tukee myös natiivia AMD64- ja ARM64-käännöstä ja hylkää
   muut suoritinparit. Seuraa silti jobin 60 minuutin aikarajaa. Sovelluksen
   tuotanto-VM:ää ei käytetä build-agenttina.
   [Dockerin monialustakäännökset](https://docs.docker.com/build/building/multi-platform/)
   ja [Rustin ARM64 Linux -kohde](https://doc.rust-lang.org/rustc/platform-support/aarch64-unknown-linux-gnu.html)
   kuvaavat menetelmän ja käännöstyökalujen vaatimukset.
8. Aktivoi `enableDeployments` vasta käyttöoikeuksien ja ulkoisten tarkistusten jälkeen.
   Aja `main` stagingiin, varmista onnistuminen ja säilytä build. Kokeile myös
   hallitusti hylättävää julkaisua. Luo vasta sen jälkeen ensimmäinen tuotantotagi.

## Salaisuudet, terveystarkistus ja palautuminen

Sovelluksen token säilyy kummankin VM:n omassa suojatussa tiedostossa. CI ei saa
sitä. Julkaisu siirtää vain konttikuvan. Blob-latausta varten muodostetaan vain
yhden artefaktin lukemiseen tarkoitettu, 30 minuutin HTTPS-SAS. Arvoa käsitellään
muistissa ja yksityisessä väliaikaistiedostossa; se ei kuulu build-artefakteihin.
Azure Run Commandin ylläpitäjä kuuluu tämän siirron luottamusrajaan.

VM varmistaa arkiston pituuden ja SHA-256:n, ARM64-alustan, kuvan configuration
digestin sekä ladatun kuvan asetukset ja kerrokset. Julkaisu ottaa nykyisellä
backup-palvelulla varmuuskopion, pysäyttää sovelluksen ja käynnistää uuden kuvan
samalla tietolevyllä ja samoilla runtime-rajoituksilla. Yhden instanssin SQLite-malli
aiheuttaa lyhyen katkon; tämä ei ole korkean saatavuuden toteutus.

Jos uusi kuva ei tule valmiiksi ja tietokannan skeema on ennallaan, päivittäjä
palauttaa edellisen kuvan ja varmistaa sen terveystarkistuksen. Putki jää silti
epäonnistuneeksi. Jos skeema muuttui, palvelu jätetään pysäytetyksi ja ylläpitäjä
palauttaa yhteensopivan version ja tarvittaessa varmuuskopion runbookin avulla.
Skeeman vertailu ei tunnista kaikkia tiedon merkityksen muutoksia: tietomigraatiot
vaativat erillisen suunnitelman ja testin. [Päivityskoodi](../deploy/azure/update_runtime.py)
ei alusta levyä, vaihda salaisuuksia tai päivitä käyttöjärjestelmän paketteja.

CI:n staattiset ja yksikkötestit eivät osoita Azure RBAC:n, federationin,
staging-julkaisun tai tuotannon palautumisen toimivuutta. Nämä hyväksytään vasta
todellisen ympäristön erikseen kirjattujen kokeiden perusteella.

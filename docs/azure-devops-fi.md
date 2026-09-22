# Azure DevOps: stagingista hallittuun tuotantojulkaisuun

Tämä toteutus käyttää projektin **DevOpsYAMKOpenDemo / DevOpsDemo** Azure Repos
-repositoriota `cyberwatch-rs`. [Putken YAML](../azure-pipelines.yml) on versionoitu
koodin kanssa. Nykyinen Azure-VM säilyy tuotantokohteena. Stagingilla on oma
VM, tietolevy, salaisuudet ja resurssiryhmä. Opintojakson tehtävänannot ja
palautukset ovat edelleen vain Moodlen kurssioppaassa.

## Käyttöönoton tila 22.9.2026

Azure CLI:llä vahvistettu kohdetilaus on **LapinAMK-Student-YAMKDevops-SANDBOX**
(`afe8ae0d-d866-47a9-bc56-e1f4475e6cc6`). Toteutus on Azure Reposin
`codex/azure-devops-cicd`-haarassa ja [pull requestissa 1](https://dev.azure.com/DevOpsYAMKOpenDemo/DevOpsDemo/_git/cyberwatch-rs/pullrequest/1).
Sitä ei ole vielä yhdistetty `main`-haaraan.

- [Sovelluksen CI-ajo 8](https://dev.azure.com/DevOpsYAMKOpenDemo/DevOpsDemo/_build/results?buildId=8&view=results)
  onnistui commitilla `1aa278a`: Quality-, Security- ja ARM64-jobit läpäisivät
  tarkistukset. Mukana olivat 57 Python-testiä, Rust-tarkistukset, HTTP-testit,
  Semgrep, Trivy sekä oikean ARM64-konttikuvan rakentaminen, skannaus ja
  käynnistystesti QEMUlla. Julkaisuartefakti julkaistiin putken artefakteihin.
- [IaC:n validointiajo 7](https://dev.azure.com/DevOpsYAMKOpenDemo/DevOpsDemo/_build/results?buildId=7&view=results)
  onnistui commitilla `a03c648`: 15 IaC-testiä, molempien Bicep-mallien käännös
  lukitulla versiolla `0.43.8` ja Trivy-tarkistus.
- Olemassa olevaan tuotantoon tehty paikallinen, Azure CLI:llä tunnistautunut
  what-if-suunnitelma onnistui commitilla `45d3006`. Kahdeksalle hallitulle
  resurssille ei löytynyt toteutettavia muutoksia. Kolme palvelun laskennallista
  tai vain luettavaa ominaisuuseroa kirjattiin `NoEffect`-havainnoiksi.
  Tämä oli suunnittelukoe; apply-vaihetta ei ajettu.
- Hyväksytty staging-ympäristö on luotu. Sovellus asennettiin onnistuneen CI-ajon
  8 artefaktista, jonka tiiviste ja ARM64-kuva tarkistettiin ennen asennusta.
  HTTPS-, autentikointi-, readiness- ja verkkorajauksen tarkistukset onnistuivat.
  Käyttöjärjestelmän päivitysten jälkeen tehty oikea uudelleenkäynnistys säilytti
  tietokannan ehjänä, ja palvelut käynnistyivät automaattisesti. Sovellus käyttää
  omaa tietokantaa ja omia salaisuuksia. [Ensimmäisellä tiedonhakukierroksella](evidence/azure-staging-bootstrap-live-20260922.json)
  29 lähdettä 38:sta onnistui; yhdeksän lähteen haku epäonnistui.
  Toimiva readiness ei tarkoita, että kaikki ulkopuoliset tietolähteet toimivat.
  Bootstrap on ylläpitäjän käyttöönottotoimi: se ei korvaa tuotantotagin vaatimaa
  onnistunutta `main`-haaran `DeployStaging`-vaihetta.
- Stagingin paikallinen what-if onnistui commitilla `0898530`: kahdeksan
  hallittua resurssia, ei toteutettavia muutoksia. IaC:n Azure Pipelines
  -yhteyden kautta tehtävä Plan/Apply-koe on vielä tekemättä.
- DevOps-ympäristöt `cyberwatch-staging` ja `cyberwatch-production` on luotu.
  Molemmissa on exclusive lock ja käyttöoikeus vain putkille `Cyberwatch-CICD`
  (2) sekä `Cyberwatch-Infrastructure` (3). Tuotantoympäristössä on lisäksi
  Matias Hiltusen hyväksyntä. Nykyinen asetus sallii hyväksyjän hyväksyä myös
  itse käynnistämänsä ajon; kyseessä ei ole kahden henkilön hyväksyntämalli.
- Repositorion oletushaara on `main`. Haaran vaaditut build validation
  -käytännöt suorittavat sovelluksen CI:n ja IaC-tiedostoja muutettaessa
  infrastruktuurin validoinnin. Mainiin yhdistäminen vaatii lisäksi Matias
  Hiltusen katselmoinnin, ja uusi push nollaa hyväksynnän. Yhden opettajan demossa
  myös oman PR:n hyväksyminen on sallittu; tämä ei ole riippumaton vertaisarviointi.
- Projektin Build Service -identiteetiltä on estetty tagien luonti tässä
  repositoriossa; lähdekoodin luku säilyy sallittuna. Tarkistushetkellä projektin
  Contributors- ja Project Administrators -ryhmien ainoa henkilöjäsen oli
  opettaja. Repositorio perii edelleen näiden ryhmien oikeudet: ryhmien
  jäsenmuutosten yhteydessä on tarkistettava myös tagien luontioikeudet.
  Projektin asetukset rajaavat YAML-jobien tokenit tähän projektiin ja jobissa
  viitattuihin repositorioihin. WIF-identiteetin Azure RBAC ja job tokenin
  DevOps-oikeudet ovat eri käyttöoikeuksia.
  [Microsoft: job access tokens](https://learn.microsoft.com/en-us/azure/devops/pipelines/process/access-tokens?view=azure-devops),
  [Microsoft: Git tags](https://learn.microsoft.com/en-us/azure/devops/repos/git/git-tags?view=azure-devops).

**Azure-julkaisut ovat edelleen poissa käytöstä** (`enableDeployments: false`).
Stagingin VM, verkko, levyt ja yksityinen artefaktitallennus on luotu.
Todellinen tallennustilin nimi `cywlqgeq7hp4llyw` on kirjattu `targets.json`-tiedostoon.
Kaikki neljä managed identityä, niiden federated credential -määritykset ja
WIF-palveluyhteydet on luotu. Tuotannon kummassakin palveluyhteydessä on opettajan
hyväksyntä YAML:n ulkopuolella. Nykyistä tuotantosovellusta ei ole muutettu.

Nykyiseltä Azure-tililtä puuttuu `Microsoft.Authorization/roleAssignments/write`.
[Ylläpitäjän täsmällinen RBAC-ohje](azure-rbac-handoff-fi.md) sisältää luoduille
identiteeteille myönnettävät 12 resurssikohtaista roolia. Kun roolit on myönnetty,
kunkin palveluyhteyden käyttö avataan vain omalle putkelleen: sovellusputki 2
tai IaC-putki 3. **Tällä hetkellä minkään palveluyhteyden pipeline-käyttöä ei
ole sallittu.** DevOpsin palauttama `isReady: true` ei osoita RBAC:n tai WIF:n
toimivuutta: tässä käyttöönotossa palvelu palautti sen jo yhteyden luomisen
yhteydessä. Todellinen pääsy varmennetaan erikseen putkiajolla.
Ympäristön hyväksyntä yksin ei suojaa palveluyhteyden käyttöä muokatusta
YAML-tiedostosta; siksi tuotannon hyväksynnät ovat myös palveluyhteyksissä.
[Päivätty tarkistusnäyttö](evidence/azure-devops-setup-20260922.json)
erittelee kokeillut ja vielä kokeilematta olevat vaiheet.

CI:n `verifyReleaseArtifact: true` mahdollistaa ARM64-kuvan rakentamisen ja
testaamisen työhaarasta ennen yhdistämistä. Se ei julkaise työhaaraa Azureen:
stagingin julkaisuehto edellyttää edelleen `main`-haaraa. Infrastruktuurin
ylläpidolle on [oma IaC-putki ja ohje](azure-iac-fi.md). Se käyttää erillisiä
identiteettejä, jotta sovelluksen julkaisu ei saa oikeutta muuttaa verkkoa tai
tallennustilin määrityksiä. Kaikkien neljän identiteetin nimet ja oikeusrajat ovat
[koneellisesti luettavassa käyttöönottosuunnitelmassa](../deploy/azure/access-plan.json).

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

Sovelluksen julkaisu käyttää kahta **user-assigned managed identityä** ja
**workload identity federation** -palveluyhteyttä. IaC-putkella on lisäksi
[kaksi omaa identiteettiä ja yhteyttä](azure-iac-fi.md#kohteet-ja-vastuut).
Entra-sovellusrekisteröintiä tai pitkäikäistä client secretia ei
tarvita. Federationin `issuer` ja `subject` otetaan juuri luodun DevOps-yhteyden
vastauksesta; niitä ei päätellä organisaation nimestä. [Microsoft: manual WIF setup](https://learn.microsoft.com/en-us/azure/devops/pipelines/release/configure-workload-identity?view=azure-devops).

Sovelluksen julkaisun kohteet tilauksessa
`afe8ae0d-d866-47a9-bc56-e1f4475e6cc6`:

| Kohde | Staging | Tuotanto |
| --- | --- | --- |
| Resurssiryhmä | `rg-cyberwatch-staging-swe` | nykyinen `rg-cyberwatch-yamk-swe` |
| VM | luotu `cyberwatch-staging` | nykyinen `cyberwatch-yamk` |
| Identity | `id-cyberwatch-ado-staging` | `id-cyberwatch-ado-prod` |
| Service connection | `cyberwatch-staging-wif` | `cyberwatch-prod-wif` |
| DevOps environment | luotu `cyberwatch-staging` | luotu `cyberwatch-production` |

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
4. Luo sovelluksen kaksi identityä ja palveluyhteyttä. Pidä palveluyhteyksien
   pipeline-käyttö estettynä roolien varmentamiseen asti. Lisää kummankin yhteyden oma
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
   Kun mukana on myös IaC-putki, luo lisäksi sen kaksi identiteettiä ja yhteyttä
   ja käytä [ylläpitäjän 12 roolin yhteistä ohjetta](azure-rbac-handoff-fi.md)
   (`--purpose all`). IaC-yhteyksien käyttöä ei avata pelkkien sovellusroolien perusteella.
5. Tarkista jo luodut DevOps-ympäristöt: vain putket 2 ja 3 saavat käyttää niitä,
   molemmissa on exclusive lock ja tuotannossa opettajan hyväksyntä.
   Rajaa jokainen sovelluksen palveluyhteys vain putkelle 2 ja jokainen IaC-yhteys
   vain putkelle 3. **Grant access permission to all pipelines** jätetään pois.
   Lisää tuotannon molempiin palveluyhteyksiin opettajan hyväksyntä YAML:n
   ulkopuolella. Yhteinen ympäristölukko estää sovelluksen ja IaC:n samanaikaiset
   muutokset samassa ympäristössä.
6. Tarkista `main`-haaran jo luodut build validation -käytännöt ja opettajan
   katselmointivaatimus. Varmista, ettei yleistä policy bypass -oikeutta ole
   annettu. Rajaa tuotantotagien luonti ja force push -oikeudet julkaisusta
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

Käyttöönoton yllä oleva järjestys kuvaa myös uuden vastaavan ympäristön perustamisen.
Tämän demon jo tehtyjä vaiheita ei ajeta uudelleen; ajantasainen tila on sivun alussa.

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
Päivittäjä pysäyttää myös terveystarkistuksen ajastimen ja mahdollisen käynnissä
olevan tarkistuksen muutoksen ajaksi. Se nollaa systemd-palvelun käynnistysyritysten
rajoituksen ennen vanhan kuvan käynnistystä ja palauttaa seurannan vasta
toimivaksi varmistetulle versiolle.
Skeeman vertailu ei tunnista kaikkia tiedon merkityksen muutoksia: tietomigraatiot
vaativat erillisen suunnitelman ja testin. [Päivityskoodi](../deploy/azure/update_runtime.py)
ei alusta levyä, vaihda salaisuuksia tai päivitä käyttöjärjestelmän paketteja.

CI:n staattiset ja yksikkötestit eivät osoita Azure RBAC:n, federationin,
staging-julkaisun tai tuotannon palautumisen toimivuutta. Nämä hyväksytään vasta
todellisen ympäristön erikseen kirjattujen kokeiden perusteella.

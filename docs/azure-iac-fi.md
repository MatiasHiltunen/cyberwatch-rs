# Azure-infrastruktuurin suunnittelu ja hallitut muutokset

Infrastruktuurin kuvaus eli **Infrastructure as Code (IaC)** sijaitsee samassa
Azure Repos -repositoriossa kuin sovelluskoodi. Infrastruktuuriputki käyttää
erillistä identiteettiä ja hyväksyntää. Sovelluksen CI/CD-putki julkaisee
konttikuvan; se ei tarvitse oikeuksia muuttaa verkkoa tai tallennustiliä.
[Sovelluksen julkaisupolku](azure-devops-fi.md) kuvaa stagingin ja tuotannon
versionhallinnan. Tässä ohjeessa kuvataan infrastruktuurin ylläpito.

Putken Validate-, Plan- ja Apply-vaiheet käyttävät Bicep-versiota `0.43.8`.
Sama kääntäjä tuottaa tarkistettavan template-tiedoston samalla tavalla myös
hyväksyntää odottaneessa ajossa. Versio päivitetään hallitusti ja uusi suunnitelma
tehdään päivityksen jälkeen; vanhan suunnitelman tiivistetarkistusta ei ohiteta.

## Kohteet ja vastuut

Kaikki kohteet ovat tilauksessa **LapinAMK-Student-YAMKDevops-SANDBOX**, jonka
tunniste on `afe8ae0d-d866-47a9-bc56-e1f4475e6cc6`. Kohdevalinnat luetaan
versionoidusta `deploy/azure/targets.json`-tiedostosta ja tarkistetaan
skriptin kiinteää ympäristörajausta vasten. Tyhjä stagingin tallennustilin nimi
estää ajon, kunnes bootstrap on valmistunut ja todellinen nimi tallennettu.

| Ympäristö | Resurssiryhmä | IaC-identiteetti | Service connection |
| --- | --- | --- | --- |
| staging | `rg-cyberwatch-staging-swe` | `id-cyberwatch-iac-staging` | `cyberwatch-iac-staging-wif` |
| prod | `rg-cyberwatch-yamk-swe` | `id-cyberwatch-iac-prod` | `cyberwatch-iac-prod-wif` |

Kumpikin **user-assigned managed identity** tunnistautuu **workload identity
federation** -menetelmällä. Entra-sovellusrekisteröintiä ja pitkäikäistä
client secretia ei tarvita. Ylläpitäjä myöntää identiteetille seuraavat
roolit vain sen oman ympäristön resurssiryhmään: **Virtual Machine Contributor**,
**Network Contributor** ja **Storage Account Contributor**. Identiteetille ei
myönnetä yleistä Contributor-roolia eikä oikeutta hallita RBAC-roolimäärityksiä
tai managed identityjen federated credential -luottamussuhteita.

Kun resurssit ja kaikki neljä identiteettiä on luotu, oikeutettu ylläpitäjä
tarkistaa sovellus- ja infrastruktuuriroolit komennolla
`python deploy/azure/grant_pipeline_roles.py --purpose all`. Komento vain lukee
ja näyttää suunnitelman. Roolit myönnetään erikseen valinnalla
`--purpose all --apply`. Federation ei itsessään myönnä RBAC-oikeuksia.

Nämä infrastruktuuriroolit ovat silti laajat oman ympäristön sisällä.
VM-rooli mahdollistaa ylläpitokomennot, ja Storage Account Contributor voi
lukea tallennustilin avaimia. Siksi vain nimetty infrastruktuuriputki saa käyttää
palveluyhteyttä, ja sen käyttö suojataan Azure DevOpsin YAML:n ulkopuolisella
hyväksynnällä. CI-testit ja pull requestin koodi eivät saa käyttää tätä yhteyttä.
Tuotannon hyväksyjä tarkistaa suunnitelman ennen apply-vaihetta. Ympäristön
**exclusive lock** estää saman ympäristön rinnakkaiset putkimuutokset.
IaC ja sovelluksen julkaisu käyttävät yhteisiä DevOps-ympäristöjä
`cyberwatch-staging` ja `cyberwatch-production`, jotta niiden apply- ja
julkaisuvaiheet eivät muuta samaa ympäristöä yhtä aikaa.
Se ei estä ylläpitäjän erillistä Azure CLI -komentoa.

## Bootstrap ja olemassa olevan ympäristön ylläpito

[`main.bicep`](../deploy/azure/main.bicep) luo uuden ympäristön infrastruktuurin
erikseen hyväksytyssä bootstrap-vaiheessa. Uuden VM:n SSH-avain, Ubuntu-kuvan
versio ja cloud-init toimitetaan tällöin kerran. Alkuperäinen
[`deploy.py`](../deploy/azure/deploy.py) on tämän käyttöönoton ylläpitäjätyökalu:
sen `what-if`-toiminto voi luoda resurssiryhmän ja valmistella paikalliset
SSH-avaimet. Sitä ei kutsuta tässä jatkuvan ylläpidon putkessa.

[`steady-state.bicep`](../deploy/azure/steady-state.bicep) ylläpitää kahdeksaa
jo olemassa olevaa resurssia: NSG, VNet, julkinen IP, datalevy,
tallennustili, Blob-palvelu, `artifacts`-kontti ja sen lifecycle-käytäntö.
Se ei lähetä VM:n tai sen NIC-verkkokortin PUT-pyyntöä, muuta käyttöjärjestelmää
tai suorita runtime-asennusta. VM ja NIC luetaan vain kohteen tarkistamiseksi.
NIC:n sidokset ja asetukset säilyvät bootstrap-mallissa; niiden muutokset
tarvitsevat erillisen katselmoinnin. Näin ylläpito ei yritä palauttaa
verkkokortin palveluntarjoajakohtaisia ominaisuuksia tuntemattomiin oletusarvoihin.
Kaikkien kahdeksan hallitun resurssin sekä VM:n ja NIC:n on oltava olemassa
ennen suunnittelua ja uudelleen ennen toteutusta.
Puuttuvan resurssin automaattinen uudelleenluonti estetään, jotta esimerkiksi
kadonnut datalevy ei korvautuisi huomaamatta tyhjällä levyllä.

Jaottelu on tarkoituksellinen: yksittäisen Azure-VM:n `customData`-arvoa ei
voi päivittää luomisen jälkeen. **Incremental**-tilassakin määritellyn
resurssin kaikki ominaisuudet lähetetään uudelleen; puuttuva ominaisuus voi
palautua oletusarvoonsa. Pelkkä `osProfile`-lohkon poistaminen tavallisesta
VM-resurssimäärityksestä ei siis ole turvallinen osapäivitysmalli.
[Microsoft: custom data](https://learn.microsoft.com/en-us/azure/virtual-machines/custom-data),
[Microsoft: deployment modes](https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/deployment-modes).

Ylläpitomalli säilyttää bootstrapin verkko-, levy- ja tallennusasetukset.
Suunnitelma hyväksyy vain rajatut, katselmoitavat muutokset: tagit,
NSG-säännöt, julkisen IP:n idle timeout, nimetyt tallennustilin yhteys- ja
käyttöasetukset, Blob-kontin julkisuus ja lifecycle-käytäntö. Levyn koko,
verkon osoiteavaruus, DNS-nimi, salausavaimen lähde sekä muut korvaamiseen
tai tietojen säilymiseen vaikuttavat muutokset pysäyttävät putken.
Ne tarvitsevat erillisen ylläpito- tai palautussuunnitelman.
NSG:n tai tallennuskäytännön sallittu muutos ei automaattisesti ole turvallinen:
hyväksyjä arvioi myös sen vaikutuksen pääsyyn ja tietojen säilytykseen.

What-if voi ilmoittaa palvelun automaattisesti asettaman oletusarvon poistoksi,
vaikka arvo ei käyttöönotossa poistu. Malli säilyttää Azuresta vahvistetut
kirjoitettavat DDoS-, VNet-, Blob retention- ja container encryption -asetukset
eksplisiittisesti. Skripti merkitsee erikseen `NoEffect`-havaintoina Azuren
itsensä vain luku -ominaisuuksiksi luokittelemat arvot sekä kaksi rajattua
Standard SSD -levyn laskennallista suorituskykyarvoa: 500 IOPS ja 100 MB/s.
Jälkimmäinen poikkeus hyväksyy vain `Delete`-esityksen, kun ennen- ja
jälkeen-tilan SKU on sama `StandardSSD_LRS`, koko on 4 GiB ja uusi määrittely
ei aseta suorituskykyarvoa. Uusi arvo, toinen SKU, koon muutos tai muu
tuntematon ero pysäyttää ajon. Havaintojen polut ja syyt jäävät raporttiin.
[Microsoft: what-if noise ja NoEffect](https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/deploy-what-if),
[Microsoft: disk properties](https://learn.microsoft.com/en-us/azure/templates/microsoft.compute/disks).

## Plan- ja apply-vaiheiden käyttö

[`azure-infra.yml`](../azure-infra.yml) määrittää infrastruktuuriputken.
Suorita putki katselmoidusta commitista. Paikallinen vastaava suunnittelukomento
edellyttää Azure CLI -kirjautumista ja oikeaa tilausvalintaa:

```bash
python tools/ado_infra.py plan --environment staging --artifact reports/infra-plan
```

Hakemiston pitää olla uusi tai tyhjä. Skripti tarkistaa nykyiset resurssit,
kääntää Bicepin ARM JSON -muotoon ja suorittaa Azure Resource Managerin
**what-if**-tarkistuksen. Se ei luo, muuta tai poista Azure-resursseja.
Plan tarvitsee silti etuoikeutetun Azure-yhteyden: normaali what-if tarkistaa
samat resurssien kirjoitusoikeudet ja deployment-oikeudet kuin käyttöönotto.
Skriptissä ei ohiteta tätä tarkistusta kevyemmällä validation level -asetuksella.
[Microsoft: what-if permissions](https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/deploy-what-if).

Julkaise `reports/infra-plan` erillisenä pipeline artifact -pakettina.
Hyväksyjä tarkistaa erityisesti `what-if.json`-tiedoston ennen apply-vaihetta:

- `template.json` on juuri tässä commitissa käännetty infrastruktuurikuvaus.
- `parameters.json` sisältää vain kiinteän ympäristön nimet ja sijainnin.
- `what-if.json` sisältää sallitut resurssit ja niiden täsmälliset,
  ei-salaiset ominaisuusmuutokset. Kokonaisten resurssivastausten muita
  ominaisuuksia ei kopioida raporttiin.
- `plan.json` yhdistää ympäristön, lähdecommitin, build-tunnisteen sekä
  lähdetiedostojen ja artefaktitiedostojen SHA-256-tiivisteet.

Apply-job lataa juuri tämän ajon artefaktin ja käyttää samaa lähdecommittia:

```bash
python tools/ado_infra.py apply --environment staging --artifact reports/infra-plan
```

Apply sallitaan vain putkiajossa suojatusta `main`-haarasta. Puuttuva
`BUILD_SOURCEBRANCH` ei kelpaa paikallisen ajon poikkeusluvaksi. Skripti
tarkistaa tiivisteet, kiinteät parametrit ja lähdecommitin sekä kääntää saman
Bicep-lähteen uudelleen. Käytä molemmissa vaiheissa samaa Bicep-versiota.
Pelkkä tiiviste ei ole allekirjoitus: uudelleenkäännös estää muokatun
template-tiedoston hyväksymisen pelkästään manifestin tiivistettä vaihtamalla.
Repo-, pipeline artifact- ja approval-oikeudet ovat edelleen luottamusrajoja.

Skripti suorittaa what-if-tarkistuksen uudelleen juuri ennen applya. Jos
resurssit tai suunnitelman vaikutus ovat muuttuneet, se pysähtyy ja vaatii
uuden suunnitelman hyväksymisen. Resurssien luonti, poisto, tuntematon kohde,
puuttuva resurssi sekä tulkitsematon tulos pysäyttävät ajon. Toteutus käyttää
ainoastaan Incremental-tilaa. Jos muutoksia ei ole, ARM deployment -ajoa
ei lähetetä lainkaan.

What-if ja apply eivät muodosta atomista transaktiota. Niiden väliin jää
lyhyt aika, jolloin ulkopuolinen ylläpitotoimi voi muuttaa ympäristöä.
Käytä exclusive lockia, sovittua muutosikkunaa ja rajattuja ylläpitäjäoikeuksia.
What-if ei myöskään todista sovelluksen toimivuutta: infrastruktuurimuutoksen
jälkeen varmista HTTPS, sovelluksen readiness, levyn liitos ja tiedon säilyminen
[käyttöönoton runbookin](azure-deployment.md) mukaan.

Paikalliset yksikkötestit tarkistavat hylkäyspolut ja artefaktin eheyden.
Ne eivät osoita WIF-yhteyden, Azure RBAC:n tai todellisen what-if/apply-ajon
toimivuutta. Käyttöönotto hyväksytään vasta Azure Reposista käynnistetyn
todellisen putkiajokokeen perusteella.

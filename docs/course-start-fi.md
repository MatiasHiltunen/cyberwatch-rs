# Edistynyt lähtöprojekti: Cyberwatch RS

**Cyberwatch RS** kokoaa haavoittuvuus- ja tietoturvatietoa useista lähteistä Rust-sovellukseen ja näyttää sen selaimessa. Se sopii ryhmälle, joka haluaa tutkia valmista, pientä API-esimerkkiä laajempaa järjestelmää. Valitse siitä hallittava osa. Projektin valinnan ehdot ja palautukset ovat vain kurssioppaassa (opintojakson Moodlen Kurssiopas ja oppimateriaalit).

Tässä materiaalissa tarkasteltu [GitHub-versio on commit 9550b4b](https://github.com/MatiasHiltunen/cyberwatch-rs/tree/9550b4bc1da2b8bb2eb67accbfe88804522d8781). Moodlen **Lähtöprojektin tiedostot** -paketin `cyberwatch-rs`-kansio sisältää tämän version sekä kurssia varten tehdyt dokumentaatio-, Dev Container- ja kehityssalaisuustäydennykset. Paketin `COURSE_REVISION.md` yksilöi erot. GitHubin tämänhetkinen `main` ja kurssipaketti eivät välttämättä ole sama versio. GitHub-version vanhat kurssikohtaiset määräajat ja erillisen repositorion vaatimus eivät määritä tämän toteutuksen suoritusta.

## Aloita toimivasta paikallisesta demosta

Pura paketti ja avaa `cyberwatch-rs` omana projektikansionaan VS Codessa. Tarvitset Dockerin ja Dev Containers -laajennuksen. Valitse **Dev Containers: Reopen in Container** ja odota valmistumista. Ensimmäinen koonti lataa työkaluja ja Rust-riippuvuuksia; se voi kestää. Kontti sisältää Rustin, C/C++-koontityökalut, Pythonin, Node.js:n ja Azure CLI:n. Node.js tarkistaa selaimen JavaScriptin syntaksia; sovellus ei tarvitse erillistä Node-palvelinta.

Aja kontin terminaalissa:

```sh
python tools/check.py
cargo run --locked
```

Avaa selaimessa `http://127.0.0.1:8080`. Demon aineisto on synteettistä ja lähteiden päivitys on pois käytöstä. Kontin sisäinen palvelin kuuntelee konttiverkkoa, mutta Docker julkaisee portin vain isäntäkoneen localhost-osoitteeseen. Asetukset eivät ole julkisen palvelun käyttöönotto-ohje. Tarkka selitys löytyy paketin `.devcontainer/README.md`-tiedostosta. Dockerin porttijulkaisu määrittää, mihin isäntäosoitteeseen portti sidotaan. [Docker: port publishing](https://docs.docker.com/engine/network/port-publishing/).

Jos selain ei saa yhteyttä, tarkista kontin terminaalissa `curl -fsS http://127.0.0.1:8080/ready`. Palvelimen täytyy olla käynnissä. Jos sisäinen pyyntö toimii, tarkista isännällä `docker port` ja portin 8080 mahdollinen muu käyttäjä. Dev Containerin luominen ei käynnistä sovellusta automaattisesti. Sulje sovellus Ctrl+C:llä. [Dev Containers: määritykset](https://containers.dev/implementors/json_reference/).

## Näin tieto kulkee sovelluksessa

Päivityksen käynnistäjä antaa pyynnön `RefreshCoordinator`-komponentille. Se välttää päällekkäisiä päivitystöitä ja välittää työn lähdekohtaisille sovittimille (*source adapters*). HTTP-kerros tarkistaa kohdeosoitteita ja rajaa pyynnön aikaa ja vastauskokoa. Sovitin tulkitsee lähteen aineiston, minkä jälkeen sovellus validoi tietueet ja tallentaa erän tietokantatapahtumassa (*transaction*). Selain hakee yhdistetyn näkymän Axum-APIsta. Lähdekohtaiset havainnot säilyvät tarkasteltavina; usean lähteen esiintyminen ei sellaisenaan todista väitteen oikeellisuutta.

Tämä kuvaus perustuu tarkastetun version [arkkitehtuurikuvaan](https://github.com/MatiasHiltunen/cyberwatch-rs/blob/9550b4bc1da2b8bb2eb67accbfe88804522d8781/ARCHITECTURE.md) ja lähdekoodiin. Repositorion teksti on toteutuksen oma kuvaus, ei riippumaton turvallisuussertifiointi.

## Miksi nämä osat ovat mukana?

**Rust, Tokio ja Axum** toteuttavat sovelluksen ja asynkronisen HTTP-palvelimen. Rajatut työjonot, rinnakkaisuuden rajat ja määräajat ovat tässä toteutuksessa tapa estää yhtä hidasta lähdettä kuluttamasta kaikkea työkapasiteettia. Kielivalinta ei poista virheellistä käyttöoikeuslogiikkaa tai haavoittuvia riippuvuuksia. Lue `src/refresh.rs` ja `src/api.rs`; tarkastele, mitä tapahtuu jonon täyttyessä ja pyynnön epäonnistuessa.

**Source adapters ja yhteinen HTTP-kerros** pitävät lähteiden erot erillään verkkoliikenteen suojauksista. `src/ingest/http.rs` hylkää yksityisiin osoitteisiin ja metadataosoitteisiin kohdistuvia pyyntöjä sekä rajoittaa uudelleenohjauksia. Tarkoitus on vähentää SSRF-riskiä: hyökkääjä ei saisi ohjata palvelinta hakemaan sisäisiä kohteita. Testit `rejects_private_metadata_credentials_and_transition_urls` ja `private_request_is_rejected_before_connecting` näyttävät tämän rajattuja koetapauksia. Sovelluksen tarkistus ei korvaa ajoympäristön egress-rajausta. [Tarkastettu HTTP-toteutus ja testit](https://github.com/MatiasHiltunen/cyberwatch-rs/blob/9550b4bc1da2b8bb2eb67accbfe88804522d8781/src/ingest/http.rs).

**Turso/libSQL-tiedostotietokanta** pitää paikallisen esimerkin ylläpidettävänä ilman erillistä tietokantapalvelua. `src/db.rs` yhdistää tietueiden ja päivitystilan tallennuksia samaan tapahtumaan, jotta epäonnistuva tallennus ei merkitsisi puuttuvaa aineistoa käsitellyksi. Yhden kirjoittajan malli ja varmuuskopioinnin tarve kuuluvat valinnan rajoihin. Usean sovellusreplikan lisääminen ei ole tämän arkkitehtuurin automaattinen skaalausratkaisu. [Tietokantatoteutus](https://github.com/MatiasHiltunen/cyberwatch-rs/blob/9550b4bc1da2b8bb2eb67accbfe88804522d8781/src/db.rs).

**Docker ja erillinen runtime-kuva** paketoivat sovelluksen. Kehityskontissa tarvitaan kääntäjiä; tuotannon runtime-kuvassa niitä ei tarvita. Ei-root-käyttäjä, vain luettava juuritiedostojärjestelmä ja poistettavat capabilities rajaavat sitä, mitä murrettu prosessi voisi tehdä. Ne eivät estä prosessia käyttämästä sille sallittua tietokantaa tai lukemasta sen omaa salaisuutta. [Dockerfile](https://github.com/MatiasHiltunen/cyberwatch-rs/blob/9550b4bc1da2b8bb2eb67accbfe88804522d8781/Dockerfile), [Azure-kontin määritys](https://github.com/MatiasHiltunen/cyberwatch-rs/blob/9550b4bc1da2b8bb2eb67accbfe88804522d8781/deploy/azure/compose.yaml).

**Azure VM, levy, VNet ja Network Security Group (NSG)** muodostavat nykyisen palvelun alustan. VM mahdollistaa paikallista mallia muistuttavan ajon, levy säilyttää tietokannan ja NSG rajaa verkosta saavutettavia portteja. Valinnan hinta on käyttöjärjestelmän, levyn, Dockerin ja päivitysten ylläpitovastuu. Tämä on eri toteutus kuin pienen esimerkin Container Apps -polku. Bicep kuvaa resurssit versionoitavana koodina; sen olemassaolo ei todista, että ajossa oleva ympäristö vastaa sitä. [Azure-resurssien Bicep-määritys](https://github.com/MatiasHiltunen/cyberwatch-rs/blob/9550b4bc1da2b8bb2eb67accbfe88804522d8781/deploy/azure/main.bicep).

**Nginx ja Certbot** hoitavat nykyisen VM-toteutuksen HTTPS-päätepistettä ja sertifikaattia. Nginxin lukijatunnistus erottaa selaimen lukuoikeuden sovelluksen hallintatokenista. TLS suojaa siirtotietä, mutta ei korjaa sovelluksen valtuutusvirhettä. **systemd** käynnistää palvelun ja **Azure Run Command** mahdollistaa ylläpidon ilman julkista SSH-porttia. Run Command -oikeus on silti vahva ylläpito-oikeus, joka kuuluu uhkamalliin. **Blob Storage** siirtää tässä esimerkissä runtime-artefakteja; sitä ei pidä kirjata todisteeksi ACR-julkaisusta. [Toteutuksen Azure-ohje](https://github.com/MatiasHiltunen/cyberwatch-rs/blob/9550b4bc1da2b8bb2eb67accbfe88804522d8781/docs/azure-deployment.md), [Microsoft: Run Command](https://learn.microsoft.com/en-us/azure/virtual-machines/linux/run-command).

**GitHub Actions, testit ja tietoturvatyökalut** kuvaavat repositorion tarkistusketjua. Rust-testit, Clippy ja Python-tarkistukset etsivät eri virheluokkia. Skannerit, SBOM ja artefaktin tunniste auttavat arvioimaan riippuvuuksia ja jäljittämään julkaisua; vihreä koonti ei ole yleinen turvallisuustodistus. Repositorion GitHub Actions -työnkulku ei ole valmis Azure DevOps -service connection. Azure-polulla samat tarkistukset voidaan ajaa Azure Pipelinesissa ja pilvitunnistautuminen rakentaa LUCIT-ohjeen (opintojakson Moodlen Kurssiopas ja oppimateriaalit) mukaan. [CI-määritys](https://github.com/MatiasHiltunen/cyberwatch-rs/blob/9550b4bc1da2b8bb2eb67accbfe88804522d8781/.github/workflows/ci.yml), tarkistusten oppimateriaali (opintojakson Moodlen Kurssiopas ja oppimateriaalit).

**Metrics-päätepiste, Prometheus-määritys ja varmuuskopiointityökalut** auttavat havainnoimaan toimintaa ja harjoittelemaan palautumista. Repositorion Prometheus- tai Kubernetes-tiedosto ei tarkoita palvelun olevan käytössä Azure-VM:llä. Varmuuskopion olemassaolo ja onnistunut palautus ovat eri havaintoja. Lue `tools/backup.py` ja kokeile palautusta omaan erilliseen demotietokantaan. Palautumisen oppimateriaali (opintojakson Moodlen Kurssiopas ja oppimateriaalit).

## Mitä Azuresta vahvistettiin 22.9.2026?

Opettajan ympäristö tarkistettiin Azure CLI:llä. VM oli käynnissä ja Cyberwatch-, Nginx- sekä Docker-palvelut toimivat. Kontti oli healthy-tilassa. Sen käyttäjä oli `10001:0`, juuritiedostojärjestelmä vain luettava, capabilities-listalta oli poistettu `ALL` ja `no-new-privileges` oli käytössä. Portti 8080 oli julkaistu VM:n localhostiin. Hallintatoken oli liitetty konttiin vain luettavana tiedostona.

**Key Vault ei ollut käytössä tässä toteutuksessa:** tarkastetun tilauksen Key Vault -luettelo oli tyhjä, VM:n identity-asetus puuttui ja sovellus käytti `ADMIN_TOKEN_FILE`-tiedostoa. Pilviympäristön muuttamista tai Key Vault -integraatiota ei tehty tilatarkistuksessa. [Paikallisten salaisuuksien ja Key Vaultin materiaali](local-secrets-fi.md) näyttää kehitystavan ja erottelee sen nykyisestä tuotantoajosta.

Tarkistus osoittaa palvelun ajotilan ja mainitut asetukset, ei kaikkien tietolähteiden tuoreutta, riippuvuuksien nykyistä haavoittuvuustilaa tai uuden lähdekoodin vastaavuutta ajossa olevaan artefaktiin. Repositorion aiemmassa Azure-tietoturvaraportissa on avoimia käyttöjärjestelmäpaketteihin liittyviä löydöksiä. Niiden nykyinen tila vaatii uuden skannauksen ja tulkinnan; vanhoja lukumääriä ei käytetä nykytilan mittauksena. [Aiempi raportti ja sen rajaus](https://github.com/MatiasHiltunen/cyberwatch-rs/blob/9550b4bc1da2b8bb2eb67accbfe88804522d8781/docs/evidence/azure-security-status.md).

**Soveltuvuusarvio:** Cyberwatch soveltuu rajattuna edistyneeksi oppimiskohteeksi. Sen vahvuus on mahdollisuus jäljittää kontrolli koodiin, testiin ja ajonaikaiseen asetukseen. Nykyinen julkinen palvelu ei ole valmis malliratkaisu kaikista kurssin tavoitteista. Hyviä rajauksia ovat esimerkiksi lähdepyynnön SSRF-rajaus, hallintatokenin elinkaari tai putken käyttöoikeus. Valinta on tämän materiaalin pedagoginen arvio tarkastetuista tiedostoista ja havainnoista.

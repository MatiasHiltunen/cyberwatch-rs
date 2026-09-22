# Paikalliset salaisuudet ja Azure Key Vault

Sovellukselle on hyödyllistä tarjota sama salaisuuden lukurajapinta eri ympäristöissä. Cyberwatch lukee hallintatokenin joko `ADMIN_TOKEN`-arvosta tai `ADMIN_TOKEN_FILE`-tiedostosta. Molempien yhtäaikainen asettaminen hylätään. Tässä käytämme tiedostoa: salaisuutta ei tarvitse kirjoittaa käynnistyskomentoon tai versionoituun asetukseen. Sovellus lukee arvon käynnistyessään; tiedoston vaihtuminen ei itsessään päivitä käynnissä olevaa prosessia. [Cyberwatchin asetuskoodi ja testit](https://github.com/MatiasHiltunen/cyberwatch-rs/blob/9550b4bc1da2b8bb2eb67accbfe88804522d8781/src/config.rs).

## Kolme eri ympäristöä

**Paikallinen offline-kehitys:** satunnainen harjoitustoken säilytetään Dev Containerin käyttäjän yksityisessä hakemistossa. Pilveä ei tarvita. Tämä ei ole paikallinen Key Vault -palvelu tai todiste Azure RBAC:n toiminnasta.

**Paikallinen sovellus ja kehityksen Key Vault:** kehittäjä kirjautuu omalla Entra-tunnuksellaan ja hakee erillisen kehityssalaisuuden oikeasta Azure Key Vaultista. Sovellus käyttää siitä tehtyä paikallista kopiota. Tässä voidaan testata oikeaa pilvipääsyä, mutta kehittäjän tunnus ei ole Azure-VM:n managed identity.

**Azure-ajoympäristö:** Key Vault -toteutuksessa sovelluksen tai salaisuusagentin managed identity hakee salaisuuden. Container Apps tukee myös omaa Secrets-toimintoa ilman Key Vaultia. Cyberwatchin nykyinen VM-toteutus käyttää paikallista salaisuustiedostoa; se ei tee Key Vault -hakua. [Microsoft: Key Vault -tunnistautuminen](https://learn.microsoft.com/en-us/azure/key-vault/general/authentication), [Container Appsin vaihtoehdot](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets).

<a id="ilman-key-vaultia"></a>
## Vaihtoehto ilman Key Vaultia: suojattu salaisuustiedosto

Tiedostomallissa sovellus saa käyttöönsä erillisen tiedoston, johon tallennetaan vain harjoitustoken. Koodi ja versionoidut asetukset sisältävät tiedostopolun. Tämä toimii myös silloin, kun Azure-oikeudet eivät riitä Key Vaultin RBAC-roolien myöntämiseen. Kurssilla hyväksyttävät toteutustavat ja näytöt on määritelty T4-tehtävänannossa (opintojakson Moodlen Kurssiopas ja oppimateriaalit).

**Dev Containerissa** alla olevan offline-ohjeen apuri luo tokenin käyttäjän kotihakemistoon. Sovellus ja apuri toimivat samalla käyttäjällä, joten tiedoston oikeus `0600` riittää. Pilvipalvelua tai kirjautumista ei tarvita.

**Docker Composella** Cyberwatchin mukana tuleva määritys liittää tokenin vain `cyberwatch`-palveluun polkuun `/run/secrets/admin-token`. Tee seuraava Linux-isännällä tai WSL:n Linux-tiedostojärjestelmässä projektin juuressa. Dockerin tulee olla käytettävissä siinä ympäristössä; Dev Containerin sisällä sitä ei ole oletuksena:

```sh
python3 tools/create_admin_secret.py
docker compose up --build -d
```

Luo tiedosto vain ensimmäisellä käyttökerralla: apuri kieltäytyy korvaamasta olemassa olevaa tokenia. Se suojaa isännän `secrets`-hakemiston oikeuksilla `0700`. Tiedoston oikeus on tässä `0644`, jotta kontin eri käyttäjätunnuksella toimiva prosessi voi lukea liitetyn tiedoston. Isännällä muiden tavallisten käyttäjien pääsyn estää ylemmän hakemiston `0700`. Älä kopioi tiedostoa yleisesti luettavaan hakemistoon. Windowsin NTFS-käyttöoikeudet vaativat erillisen ACL-tarkastelun; nämä Linux-oikeudet eivät kuvaa niitä. [Projektin luontiapuri](https://github.com/MatiasHiltunen/cyberwatch-rs/blob/9550b4bc1da2b8bb2eb67accbfe88804522d8781/tools/create_admin_secret.py).

Compose käyttää paikalliseen tiedostoon perustuvaa liitosta (*bind mount*). Se ei tee isännän tiedostosta salattua salaisuussäilöä. `_FILE` toimii tässä, koska Cyberwatchin koodi tukee sitä; se ei ole kaikkien sovellusten automaattinen ominaisuus. [Docker: Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/).

**Omalla Azure-VM:llä** samaa mallia voi käyttää ilman Key Vaultia. Tarkastettu Cyberwatchin käyttöönottokoodi luo tokenin `/etc/cyberwatch/secrets`-hakemistoon ja liittää sen konttiin vain lukuun. Tarkastetussa ympäristössä hakemisto oli rootin `0700`, tiedosto `root:root` ja `0640`, ja kontti käytti tunnuksia `10001:0`. Siksi kontin prosessi pystyi lukemaan liitetyn tiedoston ryhmäoikeudella. Nämä ovat kyseisen toteutuksen asetuksia, eivät yleispäteviä oikeuksia jokaiseen konttiin. [Käyttöönottokoodi](https://github.com/MatiasHiltunen/cyberwatch-rs/blob/9550b4bc1da2b8bb2eb67accbfe88804522d8781/deploy/azure/configure-runtime.py).

### Miksi malli suojaa ja mitä se ei ratkaise?

Salaisuus jää lähdekoodin, konttikuvan ja käynnistyskomennon ulkopuolelle. Tiedostooikeudet rajaavat tavallisten käyttäjien pääsyä, ja vain lukuun tehty liitos estää sovellusta muuttamasta kyseistä tiedostoa. Sovellus pystyy kuitenkin lukemaan tokenin: sovelluksen haltuunotto voi paljastaa sen. Myös root ja Docker-ylläpitäjä kuuluvat luottamusrajan sisälle. Pelkkä `.gitignore` ei ole käyttöoikeussuoja.

Vaihto on tässä mallissa ylläpitäjän tehtävä. Suunnittele rajatussa harjoitusympäristössä uuden satunnaisen tokenin luonti, tiedoston turvallinen korvaaminen samoilla oikeuksilla ja sovelluksen uudelleenkäynnistys. Cyberwatch lukee tokenin käynnistyessään. Jos Compose-tiedoston lähdetiedosto korvataan uudella tiedostolla, luo myös kontti uudelleen komennolla `docker compose up -d --force-recreate cyberwatch`, jotta liitos osoittaa uuteen tiedostoon. Päivitä myös tokenia käyttävä asiakas. Tavallinen käynnistys tai paikallisen apurin uudelleenajo ei itsessään kierrätä tokenia.

Tallenna vaihdon ajankohta, vastuuhenkilö ja kokeiden tulokset ilman tokenia. Ratkaisu ei sellaisenaan tarjoa keskitettyä salaisuuksien versiohistoriaa, hakujen auditointia tai automaattista kiertoa. Arvioi nämä rajat oman uhkamallin perusteella. Dev Containerin offline-tila ei myöskään todista ulkoisen tietolähteen tai pilven käyttöoikeuksien toimivuutta.

## 1. Offline-kehitys Dev Containerissa

Moodlen lähdepaketin Cyberwatch-kansiossa Dev Containerin käyttöönotto luo automaattisesti satunnaisen tokenin. Voit varmistaa paikallisen tokenin myös näin kontin Bash-terminaalissa:

```sh
python tools/dev_secrets.py local
cargo run --locked
```

Apuri säilyttää jo olemassa olevan kelvollisen tokenin. Hakemisto `$HOME/secrets` on vain käyttäjän käytettävissä (`0700`) ja tiedosto `admin-token` vain käyttäjän luettavissa ja kirjoitettavissa (`0600`). Asetuksiin tallennetaan polku, ei salaisuutta. Apuri on tarkoitettu Linuxiin eli tähän Dev Containeriin; se ei aseta Windowsin ACL-oikeuksia.

Salaisuus sijaitsee kontin kotihakemistossa lähdekoodin ulkopuolella. Kontin uudelleenluominen voi poistaa sen, jolloin syntyy uusi harjoitustoken. Tämä on tarkoituksellinen kehitysmalli. Tallenna lähdekoodimuutokset työtilaan ja käsittele pilveen kirjautuminen uudelleenluonnin jälkeen erikseen. Isäntäkoneen `.azure`-hakemistoa tai Docker socketia ei liitetä tähän konttiin.

## 2. Paikallinen käyttö kehityksen Key Vaultin kanssa

Tarvitset valmiin, harjoitukseen hyväksytyn Key Vaultin ja siinä vain kehityskäyttöön luodun salaisuuden, esimerkiksi `cyberwatch-admin-dev`. Arvon tulee olla vähintään 32 merkin satunnainen ASCII-token ilman välilyöntejä. Älä käytä opettajan julkisen palvelun tai muun tuotantopalvelun tokenia. Vaultin omistaja voi luoda harjoitusarvon portaalissa; sitä ei tarvitse jakaa Gitissä tai viestinä. [Microsoft: Key Vault secrets](https://learn.microsoft.com/en-us/azure/key-vault/secrets/quick-create-cli).

RBAC-mallissa kehittäjälle annetaan tarvittava salaisuuden lukuoikeus, esimerkiksi **Key Vault Secrets User** kehitysvaultiin. Tämän apurin vaultin subscription-tarkistus tarvitsee lisäksi hallintatason lukuoikeuden kyseiseen vaultiin, esimerkiksi **Reader**. **Key Vault Reader** ei yksin anna salaisuuden arvon lukuoikeutta. Oikeuden myöntäminen, salaisuuden luominen ja sen lukeminen ovat eri tehtäviä. Vaultin verkkoasetusten on myös sallittava kehitysympäristön yhteys. [Microsoft: Key Vault RBAC](https://learn.microsoft.com/en-us/azure/key-vault/general/rbac-guide).

Kirjaudu Dev Containerin terminaalissa omalla tunnuksellasi. Korvaa isot esimerkkitekstit omilla arvoillasi:

```sh
az login --tenant TENANT-ID --use-device-code
az account set --subscription SUBSCRIPTION-ID
az account show --query '{name:name,id:id,tenant:tenantId}' -o json
```

Device code -kirjautumisessa avaat Azure CLI:n osoittaman kirjautumissivun omassa selaimessasi. Jos organisaatio estää tämän kirjautumistavan, käytä sen hyväksymää kehittäjän kirjautumista. Älä kopioi tunnistautumistokeneita isännältä konttiin. [Microsoft: Azure CLI -kirjautuminen](https://learn.microsoft.com/en-us/cli/azure/authenticate-azure-cli-interactively).

Pysäytä aiempi Cyberwatch-prosessi. Hae harjoitussalaisuus ja käynnistä sovellus **vain haun onnistuessa**:

```sh
python tools/dev_secrets.py keyvault \
  --subscription SUBSCRIPTION-ID \
  --vault KEHITYSVAULTIN-NIMI \
  --secret cyberwatch-admin-dev && \
  ADMIN_TOKEN_FILE="$HOME/secrets/keyvault-admin-token" \
  cargo run --locked
```

Apuri varmistaa vaultin subscription-tunnisteen, hakee salaisuuden Azure CLI:n kautta muistissa ja kirjoittaa sen yksityiseen tiedostoon. Se ei tulosta arvoa, välitä Azure CLI:n virhetulostetta tai lisää salaisuutta sovelluksen komentoriviargumentiksi. Virhe pysäyttää komennon. Onnistunut haku korvaa aikaisemman kehityskopion atomisesti; epäonnistunut haku jättää aiemman tiedoston ennalleen, mutta yllä oleva `&&` estää sovelluksen käynnistämisen sillä vahingossa. Halutessasi yksilöi versio `--version`-valinnalla. [Microsoft: az keyvault secret show](https://learn.microsoft.com/en-us/cli/azure/keyvault/secret?view=azure-cli-latest).

Säilytä testihavainnossa vaultin nimi, salaisuuden nimi tai version tunniste, ajankohta ja tulos organisaation käytäntöjen mukaisesti. Arvoa ei tarvita näyttöön. Älä ota käyttöön shellin `set -x` -jäljitystä tai tulosta koko prosessiympäristöä salaisuuden käsittelyn yhteydessä.

## 3. Mitä suojaukset takaavat ja mitä jää jäljelle?

Tiedostooikeudet estävät tavallista toista Linux-käyttäjää lukemasta tokenia. Ne eivät suojaa samana käyttäjänä ajettavalta haittakoodilta, rootilta tai isäntäkoneen Docker-ylläpitäjältä. Dev Container on kehitysympäristö; siihen avattava lähdekoodi ja työkalut on edelleen arvioitava.

Key Vaultin käyttöoikeuden poistaminen estää tulevia hakuja, mutta **ei mitätöi jo kopioitua tokenia**. Sovelluksen token pitää vaihtaa erikseen ja vanhan toiminta todentaa estetyksi. Cyberwatchin tämänhetkinen paikallinen apuri ei tarjoa taustalla tapahtuvaa uusintaa, automaattista kiertoa (*rotation*) tai Key Vaultin käyttökatkon yleistä ratkaisua. Harjoituksen jälkeen lopeta sovellus, poista oma kehityskopio tarvittaessa komennolla `rm -- "$HOME/secrets/keyvault-admin-token"` ja kirjaudu ulos komennolla `az logout`. Tiedoston poistaminen ei lupaa tietovälineen turvallista ylikirjoitusta. [OWASP: salaisuuden elinkaari](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html).

## Cyberwatchin VM:n myöhempi Key Vault -integraatio

Jos uhkamalli edellyttää keskitettyä salaisuuksien hallintaa, tiedostomallia voi täydentää Key Vaultilla. Seuraava on jatkokehityksen suunnitelma, ei väite valmiista integraatiosta. Käyttöönotossa valitaan sovelluksen oma managed identity ja annetaan sille tarvittava Key Vault -lukuoikeus. Sovellus voidaan muuttaa lukemaan salaisuus tuetulla Azure-kirjastolla tai VM:lle voidaan suunnitella erillinen, hallittu hakuvaihe ennen palvelun käynnistystä. Molemmissa pitää määritellä verkon pääsy, käynnistyksen virhekäyttäytyminen, paikallisen kopion oikeudet, kierto, uudelleenkäynnistys ja lokitus.

Arvioi myös luottamusraja: VM:n identiteettiä käyttävä prosessi ei automaattisesti ole eristetty muista samalla VM:llä ajettavista prosesseista. Key Vault ei estä sovellusta käyttämästä sille tarkoituksella annettua salaisuutta väärin. Testaa sallittu haku, kielletty haku ja vanhan tokenin hylkääminen omassa kehitysympäristössä ennen julkisen palvelun muutosta. [Microsoft: managed identity -turvallisuus](https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/managed-identities-faq).

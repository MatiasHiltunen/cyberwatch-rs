# Cyberwatch: ylläpitäjän RBAC-osuus

Tämä ohje koskee 22.9.2026 hyväksyttyä käyttöönottoa tilauksessa
**LapinAMK-Student-YAMKDevops-SANDBOX**, tunniste
`afe8ae0d-d866-47a9-bc56-e1f4475e6cc6`. Stagingin resurssit, neljä identiteettiä
ja niiden Azure DevOps -federoinnit on luotu. Nykyisellä käyttöönoton tekijällä
on resurssien hallintaoikeus, mutta ei oikeutta myöntää RBAC-rooleja.

Ylläpitäjän jäljellä oleva tehtävä on myöntää alla olevat **12 roolia**.
Roolimääritysten kirjoitusoikeuden on katettava kummankin ympäristön nimetyt
kohteet. Sovellukset eivät tarvitse koko tilauksen Owner- tai Contributor-roolia.

## Suoritettavat komennot

Käytä tämän repositorion `codex/azure-devops-cicd`-haaran ajantasaista versiota.
Suorita seuraavat komennot repositorion juuressa Azure CLI:llä tunnistautuneena
tilinä, jolla on oikeus `Microsoft.Authorization/roleAssignments/write`
molemmissa resurssiryhmissä. Tarkista ensin tulostuva suunnitelma.

```powershell
az account set --subscription afe8ae0d-d866-47a9-bc56-e1f4475e6cc6
python deploy/azure/grant_pipeline_roles.py --purpose all
python deploy/azure/grant_pipeline_roles.py --purpose all --apply
```

Ensimmäinen Python-komento vain lukee. Jälkimmäinen luo puuttuvat määritykset;
se tarkistaa molempien ympäristöjen VM:t, tallennustilit ja identiteetit ennen
ensimmäistä kirjoitusta. Komento voidaan ajaa uudelleen jo tehtyjä määrityksiä
tuplaamatta. Tavoite on `All 12 resource-scoped role assignments are present.`

## Luodut identiteetit

`principalId` yksilöi RBAC-roolien vastaanottajan. WIF-yhteys käyttää erillistä
`clientId`-tunnistetta; näitä kahta tunnistetta ei vaihdeta keskenään.

| Identiteetti | principalId |
| --- | --- |
| `id-cyberwatch-ado-staging` | `9c9c125d-75fc-4387-ad76-77e3be2fd6da` |
| `id-cyberwatch-iac-staging` | `1413455a-42ec-4af6-ae6a-c97557b6c2cf` |
| `id-cyberwatch-ado-prod` | `ac93d664-c762-4035-bf17-01a82a02ec35` |
| `id-cyberwatch-iac-prod` | `1a18ba27-a269-48cc-86f7-ff81adad4f74` |

## Hyväksytyt oikeusrajat

| Identiteetti | Rooli | Kohde tilauksen sisällä |
| --- | --- | --- |
| `id-cyberwatch-ado-staging` | Virtual Machine Contributor | `rg-cyberwatch-staging-swe/providers/Microsoft.Compute/virtualMachines/cyberwatch-staging` |
| `id-cyberwatch-ado-staging` | Storage Blob Data Contributor | `rg-cyberwatch-staging-swe/providers/Microsoft.Storage/storageAccounts/cywlqgeq7hp4llyw/blobServices/default/containers/artifacts` |
| `id-cyberwatch-ado-staging` | Storage Blob Delegator | `rg-cyberwatch-staging-swe/providers/Microsoft.Storage/storageAccounts/cywlqgeq7hp4llyw` |
| `id-cyberwatch-iac-staging` | Virtual Machine Contributor | `rg-cyberwatch-staging-swe` |
| `id-cyberwatch-iac-staging` | Network Contributor | `rg-cyberwatch-staging-swe` |
| `id-cyberwatch-iac-staging` | Storage Account Contributor | `rg-cyberwatch-staging-swe` |
| `id-cyberwatch-ado-prod` | Virtual Machine Contributor | `rg-cyberwatch-yamk-swe/providers/Microsoft.Compute/virtualMachines/cyberwatch-yamk` |
| `id-cyberwatch-ado-prod` | Storage Blob Data Contributor | `rg-cyberwatch-yamk-swe/providers/Microsoft.Storage/storageAccounts/cywqqv6z273n7dfk/blobServices/default/containers/artifacts` |
| `id-cyberwatch-ado-prod` | Storage Blob Delegator | `rg-cyberwatch-yamk-swe/providers/Microsoft.Storage/storageAccounts/cywqqv6z273n7dfk` |
| `id-cyberwatch-iac-prod` | Virtual Machine Contributor | `rg-cyberwatch-yamk-swe` |
| `id-cyberwatch-iac-prod` | Network Contributor | `rg-cyberwatch-yamk-swe` |
| `id-cyberwatch-iac-prod` | Storage Account Contributor | `rg-cyberwatch-yamk-swe` |

VM-oikeus sisältää Run Command -ylläpitotoimet ja pääsyn VM:n runtime-salaisuuksiin.
IaC:n Storage Account Contributor -rooli voi lukea tallennustilin avaimia.
Siksi tuotannon kumpikin palveluyhteys on suojattu opettajan hyväksynnällä.
Federation ratkaisee tunnistautumisen ilman client secretia; se ei myönnä
Azure RBAC -oikeuksia. [Microsoft: WIF-palveluyhteyden käyttöönotto](https://learn.microsoft.com/en-us/azure/devops/pipelines/release/automate-service-connections?view=azure-devops).

Kun roolit on myönnetty ja ne ovat päivittyneet Azureen, yhteydet voidaan
aktivoida ja niiden kirjautuminen sekä resurssipääsy testata putkesta.
Vasta tämän jälkeen tehdään sovelluksen staging-julkaisu ja IaC:n Plan/Apply-koe.
Käyttöönoton ajantasainen kokonaistila on [CI/CD-ohjeessa](azure-devops-fi.md).

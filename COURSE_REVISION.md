# Kurssipaketin versio 2026.09.22.3

Upstream: https://github.com/MatiasHiltunen/cyberwatch-rs

Sovelluksen tarkastettu pohja: `9550b4bc1da2b8bb2eb67accbfe88804522d8781`.
Julkaistu kehitysympäristö- ja materiaalitäydennys: `87dd30da3ceac714545d65d95548bcb15236c7eb`.
Versio 2026.09.22.3 täydentää ohjeeseen Key Vaultista riippumattoman tiedostovaihtoehdon.

Kurssitäydennys sisältää suomenkieliset toiminta- ja turvallisuusperustelut,
Azure CLI:n Dev Containerissa, LF-rivinvaihtokäytännön sekä kehityssalaisuuden
luonnin ja kehityksen Key Vault -haun (`tools/dev_secrets.py`) testeineen.
Vanhat kurssitehtävien kopiot on korvattu viittauksella Moodlen kurssioppaaseen.
Sovelluksen Rust-logiikkaa ja Azure-tuotantoympäristöä ei muutettu.

Azure-VM tarkistettiin 22.9.2026: palvelu ja runtime-kontti olivat käynnissä.
Key Vault ei ollut käytössä, VM:llä ei ollut managed identityä ja hallintatoken
tuli paikallisesta tiedostosta. Paikallinen Key Vault -apuri ei lisää pilveen
resursseja tai rooleja eikä toteuta VM:n tuotantointegraatiota.

Yksityiskohtainen tämän muutoksen testiraportti toimitetaan opettajan
kurssilähteen `CYBERWATCH_REVIEW.md`-tiedostossa. Repositorion vanhat
`RELEASE_STATUS.md` ja `docs/evidence` kuvaavat niihin kirjattuja aiempia ajoja,
eivätkä korvaa kurssitäydennyksen tarkistuksia. Paketin tarkat tiedostotiivisteet
ja GitHubissa julkaistun version päälle tehdyt muutokset löytyvät kurssilähteen
pakettiraportista ja patch-tiedostosta.

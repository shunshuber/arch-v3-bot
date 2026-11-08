"""Batch-validate Gmail app-password logins (IMAP)."""
import imaplib
import ssl
import sys
import io
import os
from concurrent.futures import ThreadPoolExecutor

SENDERS = {
	"snossigma@gmail.com": "tozk zdns btfc osfw",
	"awobayucel368@gmail.com": "gbfm kgso aslb vsmi",
	"uhiduma149@gmail.com": "sunx dnsc djej qgfn",
	"kellerosmynd@gmail.com": "dtvkvxkpkrtbpawi",
	"darenhanfyniag@gmail.com": "lvjy kywf aofa dmjp",
	"oyevajug91@gmail.com": "ziea dntc riuc czhs",
	"aqenufujeba21@gmail.com": "lplu btvj eknu blyx",
	"ufajiyuy96@gmail.com": "bzek kkwf bjwe avxi",
	"wuxojonoz52@gmail.com": "tqdj hecd vbsv gszz",
	"misha28272727@gmail.com": "kgwqxvkgjyccibkm",
	"jshevdydiwnww@gmail.com": "olfc uhan drkz lptn",
	"capersshawnkfvig@gmail.com": "ssmw vbnj uczh lvlo",
	"brenaurquhar834@gmail.com": "bhcfucpdqinujzzm",
	"changibrahimafumcsv@gmail.com": "yaoz jngg zzzi qfnc",
	"posnos088@gmail.com": "yukn oqby dria intr",
	"weaverebukagvsgye@gmail.com": "elkg lnuc nruv pulg",
	"edmondsjeffersxjn@gmail.com": "vidc jfhp peky zjwr",
	"bondingboasew@gmail.com": "ikgtyjtkjkehmjsi",
	"tsimshianhoming@gmail.com": "uztratzommnsjnqs",
	"ozoloko523@gmail.com": "qnek owrj oplx nxwg",
	"maksimafanacefish@gmail.com": "hdpn tbfp acwv jyro",
	"nikitaefremovvv1@gmail.com": "rruo rdhr ffdo ccum",
	"yefrieliminatorfepsg@gmail.com": "soyf xzdf ijda uonv",
	"missieletulled128@gmail.com": "mnymjjfjxaxyomrn",
	"pidraslox@gmail.com": "bqgb bfow uxgm sgtq",
	"tuasonbasilkqubx@gmail.com": "ntpo fomp pjbj wlon",
	"muecasfalcaorzbqd@gmail.com": "mqbf vnjc qhgb lzaj",
	"zqpterodaktelb@gmail.com": "dhev yhbz pwlp tgjq",
	"goudysrinivasmewhr@gmail.com": "iyuz tylx nmnl fzgm",
	"dlatt6677@gmail.com": "usun ruef otzx zcrh",
	"magauor05@gmail.com": "zzifsqvahkgrkivv",
	"nazarkoksov@gmail.com": "hgoh bpmu gdbj qnho",
	"xneokskurator@gmail.com": "okpj fuir hogn tszy",
	"chpnepalstunr@gmail.com": "wfue rqta amlt ypfl",
	"wendyechanonatxd@gmail.com": "xiijwnggabwljwpp",
	"rajheemxiongojpheu@gmail.com": "bate xeih akxr xopx",
	"funderburgadelsongsog@gmail.com": "qoaz adec guxp rhxr",
	"storrsisyansdy@gmail.com": "zuiy ppmz isar gjui",
	"dellapreston50@gmail.com": "qoit huon rzsd eewo",
	"segapro72@gmail.com": "ubmq pbrt ujqy orhf",
	"kurokopotok@gmail.com": "pxww ewut uffz ufpu",
	"prosega211@gmail.com": "fnrz rkrp nrwy yaig",
	"miranovseverov@gmail.com": "kdbc vmdb djxf pmiq",
	"artemkrotisov@gmail.com": "zglw vgak tfov uxao",
	"Vanakrotisov@gmail.com": "gukl qhxy uxea yhil",
	"leravladimir237@gmail.com": "ndon fzio vskk bidt",
	"suckdick12345222@gmail.com": "ckcw eqdv nsjv whgm",
	"alenaveterov@gmail.com": "hmiq xwmr yfmw prsa",
	"linadurov@gmail.com": "gsbp xyts brbu dlpw",
	"kolyaivanov000k@gmail.com": "mfhg eeio ayau zked",
	"edittendo0@gmail.com": "mzdl lrmx puyq epur",
	"shshsbsbsbwbwvw@gmail.com": "jqrx qivo qxjy jejt",
	"IvanKarma2000@gmail.com": "irlr cggo xksq tlbb",
	"trevorzxasuniga214@gmail.com": "egnr eucw jvxg jatq",
	"neilfdhioley765@gmail.com": "rgco uwiy qrdc gvqh",
	"samuelmnjassey32@gmail.com": "lgct cjiw nufr zxjg",
	"kalievutub@gmail.com": "jlwb otxo mppi jvdh",
	"snosakka07@gmail.com": "yiro khva gafc lujr",
	"qwaerlarp@gmail.com": "zrzx siyf ukvm ctjp",
	"segatel093@gmail.com": "fsma qetz gvmp pqrm",
	"irina15815123@gmail.com": "fmre mxne ncaw gnke",
	"germanalexandrovich12345678@gmail.com": "tsln hvmz mipp kmwh",
	"bl89222099674@gmail.com": "yjru yftj zihu nyrz",
	"psega0892@gmail.com": "vhrr hiso npgm xnoi",
	"noakk1843@gmail.com": "mvqo rfrv cjht vppo",
	"tatanamorinskaa@gmail.com": "cjig kaxt tijl ndre",
	"ivanplutalov543@gmail.com": "xsvm ewki dhfz qqkh",
	"editt1345@gmail.com": "hezf xuel hzvz jzur",
	"dlatt7055@gmail.com": "tpzd nxle odaw uqwf",
	"dlyabravla655@gmail.com": "kprn ihvr bgia vdys",
	"allisonikse1922@gmail.com": "tozo xrzu qndn mwuq",
	"Ivan27727272hwhs@gmail.com": "ozcu edfd gmgk rkqg",
	"Sckykatwo@gmail.com": "dblx ajll ugku ogpx",
	"d77666742@gmail.com": "alze kfmx xaem jogm",
	"deg411025@gmail.com": "pccl aleu earc aewn",
	"spamemailfree1@gmail.com": "uzvr iykl eiab rvqm",
	"sczdsv@gmail.com": "sdjt wbbr mglv obil",
	"osutokudu06@gmail.com": "gscs ztmn suqx nnsb",
	"ezezeludaz27@gmail.com": "ofxg arpz brcd pyip",
	"cnkstraz@gmail.com": "zcpe hdbi ujao bron",
	"ofag59111@gmail.com": "xmnx ijya yxvr wamo",
	"snosdark@gmail.com": "yajs rvin aqsw btfv",
	"34pashagei228@gmail.com": "xctb krbh xhpq rzae",
	"pashageimazahist@gmail.com": "edzp fxeq dkww wyyc",
	"snosertg@gmail.com": "xlvl yckq xxpd cidh",
	"krabiksigma7@gmail.com": "kpkh jyzz zifi umxe",
	"andraser93@gmail.com": "jftf eqdt tbdo chxh",
	"artistzxkakk@gmail.com": "hpxg zmti cwlx svar",
	"v89740130@gmail.com": "wzrg rgxb ddqx fidp",
	"vasyapetkin132@gmail.com": "bflk peqq sorn gfsp",
	"genadijklimak@gmail.com": "tbvu xdiw ppuv bqbp",
	"annnoraleidingbr57@gmail.com": "desnidcbrzkekuby",
	"rokmomnoncnm@gmail.com": "lgxrqtglkpulfupn",
	"sharonmenascer@gmail.com": "yupfvclgvyrrkyzt",
	"erotexen89@gmail.com": "ruzj ydkt erfz mkhy",
	"wovonunepo107@gmail.com": "twxe takt blju zvjt",
	"oficuhu591@gmail.com": "lrtb gjiz tawx qtse",
	"m70013953@gmail.com": "lyfmhqcoxdajfubq",
	"alivalijonovich5@gmail.com": "fnyboinhhsbddkqo",
	"sureshkaylorqvmf@gmail.com": "kgru juxz cbre ryqz",
	"popaseveloqqpmn@gmail.com": "kuba heor kkev vtnd",
	"jeffersastudillomalmkx@gmail.com": "itsm ywxt jowf bvsh",
	"moisesmarxmillerprtoym@gmail.com": "bzim qbxg atdl mvqz",
	"richardsoncrownvbskc@gmail.com": "kyqg ymvs qiku zsjt",
	"pewittvinceoobxe@gmail.com": "xwxn uxod tdiq ltxv",
	"piersonpremujiavy@gmail.com": "balu rlwc uucn rtvl",
	"tregoningantonyubhfup@gmail.com": "kuzq ozqm spjh ewsu",
	"marlohabbanifnkvu@gmail.com": "kalh brnn koln sfbp",
	"horowitzprinceglksr@gmail.com": "rvav kfxw nvdq jepl",
	"schroetersakurafbpe@gmail.com": "zgze gmrh lpoa ecbx",
	"nevorovatt2@gmail.com": "rrtj gafh wchj rkhb",
	"xxhowsq@gmail.com": "fcmm adeq oato gjon",
	"cotiktyn@gmail.com": "rhko oxey zpio nmsr",
	"arinacringe@gmail.com": "jkwa ewdm vjpe mgxo",
	"vinnieflood0@gmail.com": "blpx uyyk izjt bihj",
	"specevoid@gmail.com": "zgiz ebkz lgld ohxe",
}

HOST = "imap.gmail.com"
PORT = 993

CTX = ssl.create_default_context()


def check(entry):
    email, pwd = entry
    pwd_clean = pwd.replace(" ", "").strip()
    client = None
    try:
        client = imaplib.IMAP4_SSL(HOST, PORT, ssl_context=CTX)
        try:
            client.login(email, pwd_clean)
            code, _ = client.select("INBOX", readonly=True)
            status = "OK" if code == "OK" else "OK(no-inbox)"
            return (email, status, "")
        except imaplib.IMAP4.error as e:
            msg = str(e).strip()
            if "AUTHENTICATIONFAILED" in msg.upper():
                return (email, "FAIL", "wrong creds")
            if "LOCKED" in msg.upper():
                return (email, "LOCKED", msg)
            return (email, "FAIL", msg[:80])
        except Exception as e:
            return (email, "ERR", f"{type(e).__name__}:{e}"[:80])
        finally:
            try:
                client.logout()
            except Exception:
                pass
    except Exception as e:
        return (email, "CONN", f"{type(e).__name__}:{e}"[:80])


def main():
    # prefer env-injected credentials (used on GH Actions)
    env_creds = os.environ.get("CREDS_LIST", "").strip()
    if env_creds:
        uniq = {}
        for line in env_creds.splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            em, pw = line.split("|", 1)
            uniq[em.strip()] = pw.replace(" ", "").strip()
        sys.stdout.reconfigure(encoding="utf-8")
        print(f"checking {len(uniq)} unique accounts (from env)...")
    else:
        uniq = {}
        for k, v in SENDERS.items():
            k = k.strip()
            if k not in uniq:
                uniq[k] = v.replace(" ", "").strip()
        sys.stdout.reconfigure(encoding="utf-8")
        print(f"checking {len(uniq)} unique accounts...")
    results = []
    with ThreadPoolExecutor(max_workers=15) as ex:
        for row in ex.map(check, uniq.items()):
            results.append(row)
            mark = {"OK": "✅", "FAIL": "❌", "LOCKED": "🔒", "ERR": "⚠", "CONN": "🌐"}.get(row[1], "?")
            print(f"{mark} {row[0]:<48} {row[1]:<7} {row[2]}")

    ok = [r for r in results if r[1] == "OK" or r[1] == "OK(no-inbox)"]
    fail = [r for r in results if r[1] == "FAIL"]
    other = [r for r in results if r[1] not in ("OK", "OK(no-inbox)", "FAIL")]

    print("\n===== SUMMARY =====")
    print(f"valid: {len(ok)}   fail: {len(fail)}   other: {len(other)}")

    with io.open("valid_accounts.txt", "w", encoding="utf-8") as f:
        for email, _, _ in ok:
            f.write(f"{email}|{uniq[email]}\n")
    print("valid accounts -> valid_accounts.txt")

    with io.open("fail_accounts.txt", "w", encoding="utf-8") as f:
        for email, s, reason in fail + other:
            f.write(f"{email}|{uniq[email]}|{s}|{reason}\n")
    print("failed accounts -> fail_accounts.txt")


if __name__ == "__main__":
    main()

"""Arch V3 | report_texts.py — пул текстов жалоб (перенос из Brown V2).

GENERAL_TEXTS — общий пул RU/EN (дословно из Brown V2 report_texts.py);
CATEGORY_TEXTS — категории, собранные из текстов Brown V2 (channel-набор,
8 реплик на причину). Mail-метод берёт CATEGORY_TEXTS/GENERAL_TEXTS,
канал-метод — get_random_text (категория + общий пул, как в Brown).
"""
import random

# ─── общий пул (дословно из Brown V2) ────────────────────
GENERAL_TEXTS = [
    "Прошу заблокировать этого пользователя за нарушения.",
    "Заблокируйте, пожалуйста, этого пользователя. Он нарушает правила.",
    "Необходимо заблокировать данного пользователя.",
    "Этот пользователь должен быть заблокирован из-за нарушений.",
    "Просьба заблокировать аккаунт этого пользователя.",
    "Я прошу заблокировать этого пользователя в связи с нарушениями.",
    "Заблокируйте, пожалуйста, этого пользователя за нарушение правил.",
    "Этот пользователь явно нарушает правила, его нужно заблокировать.",
    "Пожалуйста, заблокируйте этого пользователя.",
    "Требую блокировки этого пользователя за нарушения.",
    "Заблокируйте этого пользователя за его действия.",
    "Считаю необходимым заблокировать этого пользователя.",
    "Этот пользователь не соблюдает правила, нужна блокировка.",
    "Заблокируйте, пожалуйста, пользователя, который нарушил правила.",
    "Прошу принять меры и заблокировать этого пользователя.",
    "Заблокируйте данного пользователя, он нарушает порядок.",
    "Этот аккаунт следует заблокировать за нарушения.",
    "Необходимо заблокировать этого пользователя за несоблюдение правил.",
    "Я настаиваю на блокировке этого пользователя.",
    "Прошу вас заблокировать этого пользователя за его поведение.",
    "Этот пользователь должен быть заблокирован немедленно.",
    "Прошу заблокировать этого пользователя, он нарушил правила.",
    "Нужно заблокировать этого пользователя.",
    "Данный пользователь заслуживает блокировки.",
    "Заблокируйте, пожалуйста, этого пользователя за нарушение.",
    "Этот пользователь ведет себя недопустимо, его надо заблокировать.",
    "Просьба о блокировке этого пользователя в связи с нарушениями.",
    "Этот пользователь явно не соблюдает правила, нужна блокировка.",
    "Пользователя нужно заблокировать, он нарушил порядок.",
    "Я прошу принять меры и заблокировать этого пользователя.",
    "Заблокируйте, пожалуйста, аккаунт данного пользователя.",
    "Необходимо заблокировать этого пользователя в связи с нарушениями.",
    "Этот пользователь должен быть заблокирован за свои действия.",
    "Прошу заблокировать этого пользователя за его поведение.",
    "Заблокируйте этого пользователя, он нарушает правила сообщества.",
    "Считаю, что этого пользователя нужно заблокировать.",
    "Этот пользователь заслужил блокировку.",
    "Прошу заблокировать этого пользователя в кратчайшие сроки.",
    "Пользователь явно нарушает правила, нужна блокировка.",
    "Требую заблокировать этого пользователя немедленно.",
    "Просьба заблокировать пользователя, нарушившего правила.",
    "Этот пользователь нуждается в блокировке за свои нарушения.",
    "Заблокируйте этого пользователя за некорректное поведение.",
    "Прошу заблокировать этого пользователя из-за нарушения.",
    "Этот пользователь не соблюдает правила, заблокируйте его.",
    "Необходимо принять меры и заблокировать этого пользователя.",
    "Пользователь нарушает правила. Прошу принять меры.",
    "Прошу о блокировке аккаунта за неоднократные нарушения.",
    "Пользователь ведет себя неподобающе. Прошу заблокировать.",
    "Прошу заблокировать за нарушения в чате.",
    "Пользователь нарушает правила сообщества. Прошу о блокировке.",
    "Прошу принять меры против пользователя за нарушения.",
    "Пользователь не соблюдает правила. Прошу заблокировать.",
    "Прошу о блокировке аккаунта за неподобающее поведение.",
    "Пользователь нарушает правила. Прошу заблокировать его.",
    "Прошу заблокировать за неоднократные нарушения.",
    "Пользователь ведет себя агрессивно. Прошу о блокировке.",
    "Прошу о блокировке пользователя за нарушения.",
    "Пользователь создает проблемы в чате. Прошу заблокировать.",
    "Прошу принять меры против пользователя.",
    "Пользователь нарушает правила общения. Прошу о блокировке.",
    "Прошу заблокировать за неподобающее поведение.",
    "Пользователь не соблюдает правила. Прошу принять меры.",
    "Прошу о блокировке аккаунта за нарушения.",
    "Пользователь ведет себя неуместно. Прошу заблокировать.",
    "Прошу заблокировать за нарушения в группе.",
    "Пользователь создает негативную атмосферу. Прошу о блокировке.",
    "Прошу о блокировке пользователя за неподобающее поведение.",
    # EN
    "Please block this user for violations.",
    "Please block this user. He's breaking the rules.",
    "This user must be blocked.",
    "This user should be blocked due to violations.",
    "Please block this user's account.",
    "I ask you to block this user due to violations.",
    "Please block this user for violating the rules.",
    "This user is clearly violating the rules, and he needs to be blocked.",
    "Please block this user.",
    "I demand that this user be blocked for violations.",
    "Block this user for his actions.",
    "I consider it necessary to block this user.",
    "This user does not follow the rules, and they need to be blocked.",
    "Please block the user who violated the rules.",
    "Please take action and block this user.",
    "Block this user, he breaks the order.",
    "This account should be blocked for violations.",
    "It is necessary to block this user for non-compliance with the rules.",
    "I insist on blocking this user.",
    "I ask you to block this user for his behavior.",
    "This user should be blocked immediately.",
    "Please block this user, he violated the rules.",
    "You need to block this user.",
    "This user deserves to be blocked.",
    "Please block this user for violation.",
    "This user is behaving unacceptably, he should be blocked.",
    "Request to block this user due to violations.",
    "This user is clearly not following the rules, and they need to be blocked.",
    "The user needs to be blocked, he has violated the order.",
    "I ask you to take action and block this user.",
    "It is necessary to block this user due to violations.",
    "This user should be blocked for their actions.",
    "Block this user, he is violating the rules of the community.",
    "I think this user should be blocked.",
    "Please block this user as soon as possible.",
    "The user is clearly violating the rules, and they need to be blocked.",
    "I demand to block this user immediately.",
    "Please block the user who violated the rules.",
    "This user needs to be blocked for his violations.",
    "Block this user for inappropriate behavior.",
    "Please block this user due to a violation.",
    "This user does not follow the rules, block him.",
    "It is necessary to take measures and block this user.",
    "I'm asking you to block this user.",
    "I ask you to block the user for violating the rules.",
]

# ─── категории (дословно из Brown V2 channel_snos.py) ────
SPAM = [
    "Канал распространяет массовый спам и мошеннические предложения. Прошу заблокировать.",
    "This channel distributes mass spam and fraudulent offers. Please block immediately.",
    "Канал рассылает спам-контент и обманывает пользователей. Требую блокировки.",
    "Channel is spreading spam and scam content to users. Immediate block required.",
    "Канал нарушает правила Telegram: массовый спам и мошенничество. Прошу разобраться.",
    "This channel violates Telegram ToS through mass spam and fraud. Please block.",
    "Канал используется для распространения спама и фишинга. Прошу заблокировать.",
    "Channel conducts phishing and spam campaigns against users. Block required.",
]

VIOLENCE = [
    "Канал публикует контент, пропагандирующий насилие и призывающий к жестокости. Прошу заблокировать.",
    "This channel promotes violence and incites users to commit violent acts. Please block.",
    "Канал распространяет материалы, пропагандирующие насилие и экстремизм. Требую блокировки.",
    "Channel spreads violent content and extremist propaganda. Immediate block required.",
    "Канал публикует призывы к насилию и жестокие материалы. Прошу принять меры.",
    "This channel incites violence and distributes harmful extremist content. Please block.",
    "Канал нарушает ToS Telegram: пропаганда насилия и жестокости. Прошу заблокировать.",
    "Channel violates Telegram ToS by promoting violence and extremism. Block required.",
]

CHILD = [
    "Канал содержит и распространяет незаконный контент с несовершеннолетними. Требую блокировки.",
    "This channel distributes illegal content involving minors (CSAM). Block immediately.",
    "Канал публикует материалы сексуального насилия над детьми. Требую экстренной блокировки.",
    "Channel contains child sexual abuse material. Urgent block and report to authorities.",
    "Канал распространяет незаконный контент с участием детей. Это уголовно наказуемо. Заблокируйте.",
    "This channel spreads illegal CSAM content. Immediate removal and block required.",
    "Канал содержит детскую порнографию. Требую немедленного удаления и блокировки.",
    "Channel distributes child abuse material violating international law. Block immediately.",
]

PORN = [
    "Канал распространяет порнографический контент без верификации возраста. Прошу заблокировать.",
    "This channel distributes explicit adult content without age verification. Please block.",
    "Канал публикует контент 18+ без проверки возраста подписчиков. Требую блокировки.",
    "Channel posts pornographic material without age gates or consent. Immediate block needed.",
    "Канал рассылает неприемлемый контент для взрослых без ограничений. Прошу принять меры.",
    "This channel spreads adult content without age verification violating ToS. Please block.",
    "Канал нарушает ToS Telegram: публикует порнографию без верификации. Прошу заблокировать.",
    "Channel violates Telegram ToS by distributing adult content without age checks. Block it.",
]

PERSONAL = [
    "Канал собирает и распространяет личные данные пользователей: ИНН, адреса, телефоны. Прошу заблокировать.",
    "This channel collects and distributes personal data: phone numbers, IDs, addresses. Please block.",
    "Канал публикует конфиденциальные данные пользователей без их согласия. Требую блокировки.",
    "Channel leaks private user data including phone numbers, home addresses and IDs. Block required.",
    "Канал незаконно распространяет персональные данные: паспорта, телефоны, адреса. Прошу заблокировать.",
    "This channel illegally distributes personal data: passports, phones, addresses. Please block.",
    "Канал публикует личные данные людей без согласия. Нарушает ToS. Прошу разобраться.",
    "Channel posts personal data of users without consent, violating Telegram ToS. Block it.",
]

OTHER = [
    "Канал систематически нарушает правила Telegram и ведёт мошенническую деятельность. Прошу заблокировать.",
    "This channel systematically violates Telegram ToS and engages in fraud. Please block.",
    "Канал нарушает правила платформы и причиняет вред пользователям. Требую блокировки.",
    "Channel breaks Telegram rules and harms users through repeated violations. Block needed.",
    "Канал ведёт незаконную деятельность и нарушает ToS Telegram. Прошу разобраться.",
    "This channel conducts illegal activities and violates Telegram Terms of Service. Block it.",
    "Канал систематически нарушает правила и используется для обмана. Прошу заблокировать.",
    "Channel is used for systematic fraud and ToS violations. Immediate action required.",
]


CATEGORY_TEXTS = {
    "spam": SPAM,
    "sexwork": PORN,
    "fraud": SPAM,
    "violence": VIOLENCE,
    "child": CHILD,
    "porn": PORN,
    "copyright": OTHER,
    "drugs": OTHER,
    "personal": PERSONAL,
    "terrorism": VIOLENCE,
    "other": OTHER,
    "other_default": OTHER,
}


def get_random_text(reason_key: str = "") -> str:
    """Brown formula: category pool mixed with the general one."""
    texts = CATEGORY_TEXTS.get(reason_key, []) + GENERAL_TEXTS
    return random.choice(texts)


def get_mixed_texts(reason_key: str = "", count: int = 5) -> list[str]:
    """Brown get_mixed_texts: category + general, unique sample."""
    texts = CATEGORY_TEXTS.get(reason_key, []) + GENERAL_TEXTS
    return random.sample(texts, min(count, len(texts)))

import json
import os

MODE_ORDER = ["leicht", "mittel", "schwer"]


def build_mode(description, question_builder):
    return {"description": description, "questions": question_builder()[:100]}


# ---------- Mathematics ----------

def arithmetic_questions(mode):
    questions = []
    for a in range(1, 60):
        b = a + (mode == "leicht" and 2 or 3)
        questions.append({"frage": f"Was ergibt {a} + {b}?", "antwort": str(a + b)})
        if mode != "leicht":
            questions.append({"frage": f"Subtrahiere {a} von {a + b}", "antwort": str(b)})
        if len(questions) >= 120:
            break
    for a in range(10, 110):
        if len(questions) >= 200:
            break
        questions.append({"frage": f"Wie viel ergibt {a + 5} - {5}?", "antwort": str(a)},)
    return questions


def multiplication_questions(mode):
    questions = []
    start = 2 if mode == "leicht" else 5 if mode == "mittel" else 8
    end = 12 if mode == "leicht" else 20 if mode == "mittel" else 26
    for a in range(start, end):
        for b in range(start, end):
            questions.append({"frage": f"Wieviel ist {a} mal {b}?", "antwort": str(a * b)})
            if len(questions) >= 200:
                break
        if len(questions) >= 200:
            break
    return questions


def division_questions(mode):
    questions = []
    start = 2 if mode == "leicht" else 3 if mode == "mittel" else 4
    end = 12 if mode == "leicht" else 18 if mode == "mittel" else 26
    for a in range(start, end):
        for b in range(start, end):
            questions.append({"frage": f"Wie viel ergibt {a * b} geteilt durch {b}?", "antwort": str(a)})
            if len(questions) >= 200:
                break
        if len(questions) >= 200:
            break
    return questions


def equation_questions(mode):
    questions = []
    for x in range(2, 40 if mode == "leicht" else 60 if mode == "mittel" else 80):
        questions.append({"frage": f"Löse: {x}x - {x} = {x * (x - 1)}", "antwort": str(x)})
        questions.append({"frage": f"Löse: 3x + {x} = {4 * x}", "antwort": str(x)})
        if len(questions) >= 200:
            break
    return questions


def generate_math():
    return {
        "Arithmetik": {
            "modes": {
                "leicht": build_mode("Schnelles Addieren und Subtrahieren kleiner Zahlen.", lambda: arithmetic_questions("leicht")),
                "mittel": build_mode("Zweistellige Summen, Differenzen und Gruppierungen.", lambda: arithmetic_questions("mittel")),
                "schwer": build_mode("Multi-Schritt-Rechnungen für Fortgeschrittene.", lambda: arithmetic_questions("schwer")),
            }
        },
        "Multiplikation": {
            "modes": {
                "leicht": build_mode("Kleine Einmaleins-Aufgaben ohne Dezimalstellen.", lambda: multiplication_questions("leicht")),
                "mittel": build_mode("Doppelte Einmaleins- und Faktoren bis 20.", lambda: multiplication_questions("mittel")),
                "schwer": build_mode("Faktoren bis 25 + Kombinationsaufgaben.", lambda: multiplication_questions("schwer")),
            }
        },
        "Division": {
            "modes": {
                "leicht": build_mode("Ganzzahlige Divisionen mit kleinen Zahlen.", lambda: division_questions("leicht")),
                "mittel": build_mode("Divisionen mit zweistelligen Zahlen.", lambda: division_questions("mittel")),
                "schwer": build_mode("Mehrstellige Divisionen ohne Rest.", lambda: division_questions("schwer")),
            }
        },
        "Gleichungen": {
            "modes": {
                "leicht": build_mode("Lineare Gleichungen mit einem einfachen Schritt.", lambda: equation_questions("leicht")),
                "mittel": build_mode("Gleichungen mit mehreren Termen und Konstanten.", lambda: equation_questions("mittel")),
                "schwer": build_mode("Komplexe lineare Gleichungen und Umformungen.", lambda: equation_questions("schwer")),
            }
        },
    }


# ---------- Geography ----------

CAPITALS = [
    {"country": "Frankreich", "answer": "Paris"},
    {"country": "Spanien", "answer": "Madrid"},
    {"country": "Italien", "answer": "Rom"},
    {"country": "Österreich", "answer": "Wien"},
    {"country": "Schweiz", "answer": "Bern"},
    {"country": "Portugal", "answer": "Lissabon"},
    {"country": "Belgien", "answer": "Brüssel"},
    {"country": "Niederlande", "answer": "Amsterdam"},
    {"country": "Polen", "answer": "Warschau"},
    {"country": "Ungarn", "answer": "Budapest"},
    {"country": "Tschechien", "answer": "Prag"},
    {"country": "Norwegen", "answer": "Oslo"},
    {"country": "Kroatien", "answer": "Zagreb"},
    {"country": "Rumänien", "answer": "Bukarest"},
    {"country": "Bulgarien", "answer": "Sofia"},
    {"country": "Russland", "answer": "Moskau"},
    {"country": "Kanada", "answer": "Ottawa"},
    {"country": "Brasilien", "answer": "Brasília"},
    {"country": "Argentinien", "answer": "Buenos Aires"},
    {"country": "Japan", "answer": "Tokio"},
    {"country": "China", "answer": "Peking"},
    {"country": "Indien", "answer": "Neu-Delhi"},
    {"country": "Australien", "answer": "Canberra"},
    {"country": "Ägypten", "answer": "Kairo"},
    {"country": "Südafrika", "answer": "Pretoria"},
    {"country": "Marokko", "answer": "Rabat"},
]

RIVERS = [
    {"river": "Nil", "country": "Ägypten"},
    {"river": "Donau", "country": "Österreich"},
    {"river": "Rhein", "country": "Deutschland"},
    {"river": "Thames", "country": "England"},
    {"river": "Amazonas", "country": "Brasilien"},
    {"river": "Yangtze", "country": "China"},
    {"river": "Ganges", "country": "Indien"},
    {"river": "Mekong", "country": "Vietnam"},
    {"river": "Volga", "country": "Russland"},
    {"river": "Euphrat", "country": "Syrien"},
    {"river": "Tigris", "country": "Irak"},
    {"river": "Seine", "country": "Frankreich"},
    {"river": "Elbe", "country": "Deutschland"},
    {"river": "Hudson", "country": "USA"},
    {"river": "Loire", "country": "Frankreich"},
    {"river": "Orinoco", "country": "Venezuela"},
]

MOUNTAINS = [
    {"mountain": "Zugspitze", "country": "Deutschland"},
    {"mountain": "Matterhorn", "country": "Schweiz"},
    {"mountain": "Mont Blanc", "country": "Frankreich"},
    {"mountain": "Kilimandscharo", "country": "Tansania"},
    {"mountain": "Denali", "country": "USA"},
    {"mountain": "Fuji", "country": "Japan"},
    {"mountain": "Mount Everest", "country": "Nepal"},
    {"mountain": "K2", "country": "Pakistan"},
    {"mountain": "Piz Buin", "country": "Österreich"},
    {"mountain": "Himalaya", "country": "Nepal"},
    {"mountain": "Anden", "country": "Chile"},
    {"mountain": "Rocky Mountains", "country": "Kanada"},
    {"mountain": "Drakensberge", "country": "Südafrika"},
    {"mountain": "Pindos", "country": "Griechenland"},
    {"mountain": "Apenninen", "country": "Italien"},
]

REGIONS = [
    {"region": "Skandinavien", "location": "Nordeuropa"},
    {"region": "Balkan", "location": "Südosteuropa"},
    {"region": "Kaukasus", "location": "Südwestasien"},
    {"region": "Sahara", "location": "Nordafrika"},
    {"region": "Kanarische Inseln", "location": "Atlantik"},
    {"region": "Lappland", "location": "Nordeuropa"},
    {"region": "Sizilien", "location": "Mittelmeer"},
    {"region": "Normandie", "location": "Frankreich"},
    {"region": "Provence", "location": "Frankreich"},
    {"region": "Toskana", "location": "Italien"},
    {"region": "Dalmatien", "location": "Adria"},
    {"region": "Korsika", "location": "Mittelmeer"},
    {"region": "Andalusien", "location": "Spanien"},
    {"region": "Rheinland", "location": "Deutschland"},
    {"region": "Sardinien", "location": "Mittelmeer"},
]


def build_question_set(entries, templates, limit=100, answer_key="answer"):
    questions = []
    for template in templates:
        template_text = template["text"] if isinstance(template, dict) else template
        template_answer_key = answer_key
        if isinstance(template, dict) and template.get("answer_key"):
            template_answer_key = template["answer_key"]
        for entry in entries:
            if len(questions) >= limit:
                return questions
            question_text = template_text.format(**entry)
            answer = entry.get(template_answer_key)
            if answer is None:
                for fallback_key in ["translation", "answer", "phrase", "word", "country", "river", "location"]:
                    if fallback_key == template_answer_key:
                        continue
                    fallback_value = entry.get(fallback_key)
                    if fallback_value:
                        answer = fallback_value
                        break
            if answer is None:
                answer = entry.get(answer_key)
            q = {"frage": question_text, "antwort": answer}
            if alias := entry.get("aliases"):
                q["aliases"] = alias
            questions.append(q)
    return questions


def generate_geografie():
    capital_templates = [
        "Was ist die Hauptstadt von {country}?",
        "Nenne die Landeshauptstadt von {country}.",
        "Was ist die größte Stadt und Hauptstadt von {country}?",
        "Kombiniere {country} mit seiner Hauptstadt: ",
        "Welche Stadt ist die politische Hauptstadt von {country}?",
    ]
    river_templates = [
        {"text": "Welcher Fluss fließt durch {country}?", "answer_key": "river"},
        {"text": "Nenne den Fluss, der {country} mit Wasser versorgt.", "answer_key": "river"},
        {"text": "Durch welches Land fließt der {river}?", "answer_key": "country"},
        {"text": "{river} verläuft durch welches Land?", "answer_key": "country"},
        {"text": "Welches Land gehört zum Fluss {river}?", "answer_key": "country"},
    ]
    mountain_templates = [
        {"text": "In welchem Land liegt {mountain}?", "answer_key": "country"},
        {"text": "{mountain} befindet sich in welchem Staat?", "answer_key": "country"},
        {"text": "Nenne das Land, in dem {mountain} steht.", "answer_key": "country"},
        {"text": "Welches Land umfasst {mountain}?", "answer_key": "country"},
        {"text": "{mountain} lässt sich auf welchem Kontinent finden?", "answer_key": "country"},
    ]
    region_templates = [
        {"text": "Zu welcher Gegend gehört {region}?", "answer_key": "location"},
        {"text": "{region} liegt in welcher Region?", "answer_key": "location"},
        {"text": "Nenne die Region von {region}.", "answer_key": "location"},
        {"text": "Welche übergeordnete Region beschreibt {region}?", "answer_key": "location"},
        {"text": "{region} ist Teil welcher größeren Region?", "answer_key": "location"},
    ]
    return {
        "Hauptstädte": {
            "modes": {
                "leicht": build_mode("Europa- und Welt-Hauptstädte", lambda: build_question_set(CAPITALS, capital_templates)),
                "mittel": build_mode("Hauptstädte plus Stadtnamen", lambda: build_question_set(CAPITALS, capital_templates + ["Nenne {country}s administrative Hauptstadt." ])),
                "schwer": build_mode("Weltweite Capitals & City-Paare", lambda: build_question_set(CAPITALS, capital_templates + ["Welche Hauptstadt gehört zu {country}?", "{country}: Hauptstadt?"])),
            }
        },
        "Flüsse": {
            "modes": {
                "leicht": build_mode("Bekannte Flüsse Europas", lambda: build_question_set(RIVERS, river_templates)),
                "mittel": build_mode(
                    "Flüsse und angrenzende Länder",
                    lambda: build_question_set(
                        RIVERS,
                        river_templates
                        + [
                            {"text": "{river} verbindet welches Land?", "answer_key": "country"},
                            {"text": "Nenne das Land zum Fluss {river}.", "answer_key": "country"},
                        ],
                    ),
                ),
                "schwer": build_mode(
                    "Kontinente und Entwässerungssysteme",
                    lambda: build_question_set(
                        RIVERS,
                        river_templates
                        + [
                            {"text": "{river} wird welchem Land zugeschrieben?", "answer_key": "country"},
                            {"text": "Welches Land besitzt {river}?", "answer_key": "country"},
                            {"text": "Nenne das Land, durch das {river} entwässert.", "answer_key": "country"},
                        ],
                    ),
                ),
            }
        },
        "Gebirge": {
            "modes": {
                "leicht": build_mode("Alpenregionen und bekannte Berge", lambda: build_question_set(MOUNTAINS, mountain_templates)),
                "mittel": build_mode(
                    "Berge mit umliegenden Staaten",
                    lambda: build_question_set(
                        MOUNTAINS,
                        mountain_templates
                        + [
                            {"text": "{mountain} steht in welchem Land?", "answer_key": "country"},
                            {"text": "Nenne das Land zu {mountain}.", "answer_key": "country"},
                        ],
                    ),
                ),
                "schwer": build_mode(
                    "Globale Gebirge & Länder",
                    lambda: build_question_set(
                        MOUNTAINS,
                        mountain_templates
                        + [
                            {"text": "Welches Land beherbergt {mountain}?", "answer_key": "country"},
                            {"text": "{mountain} befindet sich auf welchem Kontinent?", "answer_key": "country"},
                        ],
                    ),
                ),
            }
        },
        "Regionen": {
            "modes": {
                "leicht": build_mode("Regionen Europas und Nordafrikas", lambda: build_question_set(REGIONS, region_templates)),
                "mittel": build_mode(
                    "Regionen mit zusätzlichen Beschreibungen",
                    lambda: build_question_set(
                        REGIONS,
                        region_templates
                        + [
                            {"text": "{region} gehört zu welcher großen Region?", "answer_key": "location"},
                            {"text": "Nenne die Lage von {region}.", "answer_key": "location"},
                        ],
                    ),
                ),
                "schwer": build_mode(
                    "Regionen im Kontext von Staaten",
                    lambda: build_question_set(
                        REGIONS,
                        region_templates
                        + [
                            {"text": "{region} ist Teil von welchem geografischen Raum?", "answer_key": "location"},
                            {"text": "Welches Gebiet umfasst {region}?", "answer_key": "location"},
                            {"text": "In welchem Staat liegt {region}? ", "answer_key": "location"},
                        ],
                    ),
                ),
            }
        },
    }


# ---------- English ----------

ENGLISH_VOCAB = [
    {"word": "house", "translation": "Haus", "aliases": ["Wohnhaus"]},
    {"word": "school", "translation": "Schule", "aliases": ["Lehranstalt"]},
    {"word": "book", "translation": "Buch", "aliases": ["Lesestoff"]},
    {"word": "apple", "translation": "Apfel"},
    {"word": "friend", "translation": "Freund", "aliases": ["Kumpel"]},
    {"word": "music", "translation": "Musik"},
    {"word": "song", "translation": "Lied"},
    {"word": "movie", "translation": "Film", "aliases": ["Kinofilm"]},
    {"word": "sun", "translation": "Sonne"},
    {"word": "moon", "translation": "Mond"},
    {"word": "water", "translation": "Wasser"},
    {"word": "fire", "translation": "Feuer"},
    {"word": "cold", "translation": "kalt"},
    {"word": "hot", "translation": "heiß"},
    {"word": "laugh", "translation": "lachen"},
    {"word": "cry", "translation": "weinen"},
    {"word": "read", "translation": "lesen"},
    {"word": "write", "translation": "schreiben"},
    {"word": "run", "translation": "rennen", "aliases": ["laufen"]},
    {"word": "walk", "translation": "gehen"},
    {"word": "eat", "translation": "essen"},
    {"word": "drink", "translation": "trinken"},
    {"word": "learn", "translation": "lernen"},
    {"word": "teach", "translation": "unterrichten"},
    {"word": "question", "translation": "Frage"},
    {"word": "answer", "translation": "Antwort"},
    {"word": "color", "translation": "Farbe"},
    {"word": "family", "translation": "Familie"},
    {"word": "happy", "translation": "glücklich", "aliases": ["fröhlich"]},
]

VERBS = [
    {"word": "run", "translation": "rennen", "aliases": ["laufen"]},
    {"word": "jump", "translation": "springen"},
    {"word": "swim", "translation": "schwimmen"},
    {"word": "dance", "translation": "tanzen"},
    {"word": "sing", "translation": "singen"},
    {"word": "paint", "translation": "malen"},
    {"word": "write", "translation": "schreiben"},
    {"word": "read", "translation": "lesen"},
    {"word": "sleep", "translation": "schlafen"},
    {"word": "stand", "translation": "stehen"},
    {"word": "play", "translation": "spielen"},
    {"word": "think", "translation": "denken"},
    {"word": "build", "translation": "bauen"},
]

PHRASES = [
    {"phrase": "thank you", "translation": "Danke"},
    {"phrase": "please", "translation": "Bitte"},
    {"phrase": "good night", "translation": "Gute Nacht"},
    {"phrase": "excuse me", "translation": "Entschuldigung"},
    {"phrase": "I don't understand", "translation": "Ich verstehe nicht"},
    {"phrase": "see you later", "translation": "Bis später"},
    {"phrase": "how much is this?", "translation": "Was kostet das?"},
    {"phrase": "help", "translation": "Hilfe"},
    {"phrase": "I'm hungry", "translation": "Ich habe Hunger"},
    {"phrase": "I'm tired", "translation": "Ich bin müde"},
]

COLORS = [
    {"word": "blue", "translation": "blau"},
    {"word": "red", "translation": "rot"},
    {"word": "yellow", "translation": "gelb"},
    {"word": "green", "translation": "grün"},
    {"word": "pink", "translation": "rosa"},
    {"word": "orange", "translation": "orange"},
    {"word": "black", "translation": "schwarz"},
    {"word": "white", "translation": "weiß"},
    {"word": "purple", "translation": "lila"},
    {"word": "brown", "translation": "braun"},
]


ENGLISH_TEMPLATES = {
    "leicht": [
        {"text": "Was bedeutet '{word}' auf Deutsch?", "answer_key": "translation"},
        {"text": "Wie lautet '{translation}' auf Englisch?", "answer_key": "word"},
        {"text": "Nenne das englische Wort für '{translation}'.", "answer_key": "word"},
        {"text": "Wie sagt man '{translation}' in Englisch?", "answer_key": "word"},
        {"text": "{word} bedeutet auf Deutsch?", "answer_key": "translation"},
    ],
    "mittel": [
        {"text": "Welche Übersetzung passt zu '{translation}'?", "answer_key": "word"},
        {"text": "Wähle das englische Wort für '{translation}'.", "answer_key": "word"},
        {"text": "'{translation}' heißt im Englischen?", "answer_key": "word"},
        {"text": "Wie würdest du '{translation}' in einem Satz verwenden?", "answer_key": "word"},
        {"text": "Mit welchem englischen Wort beschreibst du '{translation}'?", "answer_key": "word"},
    ],
    "schwer": [
        {"text": "Finde das passende englische Wort für '{translation}'", "answer_key": "word"},
        {"text": "Welche englische Vokabel steht für '{translation}'?", "answer_key": "word"},
        {"text": "Wie lautet die englische Entsprechung von '{translation}' im Alltag?", "answer_key": "word"},
        {"text": "Translate '{translation}' into English.", "answer_key": "word"},
        {"text": "Nenne das Wort, das '{translation}' auf Englisch wiedergibt.", "answer_key": "word"},
    ],
}

VERB_TEMPLATES = {
    "leicht": [
        {"text": "Was bedeutet '{word}'?", "answer_key": "translation"},
        {"text": "Wie lautet '{translation}' auf Englisch?", "answer_key": "word"},
        {"text": "Nenne das Verb für '{translation}'.", "answer_key": "word"},
        {"text": "Was heißt '{translation}' auf Englisch?", "answer_key": "word"},
        {"text": "Übersetze '{translation}' als Verb.", "answer_key": "word"},
        {"text": "Wähle das passende Verb für '{translation}'.", "answer_key": "word"},
        {"text": "Wie lautet das Verb für '{translation}' im Satz?", "answer_key": "word"},
        {"text": "Übersetze '{translation}' in ein einfaches Verb.", "answer_key": "word"},
        {"text": "Welches Verb passt zu '{translation}'?", "answer_key": "word"},
    ],
    "mittel": [
        {"text": "Wähl das passende Verb für '{translation}'.", "answer_key": "word"},
        {"text": "Translate '{translation}' to English as a verb.", "answer_key": "word"},
        {"text": "Welche englische Handlung ist '{translation}'?", "answer_key": "word"},
        {"text": "Wie würdest du '{translation}' im Satz beschreiben?", "answer_key": "word"},
        {"text": "Welches Verb passt zu '{translation}'?", "answer_key": "word"},
        {"text": "Formuliere '{translation}' als englisches Verb.", "answer_key": "word"},
        {"text": "Welche Verbform entspricht '{translation}'?", "answer_key": "word"},
        {"text": "Wähle die passende englische Handlung für '{translation}'.", "answer_key": "word"},
        {"text": "Beschreibe '{translation}' mit einem englischen Verb.", "answer_key": "word"},
    ],
    "schwer": [
        {"text": "Wie lautet das englische Verb, das '{translation}' bedeutet?", "answer_key": "word"},
        {"text": "Finde die englische Form von '{translation}'.", "answer_key": "word"},
        {"text": "Nenne das Verb, das '{translation}' beschreibt.", "answer_key": "word"},
        {"text": "Welche englische Aktion steht für '{translation}'?", "answer_key": "word"},
        {"text": "Stelle '{translation}' als Verb dar.", "answer_key": "word"},
        {"text": "Wähle die passende Verbform für '{translation}'.", "answer_key": "word"},
        {"text": "Beschreibe '{translation}' mit einer komplexen Verbform.", "answer_key": "word"},
        {"text": "Finde das idiomatische Verb für '{translation}'.", "answer_key": "word"},
        {"text": "Welche Verbphrase beschreibt '{translation}' am besten?", "answer_key": "word"},
    ],
}

PHRASE_TEMPLATES = {
    "leicht": [
        {"text": "Wie sagt man '{translation}'?", "answer_key": "phrase"},
        {"text": "Was heißt '{translation}'?", "answer_key": "phrase"},
        {"text": "Nenne die Phrase für '{translation}'.", "answer_key": "phrase"},
        {"text": "Welche englische Wendung entspricht '{translation}'?", "answer_key": "phrase"},
        {"text": "Wie lautet '{translation}' auf Englisch?", "answer_key": "phrase"},
        {"text": "Translate '{translation}' to English.", "answer_key": "phrase"},
        {"text": "Wähle die passende Phrase für '{translation}'.", "answer_key": "phrase"},
        {"text": "Welche Redewendung steht für '{translation}'?", "answer_key": "phrase"},
        {"text": "Formuliere '{translation}' als englische Phrase.", "answer_key": "phrase"},
        {"text": "Nenne eine Alltagspause mit '{translation}'.", "answer_key": "phrase"},
        {"text": "Wie lautet '{translation}' in einem Gespräch?", "answer_key": "phrase"},
    ],
    "mittel": [
        {"text": "Translate '{translation}' into English.", "answer_key": "phrase"},
        {"text": "Welche Redewendung bedeutet '{translation}'?", "answer_key": "phrase"},
        {"text": "Wie würdest du '{translation}' ins Englische übertragen?", "answer_key": "phrase"},
        {"text": "Nenne eine englische Phrase für '{translation}'.", "answer_key": "phrase"},
        {"text": "Welche Englisch-Satzform passt zu '{translation}'?", "answer_key": "phrase"},
        {"text": "Stelle '{translation}' als englische Redewendung dar.", "answer_key": "phrase"},
        {"text": "Wähle eine höfliche Variante für '{translation}'?", "answer_key": "phrase"},
        {"text": "Wie klingt '{translation}' im britischen Englisch?", "answer_key": "phrase"},
        {"text": "Welche Phrase ersetzt '{translation}' im Alltag?", "answer_key": "phrase"},
        {"text": "Beschreibe '{translation}' mit einer englischen Wendung.", "answer_key": "phrase"},
        {"text": "Gibt es eine umgangssprachliche Phrase für '{translation}'?", "answer_key": "phrase"},
    ],
    "schwer": [
        {"text": "Wähle die passende englische Phrase für '{translation}'?", "answer_key": "phrase"},
        {"text": "Wie lautet '{translation}' in Alltagssprache?", "answer_key": "phrase"},
        {"text": "Welche idiomatische Form beschreibt '{translation}'?", "answer_key": "phrase"},
        {"text": "Translate '{translation}' to a colloquial English phrase.", "answer_key": "phrase"},
        {"text": "Welche Redewendung trifft auf '{translation}' zu?", "answer_key": "phrase"},
        {"text": "Wie würdest du '{translation}' im Dialog sagen?", "answer_key": "phrase"},
        {"text": "Erkläre '{translation}' mit einer englischen Expression.", "answer_key": "phrase"},
        {"text": "Wie klingt '{translation}' in einem idiomatischen Satz?", "answer_key": "phrase"},
        {"text": "Nenne eine farbige Phrase für '{translation}'.", "answer_key": "phrase"},
        {"text": "Welche englische Wendung ist synonym zu '{translation}'?", "answer_key": "phrase"},
        {"text": "Setze '{translation}' in eine englische Redewendung ein.", "answer_key": "phrase"},
    ],
}
COLOR_TEMPLATES = {
    "leicht": [
        {"text": "Wie heißt '{translation}' auf Englisch?", "answer_key": "word"},
        {"text": "Nenne die Farbe '{translation}' auf Englisch.", "answer_key": "word"},
        {"text": "Translate '{translation}' to an English color.", "answer_key": "word"},
        {"text": "Welche Farbe beschreibt '{translation}'?", "answer_key": "word"},
        {"text": "Wie lautet '{translation}' auf Englisch?", "answer_key": "word"},
        {"text": "Wie nennt man '{translation}' im Englischen?", "answer_key": "word"},
        {"text": "In welcher Farbe wird '{translation}' dargestellt?", "answer_key": "word"},
        {"text": "Wähle den englischen Farbton für '{translation}'.", "answer_key": "word"},
        {"text": "Welche Farbe entspricht '{translation}'?", "answer_key": "word"},
        {"text": "Wie übersetzt du '{translation}' auf Englisch?", "answer_key": "word"},
    ],
    "mittel": [
        {"text": "Welche englische Farbe beschreibt '{translation}'?", "answer_key": "word"},
        {"text": "Translate '{translation}' to an English color.", "answer_key": "word"},
        {"text": "Nenne die englische Color-Bezeichnung für '{translation}'.", "answer_key": "word"},
        {"text": "Wie würdest du '{translation}' im Design auf Englisch nennen?", "answer_key": "word"},
        {"text": "Welche Farbname passt zu '{translation}'?", "answer_key": "word"},
        {"text": "Wie lautet die englische Bezeichnung von '{translation}'?", "answer_key": "word"},
        {"text": "Welche Nuance beschreibt '{translation}'?", "answer_key": "word"},
        {"text": "Nenne den englischen Farbton, der '{translation}' entspricht.", "answer_key": "word"},
        {"text": "Welche englische Farbe würdest du wählen für '{translation}'?", "answer_key": "word"},
        {"text": "Wie heißt '{translation}' als englische Color-Definition?", "answer_key": "word"},
    ],
    "schwer": [
        {"text": "Wie lautet die englische Bezeichnung von '{translation}' im Design?", "answer_key": "word"},
        {"text": "Nenne die englische Farbe, die '{translation}' entspricht.", "answer_key": "word"},
        {"text": "Translate '{translation}' into a descriptive English color.", "answer_key": "word"},
        {"text": "Welche englische Nuance ist '{translation}'?", "answer_key": "word"},
        {"text": "Wie würdest du '{translation}' stilvoll auf Englisch beschreiben?", "answer_key": "word"},
        {"text": "Wähle die passende Farbnuance für '{translation}'.", "answer_key": "word"},
        {"text": "Welche englische Farbterm eignet sich für '{translation}'?", "answer_key": "word"},
        {"text": "Beschreibe '{translation}' im englischen Design-Sprachgebrauch.", "answer_key": "word"},
        {"text": "Nenne die englische Farbbezeichnung für '{translation}'.", "answer_key": "word"},
        {"text": "Wie lauten die englischen Hex-Notizen zu '{translation}'?", "answer_key": "word"},
    ],
}


def generate_english():
    return {
        "Grundwortschatz": {
            "modes": {
                mode: build_mode(
                    f"Grundwortschatz: {mode.title()}",
                    lambda mode=mode: build_question_set(ENGLISH_VOCAB, ENGLISH_TEMPLATES[mode]),
                )
                for mode in MODE_ORDER
            }
        },
        "Verben": {
            "modes": {
                mode: build_mode(
                    f"Verbenmodus: {mode.title()}",
                    lambda mode=mode: build_question_set(VERBS, VERB_TEMPLATES[mode]),
                )
                for mode in MODE_ORDER
            }
        },
        "Phrasen": {
            "modes": {
                mode: build_mode(
                    f"Redewendungen: {mode.title()}",
                    lambda mode=mode: build_question_set(PHRASES, PHRASE_TEMPLATES[mode], answer_key="phrase"),
                )
                for mode in MODE_ORDER
            }
        },
        "Farben": {
            "modes": {
                mode: build_mode(
                    f"Farbmodus: {mode.title()}",
                    lambda mode=mode: build_question_set(COLORS, COLOR_TEMPLATES[mode]),
                )
                for mode in MODE_ORDER
            }
        },
    }



# ---------- History ----------

HISTORY_DATA = {
    "Deutschland": [
        {"answer": "Konrad Adenauer", "year": "1949", "event": "erster Bundeskanzler"},
        {"answer": "Willy Brandt", "year": "1969", "event": "Ostpolitik"},
        {"answer": "Helmut Kohl", "year": "1990", "event": "Wiedervereinigung"},
        {"answer": "Angela Merkel", "year": "2005", "event": "erste Bundeskanzlerin"},
        {"answer": "Gerhard Schröder", "year": "1998", "event": "Agenda 2010"},
        {"answer": "Ludwig Erhard", "year": "1963", "event": "Wirtschaftswunder"},
        {"answer": "Julius Caesar", "year": "-44", "event": "Schlacht"},
        {"answer": "Bismarck", "year": "1871", "event": "Reichsgründung"},
        {"answer": "Otto von Bismarck", "year": "1871", "event": "Gründung des Kaiserreichs"},
        {"answer": "Friedrich Ebert", "year": "1919", "event": "Weimarer Republik"},
    ],
    "Weltgeschichte": [
        {"answer": "1945", "year": "1945", "event": "Ende des Zweiten Weltkriegs"},
        {"answer": "1215", "year": "1215", "event": "Magna Carta"},
        {"answer": "1969", "year": "1969", "event": "Mondlandung"},
        {"answer": "1492", "year": "1492", "event": "Entdeckung Amerikas"},
        {"answer": "1918", "year": "1918", "event": "Ende des Ersten Weltkriegs"},
        {"answer": "1776", "year": "1776", "event": "Unabhängigkeit USA"},
        {"answer": "1347", "year": "1347", "event": "Schwarzer Tod"},
        {"answer": "1848", "year": "1848", "event": "Revolutionsjahr"},
        {"answer": "1991", "year": "1991", "event": "Fall der Sowjetunion"},
        {"answer": "1957", "year": "1957", "event": "Sputnik"},
    ],
    "Epochen": [
        {"answer": "1400", "year": "1400", "event": "Renaissance"},
        {"answer": "1760", "year": "1760", "event": "Industrielle Revolution"},
        {"answer": "1789", "year": "1789", "event": "Französische Revolution"},
        {"answer": "1687", "year": "1687", "event": "Newton Principia"},
        {"answer": "1917", "year": "1917", "event": "Russische Revolution"},
        {"answer": "1492", "year": "1492", "event": "Kolumbus"},
        {"answer": "1800", "year": "1800", "event": "Beethoven"},
        {"answer": "1919", "year": "1919", "event": "Weimarer Republik"},
        {"answer": "1517", "year": "1517", "event": "Reformation"},
        {"answer": "1832", "year": "1832", "event": "Reform Act"},
    ],
    "Entdeckungen": [
        {"answer": "1450", "year": "1450", "event": "Buchdruck"},
        {"answer": "1928", "year": "1928", "event": "Penicillin"},
        {"answer": "1799", "year": "1799", "event": "Humboldt"},
        {"answer": "1961", "year": "1961", "event": "Erster Mensch im All"},
        {"answer": "1870", "year": "1870", "event": "Suezkanal"},
        {"answer": "1953", "year": "1953", "event": "DNA-Struktur"},
        {"answer": "1905", "year": "1905", "event": "Relativität"},
        {"answer": "1804", "year": "1804", "event": "Dampfmaschine"},
        {"answer": "1895", "year": "1895", "event": "Röntgen"},
        {"answer": "2003", "year": "2003", "event": "Human Genome"},
    ],
}

HISTORY_TEMPLATES = {
    "leicht": [
        "Wann war {event}?",
        "Nenne das Jahr von {event}.",
        "In welchem Jahr geschah {event}?",
        "{event} fand in welchem Jahr statt?",
        "Das Jahr {year} gehört zu {event}.",
        "Wann datierst du {event}?",
        "Welches Jahr steht bei {event}?",
        "Gib das Jahr von {event} an.",
        "Wann begann {event}?",
        "Das Jahr {year} lässt sich welchem Ereignis zuordnen?",
    ],
    "mittel": [
        "Welche historische Person ist mit {event} verbunden?",
        "Nenne das Ereignis, das {year} passierte.",
        "Wann trat {event} ein?",
        "Das Datum {year} erinnert an welches Ereignis?",
        "{event} ist verbunden mit welchem Jahr?",
        "Welches Ereignis gelangte {year} ins Geschichtsbuch?",
        "Woran erinnert {year} im Zusammenhang mit {event}?",
        "Nenne das historische Ereignis im Jahr {year}.",
        "Welche Begebenheit beschreibt {event}?",
        "Zu welchem Zeitpunkt geschah {event}?",
    ],
    "schwer": [
        "Zu welchem historischen Thema gehört das Jahr {year}?",
        "Welcher Meilenstein wird {year} zugeordnet?",
        "{event} beschreibt welches Jahr?",
        "Im Jahr {year} geschah welches bedeutende Ereignis?",
        "Welcher Zeitraum ist {event} zugeordnet?",
        "Welcher globale Kontext passt zu {year}?",
        "Welche Ära wird mit {event} verbunden?",
        "Nenne das Ereignis hinter {year}.",
        "Wie heißt das Ereignis, das {year} prägt?",
        "Welcher geschichtliche Wendepunkt steckt hinter {event}?",
    ],
}


def generate_history():
    topics = {}
    for category, entries in HISTORY_DATA.items():
        modes = {}
        for mode in MODE_ORDER:
            description = f"{category} - {mode.title()}"
            templates = HISTORY_TEMPLATES[mode]
            modes[mode] = build_mode(description, lambda templates=templates, entries=entries: build_question_set(entries, templates))
        topics[category] = {"modes": modes}
    return topics


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
QUIZZES_PATH = os.path.join(BASE_DIR, "quizzes.json")

def main():
    payload = {
        "Mathematik": generate_math(),
        "Geografie": generate_geografie(),
        "Englisch": generate_english(),
        "Geschichte": generate_history(),
    }
    with open(QUIZZES_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

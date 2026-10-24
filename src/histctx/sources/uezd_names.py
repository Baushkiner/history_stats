"""Уезды латиницей → уезды 1897 года RISTAT.

Три пакета воспроизведения на Harvard Dataverse — Дауэр и др. о волнениях
и земстве, Дауэр и Маркевич о мобилизации 1914–1916 годов, Буггле и
Нафцигер о крепостном праве — пишут уезды латиницей, и каждый по-своему:
«Arkhangel'skii» (транслитерация Библиотеки Конгресса, как у самого RISTAT
в поле `Name_ENG`), «1. Arhangel'skaja» и «Carevskij» (ГОСТ с «h» и «c»),
«Holmogorskij», «Kishinevskij». Словарь на каждое написание, как у голода
1891 года, здесь не окупается: уездов больше двух тысяч строк, а различия
сводятся к правилам транслитерации.

Поэтому сверка идёт по ключу, в котором эти правила сняты: «kh» и «h»,
«ts» и «c», «ia», «ja» и «ya» дают одно и то же, гласные «i/j/y» и
двойные согласные выпадают, окончание прилагательного отрезается. Ключ
считается с обеих сторон — от латиницы набора и от `Name_ENG` и
транслитерации `Name_RU` справочника — и сравнивается **внутри губернии**:
«Aleksandrovskii» есть в шести губерниях, и вне губернии ключ ничего не
говорит.

Совпадение бывает трёх видов, и вид записывается в запись:

* `exact` — ключи равны;
* `prefix` — один ключ начинается с другого (набор обрезал название:
  «2. Aleksandr»), и такой уезд в губернии один;
* `fuzzy` — ближайший по `difflib` ключ с долей совпадения не ниже 0,8 и
  с запасом над вторым кандидатом;
* `manual` — написание заведено в словарь сборщика руками: опечатка
  набора («Boranenskij»), уезд, переименованный или слитый до 1897 года
  (Ясский → Белецкий, Суражский → Витебский).

Не совпало — `None`: уезд остаётся в данных с пометкой
`district_unmatched`, а не подбирается наугад. Русское название записи —
из справочника 1897 года, а у уездов из ручного словаря — то, под которым
уезд стоит в наборе.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from ..geo import region_key

_RU_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "iu",
    "я": "ia", "і": "i",
}

# Диакритика польских и прибалтийских названий в `Name_ENG` справочника.
_FOLD = str.maketrans({"ł": "l", "ó": "o", "ś": "s", "ż": "z", "ź": "z", "ć": "c", "ń": "n",
                       "ą": "a", "ę": "e", "ü": "u", "ä": "a", "ö": "o", "õ": "o"})

# Порядок важен: «shch» раньше «sh», «eh» в начале слова (э) раньше «kh».
# «w» — щ у набора о мобилизации («Wigrovskij», «Tarawanskij»): в остальных
# написаниях этой буквы нет, а польские названия справочник пишет через «v».
_DIGRAPHS = (("shch", "S"), ("shh", "S"), ("w", "S"), ("kh", "h"), ("zh", "Z"), ("ch", "C"),
             ("sh", "W"), ("ts", "c"))

FUZZY_RATIO = 0.8
FUZZY_MARGIN = 0.05
PREFIX_MIN = 4


def translit(text: Optional[str]) -> str:
    """«Архангельский» → «arkhangelskii»: кириллица в латиницу, как у RISTAT."""
    return "".join(_RU_LAT.get(ch, ch) for ch in str(text or "").lower())


def latin_key(text: Optional[str]) -> str:
    """Ключ уезда, в котором сняты различия транслитераций.

    «1. Arhangel'skaja», «Arkhangel'skii» и «Архангельский» дают «arhangelsk».
    Кириллица переводится в латиницу до всего остального.
    """
    s = translit(text).translate(_FOLD)
    s = re.sub(r"^\s*\d+\s*[.)]?\s*", "", s)          # «10. Plonskij», «9.Pokrovskij»
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"\b(uezd|okrug|otdel|obl|oblast|gub|guberniia|gubernia)\b\.?", "", s)
    s = re.sub(r"[^a-z]", "", s)
    if s.startswith("eh"):
        s = "e" + s[2:]
    for old, new in _DIGRAPHS:
        s = s.replace(old, new)
    s = re.sub(r"[ijy]", "", s)
    s = re.sub(r"(.)\1+", r"\1", s)
    s = re.sub(r"[aeou]+$", "", s)
    return s


@dataclass(frozen=True)
class District:
    """Уезд справочника RISTAT 1897 года.

    Уезд опознаёт `Distr_ID`: `RISTAT_ID` в этом справочнике один на всю
    губернию («1897_04» у всех девяти уездов Архангельской), и уезда он не
    различает.
    """

    distr_id: str
    name: str          # «Елецкий» — как в Name_RU
    province: str      # «Орловская губерния» — как в prov_RU
    ristat_id: str = ""


@dataclass(frozen=True)
class Match:
    district: District
    how: str           # exact | prefix | fuzzy


class RistatDistricts:
    """Уезды 1897 года по губерниям с ключами `latin_key`.

    Строится из `data/out/boundaries/districts_1897.geojson`. Губерния
    ищется по `region_key` от русского названия — его сборщик берёт из
    своего закрытого словаря латиница → губерния.
    """

    def __init__(self, feats: Iterable[dict]) -> None:
        self.by_province: dict[str, list[tuple[set, District]]] = {}
        self.provinces: dict[str, str] = {}
        self.by_id: dict[str, District] = {}
        for feature in feats:
            props = feature.get("properties") or {}
            province, name = props.get("prov_RU"), props.get("Name_RU")
            distr_id = props.get("Distr_ID")
            if not province or not name or distr_id is None:
                continue
            name = " ".join(str(name).split())          # «Кюменский\r\n»
            district = District(str(distr_id), name, province, str(props.get("RISTAT_ID") or ""))
            keys = {latin_key(name), latin_key(props.get("Name_ENG"))} - {""}
            pkey = region_key(province)
            self.provinces.setdefault(pkey, province)
            self.by_province.setdefault(pkey, []).append((keys, district))
            self.by_id[district.distr_id] = district

    @classmethod
    def load(cls, path: Path) -> "RistatDistricts":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(payload.get("features") or [])

    def __len__(self) -> int:
        return len(self.by_id)

    def province(self, name: Optional[str]) -> Optional[str]:
        """Название губернии так, как его пишет справочник, или None."""
        key = self._pkey(name)
        return self.provinces.get(key) if key else None

    def names(self, province: Optional[str]) -> list[str]:
        return sorted(d.name for _, d in self.by_province.get(self._pkey(province) or "", []))

    def match(self, province: Optional[str], district_latin: Optional[str]) -> Optional[Match]:
        """Уезд внутри губернии по латинскому названию набора."""
        if not province or not district_latin:
            return None
        units = self.by_province.get(self._pkey(province) or "")
        key = latin_key(district_latin)
        if not units or not key:
            return None
        exact = [d for keys, d in units if key in keys]
        if len(exact) == 1:
            return Match(exact[0], "exact")
        if len(exact) > 1:
            return None
        if len(key) >= PREFIX_MIN:
            prefix = {d for keys, d in units
                      for k in keys if k and (k.startswith(key) or key.startswith(k))
                      and min(len(k), len(key)) >= PREFIX_MIN}
            if len(prefix) == 1:
                return Match(prefix.pop(), "prefix")
        scored = sorted(((max(difflib.SequenceMatcher(None, key, k).ratio() for k in keys), d)
                         for keys, d in units if keys), key=lambda x: -x[0])
        if scored and scored[0][0] >= FUZZY_RATIO and (
                len(scored) == 1 or scored[0][0] - scored[1][0] >= FUZZY_MARGIN):
            return Match(scored[0][1], "fuzzy")
        return None

    def by_name(self, province: Optional[str], name: Optional[str]) -> Optional[Match]:
        """Уезд по русскому названию справочника — для написаний, заведённых
        в словарь сборщика вручную («K-Podol'sk» → «Каменец-Подольский»)."""
        units = self.by_province.get(self._pkey(province) or "")
        if not units or not name:
            return None
        # Сначала строка целиком: у «Донской 1-й» и «Донской 2-й» ключ
        # `region_key` один и тот же — цифры он выбрасывает.
        def norm(text: str) -> str:
            return " ".join(text.lower().replace("ё", "е").split())

        hits = [d for _, d in units if norm(d.name) == norm(name)]
        if not hits:
            hits = [d for _, d in units if region_key(d.name) == region_key(name)]
        return Match(hits[0], "manual") if len(hits) == 1 else None

    def _pkey(self, province: Optional[str]) -> Optional[str]:
        """Ключ губернии с учётом того, как её называет справочник."""
        for name in (province, RISTAT_PROVINCE_ALIASES.get(province or "")):
            key = region_key(name) if name else None
            if key and key in self.by_province:
                return key
        return None


# Губернии так, как их пишут оба набора Нафцигера (волнения и земство, крепостные
# и города): название губернского города или прилагательного, со своими
# опечатками («Grodnno», «Vologoda»). Словарь закрытый: чего здесь нет,
# остаётся латиницей, а запись получает `district_unmatched`.
NAFZIGER_PROVINCES = {
    "Arkhangel'sk": "Архангельская губерния", "Astrakhan": "Астраханская губерния",
    "Bessarabia": "Бессарабская губерния", "Chernigov": "Черниговская губерния",
    "Ekaterinoslav'": "Екатеринославская губерния", "Estliand": "Эстляндская губерния",
    "Grodnno": "Гродненская губерния", "Iaroslav'": "Ярославская губерния",
    "Iaroslavl'": "Ярославская губерния", "Kaluzha": "Калужская губерния",
    "Kazan": "Казанская губерния", "Khar'kov": "Харьковская губерния",
    "Kherson": "Херсонская губерния", "Kiev": "Киевская губерния",
    "Kostroma": "Костромская губерния", "Kovno": "Ковенская губерния",
    "Kurliand": "Курляндская губерния", "Kursk": "Курская губерния",
    "Lifliand": "Лифляндская губерния", "Minsk": "Минская губерния",
    "Mogilev": "Могилёвская губерния", "Moscow": "Московская губерния",
    "Nizhegorod": "Нижегородская губерния", "Novgorod": "Новгородская губерния",
    "Olonets": "Олонецкая губерния", "Orel": "Орловская губерния",
    "Orlov": "Орловская губерния", "Orenburg": "Оренбургская губерния",
    "Penza": "Пензенская губерния", "Penzen": "Пензенская губерния",
    "Perm": "Пермская губерния", "Petersburg": "Санкт-Петербургская губерния",
    "Sankt-Peterburg": "Санкт-Петербургская губерния", "Podol'sk": "Подольская губерния",
    "Poltava": "Полтавская губерния", "Pskov": "Псковская губерния",
    "Riazan": "Рязанская губерния", "Samara": "Самарская губерния",
    "Saratov": "Саратовская губерния", "Simbirsk": "Симбирская губерния",
    "Smolensk": "Смоленская губерния", "Tambov": "Тамбовская губерния",
    "Taurida": "Таврическая губерния", "Tavrich": "Таврическая губерния",
    "Tul'a": "Тульская губерния", "Tver": "Тверская губерния", "Ufa": "Уфимская губерния",
    "Viatka": "Вятская губерния", "Vilno": "Виленская губерния",
    "Vitebsk": "Витебская губерния", "Vladimir": "Владимирская губерния",
    "Vologoda": "Вологодская губерния", "Volyna": "Волынская губерния",
    "Voronezh": "Воронежская губерния", "Zemlia voiska donskogo": "Область Войска Донского",
}

# Как справочник RISTAT называет единицы, у которых в 1850–1910-е годы было
# другое имя: Донская область у него «земля», Батумская область и Сухумский
# округ входят в Кутаисскую губернию, Закатальский округ — в Тифлисскую.
RISTAT_PROVINCE_ALIASES = {
    "Область Войска Донского": "Земля войска Донского",
    "Батумская область": "Кутаисская  губерния вкл. Сухумский округ",
    "Сухумский округ": "Кутаисская  губерния вкл. Сухумский округ",
    "Кутаисская губерния": "Кутаисская  губерния вкл. Сухумский округ",
    "Закатальский округ": "Тифлисская губерния вкл. Закатальский округ",
    "Тифлисская губерния": "Тифлисская губерния вкл. Закатальский округ",
    "Камчатская область": "Приморская область",
    "Сахалинская область": "Остров Сахалин",
}

# Уезды наборов Нафцигера, которые по ключу не сводятся: опечатки, названия
# до переименования и слияния. Значение — (название для записи, название
# в справочнике 1897 года, губерния справочника, если уезд туда переехал).
NAFZIGER_DISTRICTS = {
    # Ясский уезд переименован в Бельцкий (у RISTAT — Белецкий) в 1887 году.
    ("Bessarabia", "Iasskii"): ("Ясский уезд", "Белецкий", None),
    ("Chernigov", "Gorodnitskii"): ("Городнянский уезд", "Городнянский", None),
    # Ростовский уезд передан из Екатеринославской губернии в Область Войска
    # Донского в 1887 году; в справочнике 1897 года он там.
    ("Ekaterinoslav'", "Rostovskii"): ("Ростовский уезд", "Ростовский",
                                       "Область Войска Донского"),
    ("Kaluzha", "Meschovskii"): ("Мещовский уезд", "Мещонский", None),
    ("Mogilev", "Chausovskii"): ("Чаусский уезд", "Чаусский", None),
    ("Podol'sk", "Novo-Ushchitskii"): ("Ушицкий уезд", "Ушицкий", None),
    # Справочник подписал столичный уезд названием 1914 года.
    ("Sankt-Peterburg", "Sankt-Peterburgskii"): ("Санкт-Петербургский уезд", "Петроградский",
                                                 None),
    ("Petersburg", "Sankt-Peterburgskii"): ("Санкт-Петербургский уезд", "Петроградский", None),
    ("Ufa", "Zlatoustskii"): ("Златоустовский уезд", "Златоустовский", None),
    # Суражский уезд Витебской губернии слит с Витебским в 1866 году.
    ("Vitebsk", "Surazhskii"): ("Суражский уезд", "Витебский", None),
    # Динабургский уезд переименован в Двинский в 1893 году.
    ("Vitebsk", "Dinaburgskii"): ("Динабургский уезд", "Двинский", None),
    ("Zemlia voiska donskogo", "Pervyi Donskoi"): ("Первый Донской округ", "Донской 1-й", None),
    ("Zemlia voiska donskogo", "Vtoroi Donskoi"): ("Второй Донской округ", "Донской 2-й", None),
}

# Хвосты, при которых в названии единицы уже есть её тип.
UNIT_TAILS = ("уезд", "округ", "отдел", "приставство", "край", "улус", "степь", "участок",
              "ое", "ая")
DON = "Область Войска Донского"


# Единственный уезд, который справочник подписал не прилагательным мужского
# рода: Архангельский уезд у него «Архангельская».
RISTAT_NAME_FIXES = {"Архангельская": "Архангельский"}


def unit_name(name: str, province: Optional[str]) -> str:
    """«Елецкий» → «Елецкий уезд»; у Войска Донского — округ."""
    name = RISTAT_NAME_FIXES.get(name, name)
    if name.endswith(UNIT_TAILS):
        return name
    if province and region_key(province) in (region_key(DON),
                                             region_key("Земля войска Донского")):
        return f"{name} округ"
    return f"{name} уезд"


def genitive(province: str) -> str:
    """«Орловская губерния» → «Орловской губернии» для заголовка."""
    words = province.split()
    if len(words) == 2 and words[0].endswith(("ая", "яя")):
        head = words[0][:-2] + ("ой" if words[0].endswith("ая") else "ей")
        tail = {"губерния": "губернии", "область": "области"}.get(words[1], words[1])
        return f"{head} {tail}"
    if words and words[0] in ("Область", "Земля"):
        return {"Область": "Области", "Земля": "Земли"}[words[0]] + province[len(words[0]):]
    return province


@dataclass(frozen=True)
class Place:
    """Куда относится запись: губерния и уезд по-русски, пара в справочнике."""

    province: Optional[str]
    district: Optional[str]
    place_text: Optional[str]
    head: str                  # «Елецкий уезд Орловской губернии»
    distr_id: Optional[str]
    how: Optional[str]         # exact | prefix | fuzzy | manual | None
    confidence: str            # ok | district_unmatched


def resolve(index: Optional[RistatDistricts], province: Optional[str],
            district_latin: Optional[str], *, manual: Optional[tuple] = None) -> Place:
    """Губерния (уже по-русски) и уезд латиницей → место записи.

    `manual` — строка ручного словаря сборщика. Без пары уезд остаётся в
    `place_text` латиницей с пометкой: выдумывать название нельзя.
    """
    match = None
    district = None
    if manual is not None:
        district, ristat_name, ristat_province = manual
        if index is not None:
            match = index.by_name(ristat_province or province, ristat_name)
    elif index is not None:
        match = index.match(province, district_latin)
        if match is not None:
            district = unit_name(match.district.name, province)
    raw = str(district_latin or "").strip() or None
    confidence = "ok" if (index is None and district) or match else "district_unmatched"
    place_district = district or (f"{raw} (уезд, написание набора)" if raw else None)
    place_text = ", ".join(p for p in (place_district, province) if p) or None
    if district and province and district.endswith(("ая", "ое")):
        # «Амурская», «Большедербетовское»: справочник не называет тип единицы,
        # и «Амурская Амурской области» читалась бы как опечатка.
        head = f"{district} (единица справочника 1897 года), {province}"
    elif district and province:
        head = f"{district} {genitive(province)}"
    else:
        head = place_text or "уезд без названия"
    return Place(province, district, place_text, head,
                 match.district.distr_id if match else None,
                 match.how if match else None, confidence)

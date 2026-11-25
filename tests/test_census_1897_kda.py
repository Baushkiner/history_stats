"""Разбор сборки k-da.dev/russia-1897: перепись 1897 года по уездам и городам.

Сети в тестах нет. Сборка сайта — минифицированный JavaScript, и образец
ниже собран так же: поля модулей — константами, модуль — пространством
`Object.freeze(Object.defineProperty({…}))`, таблица модулей —
`{"../data/<губерния>/<уезд>.json":<пространство>}`, словарь интерфейса —
объектом и `JSON.parse('…')`, коды губерний — с полями `Ma.SIBERIA`.
Имя пространства `id` переиспользовано в функции выше по тексту — так
бывает у минификатора, и подхватить чужое присваивание разбор не должен.

Проверяется то, на чём слой держится: адрес сборки со страницы, проверка
формата, литералы (`3e3`, `!0`, экранирование), названия по `name_key`,
записи уезда и места без точки, сведение с RISTAT (точное, ручное, не
сведено), губерния под именем других слоёв, пустая таблица грамотности.
"""

import json

import pytest

from histctx.registry import BY_SLUG
from histctx.sources import census_1897_kda as kda
from histctx.sources.census_1897_kda import (
    CENSUS_1897_KDA, JsReader, KdaError, Ref, bundle_url, consistency, literacy_totals,
    parse_bundle, records,
)
from histctx.sources.uezd_names import RistatDistricts

PAGE = """<!doctype html><html><head>
<script type="module" crossorigin src="/russia-1897/assets/index-B3CbH3g9.js"></script>
<link rel="stylesheet" crossorigin href="/russia-1897/assets/index-Djs0JnuG.css">
</head><body><div id="root"></div></body></html>"""

UEZD_NAMES = {"Chitinsky": {"name": "Читинский округ", "old_name": "Читинскій округъ"},
              "Margelansky": {"name": "Маргеланский уезд", "old_name": "Маргеланскій уѣздъ"},
              "Turukhansky": {"name": "Туруханский край", "old_name": "Туруханскій край"},
              "Baltsky": {"name": "Балтский уезд", "old_name": "Балтскій уѣздъ"}}
LOCALITY_NAMES = {"Chita": {"name": "Чита", "old_name": "Чита"},
                  "SventsianyCity": {"name": "Свенцяны", "old_name": "Свенцяны"},
                  "Balta": {"name": "Балта", "old_name": "Балта"}}


def _js_json(obj) -> str:
    """JSON внутри одинарных кавычек, как его пишет Vite: `JSON.parse('…')`."""
    return "JSON.parse('" + json.dumps(obj, ensure_ascii=False).replace("'", "\\'") + "')"


BUNDLE = (
    # Чужое присваивание имени `id` выше модуля: разбор должен его обойти.
    'function zz(e){let id=e+1;return id}const '
    # Читинский округ: город Чита, число «3e3», поле уезда и места.
    'ewe="Chitinsky",nwe="uezd.Chitinsky.name",iwe="ZBK",lwe={verst2:112746},'
    'owe={m:1600,f:1400,total:3e3},'
    'twe=[{id:"Chita",type:"city",name_key:"locality.Chita.name",'
    'population:{m:600,f:400,total:1e3},flags:{uyezd_center:!0,guberniya_center:!0}}],'
    'mwe={uyezd:[{lang:"russian_great",m:1000,f:900},{lang:"buryat",m:600,f:500}],'
    '"city:Chita":[{lang:"russian_great",m:550,f:380},{lang:"yiddish_hebrew",m:50,f:20}]},'
    'swe={uyezd:[{age:"0",m:100,f:100},{age:"1-9",m:500,f:400},{age:"10-19",m:1000,f:900}],'
    '"city:Chita":[{age:"1-9",m:100,f:100},{age:"20-29",m:500,f:300}]},'
    'gwe={uyezd:[{religion:"orthodox",m:1200,f:1100},{religion:"buddhist",m:400,f:300}],'
    '"city:Chita":[{religion:"orthodox",m:600,f:400}]},'
    'xIe={id:ewe,name_key:nwe,guberniya:iwe,area:lwe,uyezd_population:owe,cities:twe,'
    'language_by_sex:mwe,age10_by_sex:swe,religion_by_sex:gwe},'
    'id=Object.freeze(Object.defineProperty({__proto__:null,age10_by_sex:swe,area:lwe,'
    'cities:twe,default:xIe,guberniya:iwe,id:ewe,language_by_sex:mwe,name_key:nwe,'
    'religion_by_sex:gwe,uyezd_population:owe},Symbol.toStringTag,{value:"Module"})),'
    # Маргеланский уезд: у RISTAT — Скобелевский; ключ места не совпадает с id.
    'a1="Margelansky",a2="uezd.Margelansky.name",a3="FER",a4={verst2:9e3},'
    'a5={m:60,f:40,total:100},a6=[{id:"Sventsiany",type:"adm_vuillage",'
    'name_key:"locality.SventsianyCity.name",population:{m:6,f:4,total:10},flags:{}}],'
    'a7={uyezd:[{lang:"sart",m:60,f:40}],"city:Sventsiany":[{lang:"sart",m:6,f:4}]},'
    'a8={uyezd:[{age:"unknown",m:60,f:40}]},a9={uyezd:[{religion:"muslim",m:60,f:40}]},'
    'b1=Object.freeze(Object.defineProperty({__proto__:null,age10_by_sex:a8,area:a4,cities:a6,'
    'guberniya:a3,id:a1,language_by_sex:a7,name_key:a2,religion_by_sex:a9,'
    'uyezd_population:a5},Symbol.toStringTag,{value:"Module"})),'
    # Туруханский край: у RISTAT разбит на участки — не сводится.
    'c1="Turukhansky",c2="uezd.Turukhansky.name",c3="ENI",'
    'c5={m:5,f:5,total:10},c6=[],c7={uyezd:[{lang:"russian_great",m:5,f:5}]},'
    'c8={uyezd:[{age:"30-39",m:5,f:5}]},c9={uyezd:[{religion:"orthodox",m:5,f:5}]},'
    'd1=Object.freeze(Object.defineProperty({__proto__:null,age10_by_sex:c8,cities:c6,'
    'guberniya:c3,id:c1,language_by_sex:c7,name_key:c2,religion_by_sex:c9,'
    'uyezd_population:c5},Symbol.toStringTag,{value:"Module"})),'
    # Балтский уезд «Каменец-Подольской» губернии, с пустой таблицей грамотности.
    'e1="Baltsky",e2="uezd.Baltsky.name",e3="POD",'
    'e5={m:5,f:5,total:10},e6=[{id:"Balta",type:"city",name_key:"locality.Balta.name",'
    'population:{m:2,f:2,total:4},flags:{uyezd_center:!0}}],'
    'e7={uyezd:[{lang:"russian_little",m:5,f:4}],"city:Balta":[{lang:"yiddish_hebrew",m:2,f:2}]},'
    'e8={uyezd:[{age:"30-39",m:5,f:5}]},e9={uyezd:[{religion:"orthodox",m:5,f:5}]},'
    'e0={uyezd_no_city:[{religion:"orthodox",langs:[{lang:"russian_little",metric:"total",'
    'm:0,f:0},{lang:"russian_little",metric:"literate",m:0,f:0}]}],'
    '"city:Balta":[{religion:"jewish",langs:[{lang:"russian_total",is_group:!0,'
    'metric:"total",m:2,f:2},{lang:"yiddish_hebrew",metric:"total",m:2,f:2},'
    '{lang:"yiddish_hebrew",metric:"literate",m:1,f:0}]}]},'
    'f1=Object.freeze(Object.defineProperty({__proto__:null,age10_by_sex:e8,cities:e6,'
    'guberniya:e3,id:e1,language_by_sex:e7,name_key:e2,religion_by_sex:e9,'
    'religion_x_language_x_literacy:e0,uyezd_population:e5},Symbol.toStringTag,'
    '{value:"Module"}));'
    'function g(){const wa=Object.assign({"../data/ENI/Turukhansky.json":d1,'
    '"../data/FER/Margelansky.json":b1,"../data/POD/Baltsky.json":f1,'
    '"../data/ZBK/Chitinsky.json":id});return wa}'
    'const Ma={SIBERIA:"siberia",EUROPE:"european_russia"},'
    'Sn={ZBK:{type:"oblast",region:Ma.SIBERIA,nameKey:"ZabaykalskayaOblast"},'
    'ENI:{type:"guberniya",region:Ma.SIBERIA,nameKey:"EniseyskayaGovernorate"},'
    'FER:{type:"oblast",region:Ma.SIBERIA,nameKey:"FerganaOblast"},'
    'POD:{type:"guberniya",region:Ma.EUROPE,nameKey:"PodolskGovernorate"}};'
    'const WQe={ZabaykalskayaOblast:{name:"Забайкальская область"},'
    'EniseyskayaGovernorate:{name:"Енисейская губерния"},'
    'FerganaOblast:{name:"Ферганская область"},'
    'PodolskGovernorate:{name:"Каменец-Подольская губерния",'
    'short_name:"Каменец-\\u041fодольская"}},'
    'zQe={city:"город",adm_village:"административное село"},'
    'ZQe={russian_great:"Великорусский",russian_little:"Малорусский",buryat:"Бурятский",'
    'yiddish_hebrew:"Еврейский",sart:"Сартский"},'
    'FQe={orthodox:"Православные",buddhist:"Буддисты",muslim:"Мусульмане",jewish:"Иудеи"},'
    f'XQe={_js_json(UEZD_NAMES)},qQe={_js_json(LOCALITY_NAMES)},'
    'QQe={nav:{home:"Главная"},settlement:zQe,language:ZQe,religion:FQe,guberniya:WQe,'
    'uezd:XQe,locality:qQe};'
    'Ty.use(mTe).init({resources:{ru:{translation:QQe}},lng:"ru"});'
)

DISTRICTS = [
    {"properties": {"Distr_ID": 1, "Name_RU": "Читинская", "Name_ENG": "Chitinskaia",
                    "prov_RU": "Забайкальская область"}},
    {"properties": {"Distr_ID": 2, "Name_RU": "Скобелевский", "Name_ENG": "Skobelevskii",
                    "prov_RU": "Ферганская область"}},
    {"properties": {"Distr_ID": 3, "Name_RU": "Дудинский участок", "Name_ENG": "Dudinskii",
                    "prov_RU": "Енисейская губерния"}},
    {"properties": {"Distr_ID": 4, "Name_RU": "Балтский", "Name_ENG": "Baltskii",
                    "prov_RU": "Подольская губерния"}},
]


@pytest.fixture
def bundle(monkeypatch):
    monkeypatch.setattr(kda, "MIN_UEZDS", 4)
    return parse_bundle(BUNDLE)


@pytest.fixture
def recs(bundle):
    return records(bundle, RistatDistricts(DISTRICTS))


def _rec(recs, source_id):
    return next(r for r in recs if r.source_id == source_id)


def test_bundle_url_is_taken_from_the_page():
    assert bundle_url(PAGE) == "https://k-da.dev/russia-1897/assets/index-B3CbH3g9.js"
    with pytest.raises(KdaError, match="формат сборки изменился"):
        bundle_url("<html><script src='/app.js'></script></html>")


def test_reader_literals():
    reader = JsReader('a=[1e3,.5,!0,!1,null,"x\\"\\u0442\\n",\'y\',`z`],b={"k":a,m:Ma.X}')
    value, _ = reader.value(2)
    assert value == [1000, 0.5, True, False, None, 'x"т\n', "y", "z"]
    obj, _ = reader.value(reader.text.index("{"))
    assert obj["k"] == Ref("a", obj["k"].pos) and obj["m"].attrs == ("X",)
    with pytest.raises(KdaError, match="не литерал"):
        JsReader("a=f(1)").value(2)


def test_modules_and_locale(bundle):
    assert bundle.module_paths == 4
    assert [u["id"] for u in bundle.uezds] == ["Turukhansky", "Margelansky", "Baltsky",
                                               "Chitinsky"]
    chita = bundle.uezds[-1]
    assert chita["uyezd_population"]["total"] == 3000
    assert bundle.province_name("ZBK") == "Забайкальская область"
    assert bundle.provinces["ZBK"]["region"] == "siberia"
    assert bundle.label("language", "buryat") == "Бурятский"
    assert bundle.locale["guberniya"]["PodolskGovernorate"]["short_name"] == "Каменец-Подольская"


def test_format_is_checked(monkeypatch):
    with pytest.raises(KdaError, match="ждали не меньше 700"):
        parse_bundle(BUNDLE)
    monkeypatch.setattr(kda, "MIN_UEZDS", 4)
    with pytest.raises(KdaError, match="нет полей cities"):
        parse_bundle(BUNDLE.replace("cities:twe,default", "default").replace(
            "cities:twe,language", "language"))
    with pytest.raises(KdaError, match="нет таблицы модулей"):
        parse_bundle(BUNDLE.replace("../data/", "./data/"))
    with pytest.raises(KdaError, match="словаря"):
        parse_bundle(BUNDLE.replace("resources:{ru:", "resources:{en:"))


def test_uezd_record(recs):
    rec = _rec(recs, "ZBK/Chitinsky")
    assert rec.title == "Читинский округ Забайкальской области: перепись 1897 года"
    assert rec.scope == "region" and rec.lat is None and not rec.has_point
    assert (rec.region, rec.district) == ("Забайкальская область", "Читинский округ")
    assert rec.year_from == rec.year_to == 1897 and rec.date_precision == "day"
    assert rec.url == "https://k-da.dev/russia-1897/ru/uyezd/ZBK/Chitinsky"
    assert rec.extra["ristat_distr_id"] == "1" and rec.extra["ristat_match"] == "exact"
    assert rec.extra["old_name"] == "Читинскій округъ"
    assert rec.extra["census_1897"]["язык"]["Бурятский"] == {"м": 600, "ж": 500}
    assert rec.extra["census_1897"]["возраст"]["до года"] == {"м": 100, "ж": 100}
    assert rec.extra["localities"] == [{"id": "Chita", "name": "Чита", "type": "city",
                                        "population": 1000}]
    assert "3 000 жителей (1 600 муж., 1 400 жен.)" in rec.summary
    assert "великорусский — 63%, бурятский — 37%" in rec.summary
    assert "Детей до 10 лет — 37%" in rec.summary
    assert "Место с отдельной таблицей переписи: Чита (1 000)" in rec.summary


def test_locality_record_has_no_point(recs):
    rec = _rec(recs, "ZBK/Chitinsky/Chita")
    assert rec.title == "Чита (Читинский округ Забайкальской области): перепись 1897 года"
    assert rec.summary.startswith("Чита — губернский город. Перепись 1897 года: 1 000 жителей")
    assert not rec.has_point and rec.scope == "region"
    assert rec.place_text == "Чита, Читинский округ, Забайкальская область"
    assert rec.url == "https://k-da.dev/russia-1897/ru/locality/ZBK/Chitinsky/Chita"
    assert rec.extra["unit"] == "населённое место"
    assert rec.extra["coordinates"].startswith("в данных нет")


def test_names_by_name_key_and_type_typo(recs):
    rec = _rec(recs, "FER/Margelansky/Sventsiany")
    assert rec.title.startswith("Свенцяны (")
    assert rec.extra["settlement_type"] == "adm_village"
    assert rec.extra["settlement_type_on_site"] == "adm_vuillage"
    assert rec.category.startswith("административное село")


def test_ristat_manual_and_unmatched(recs):
    margelan = _rec(recs, "FER/Margelansky")
    assert margelan.extra["ristat_name"] == "Скобелевский"
    assert margelan.extra["ristat_match"] == "manual" and margelan.confidence == "ok"
    turukhan = _rec(recs, "ENI/Turukhansky")
    assert turukhan.confidence == "district_unmatched"
    assert "ristat_distr_id" not in turukhan.extra
    assert turukhan.district == "Туруханский край"     # запись осталась


def test_province_named_as_in_other_layers(recs):
    balta = _rec(recs, "POD/Baltsky")
    assert balta.region == "Подольская губерния"
    assert balta.extra["province_on_site"] == "Каменец-Подольская губерния"
    assert balta.extra["ristat_distr_id"] == "4"


def test_literacy_only_when_filled(bundle, recs):
    baltsky = next(u for u in bundle.uezds if u["id"] == "Baltsky")
    assert literacy_totals(baltsky, "uyezd_no_city") is None
    assert literacy_totals(baltsky, "city:Balta") == {"всего": {"м": 2, "ж": 2},
                                                      "грамотных": {"м": 1, "ж": 0}}
    assert "Грамотных — 25%" in _rec(recs, "POD/Baltsky/Balta").summary
    assert "грамотность" not in _rec(recs, "POD/Baltsky").extra["census_1897"]


def test_consistency_counts(bundle):
    counts = consistency(bundle)
    assert counts["units"] == 7
    # У Балтского уезда язык не сходится с итогом (9 из 10); у Свенцян и Балты
    # нет таблицы возраста.
    assert counts["язык: сумма ≠ итогу"] == 1
    assert counts["возраст: таблицы нет"] == 2


def test_layer_is_registered():
    assert BY_SLUG[CENSUS_1897_KDA.slug] is CENSUS_1897_KDA
    assert CENSUS_1897_KDA.status == "harvested"
    assert "согласия владельца" in CENSUS_1897_KDA.license

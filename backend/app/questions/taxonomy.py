"""Exactly nine global main categories (spec §8). Mixed is a matchmaking selection, not a category."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    id: str
    names: dict[str, str]
    icon: str
    subcategories: dict[str, dict[str, str]]


def _subs(pairs: list[tuple[str, str, str]]) -> dict[str, dict[str, str]]:
    return {sid: {"en": en, "tr": tr} for sid, en, tr in pairs}


CATEGORIES: tuple[Category, ...] = (
    Category("geography", {"en": "Geography & World", "tr": "Coğrafya ve Dünya"}, "public", _subs([
        ("countries", "Countries", "Ülkeler"), ("capitals", "Capitals", "Başkentler"),
        ("flags", "Flags", "Bayraklar"), ("maps", "Maps", "Haritalar"), ("cities", "Cities", "Şehirler"),
        ("landmarks", "Landmarks", "Simge Yapılar"), ("rivers", "Rivers", "Nehirler"),
        ("mountains", "Mountains", "Dağlar"), ("islands", "Islands", "Adalar"), ("oceans", "Oceans", "Okyanuslar"),
        ("world_heritage", "UNESCO World Heritage", "UNESCO Dünya Mirası"),
    ])),
    Category("science_nature", {"en": "Science & Nature", "tr": "Bilim ve Doğa"}, "science", _subs([
        ("animals", "Animals", "Hayvanlar"), ("plants", "Plants", "Bitkiler"), ("space", "Space", "Uzay"),
        ("human_body", "Human Body", "İnsan Vücudu"), ("biology", "Biology", "Biyoloji"),
        ("physics", "Physics", "Fizik"), ("chemistry", "Chemistry", "Kimya"),
        ("earth_science", "Earth Science", "Yer Bilimi"), ("environment", "Environment", "Çevre"),
    ])),
    Category("history", {"en": "History", "tr": "Tarih"}, "history_edu", _subs([
        ("ancient_civilisations", "Ancient Civilisations", "Antik Uygarlıklar"),
        ("world_wars", "World Wars", "Dünya Savaşları"), ("exploration", "Exploration", "Keşifler"),
        ("empires", "Empires", "İmparatorluklar"), ("historical_figures", "Historical Figures", "Tarihi Kişiler"),
        ("historical_inventions", "Historical Inventions", "Tarihi İcatlar"),
        ("archaeology", "Archaeology", "Arkeoloji"),
    ])),
    Category("sports", {"en": "Sports", "tr": "Spor"}, "sports_soccer", _subs([
        ("world_cup", "World Cup", "Dünya Kupası"), ("olympics", "Olympics", "Olimpiyatlar"),
        ("football", "Global Football", "Futbol"), ("basketball", "Basketball", "Basketbol"),
        ("tennis", "Tennis", "Tenis"), ("formula_1", "Formula 1", "Formula 1"),
        ("athletics", "Athletics", "Atletizm"),
        ("international_competitions", "International Competitions", "Uluslararası Turnuvalar"),
    ])),
    Category("movies_tv", {"en": "Movies & TV", "tr": "Film ve Dizi"}, "movie", _subs([
        ("hollywood", "Hollywood", "Hollywood"), ("bollywood", "Bollywood", "Bollywood"),
        ("global_films", "Global Films", "Dünya Sineması"), ("tv_streaming", "TV & Streaming", "Dizi ve Dijital"),
        ("awards", "Oscars & Awards", "Oscar ve Ödüller"), ("directors", "Directors", "Yönetmenler"),
        ("characters_franchises", "Characters & Franchises", "Karakterler ve Seriler"),
    ])),
    Category("music", {"en": "Music", "tr": "Müzik"}, "music_note", _subs([
        ("artists", "Artists", "Sanatçılar"), ("bands", "Bands", "Gruplar"),
        ("instruments", "Instruments", "Enstrümanlar"), ("albums", "Albums", "Albümler"),
        ("music_history", "Music History", "Müzik Tarihi"), ("music_awards", "Music Awards", "Müzik Ödülleri"),
    ])),
    Category("food_culture", {"en": "Food & Culture", "tr": "Yemek ve Kültür"}, "restaurant", _subs([
        ("cuisines", "World Cuisines", "Dünya Mutfakları"), ("dishes", "Famous Dishes", "Ünlü Yemekler"),
        ("ingredients", "Ingredients", "Malzemeler"), ("traditions", "Traditions", "Gelenekler"),
        ("festivals", "Festivals", "Festivaller"), ("cultural_symbols", "Cultural Symbols", "Kültürel Semboller"),
    ])),
    Category("technology_inventions", {"en": "Technology & Inventions", "tr": "Teknoloji ve İcatlar"},
             "memory", _subs([
                 ("computers", "Computers", "Bilgisayarlar"), ("internet", "Internet", "İnternet"),
                 ("ai_basics", "AI Basics", "Yapay Zekâ Temelleri"),
                 ("smartphones", "Smartphones", "Akıllı Telefonlar"),
                 ("inventions", "Famous Inventions", "Ünlü İcatlar"), ("inventors", "Inventors", "Mucitler"),
                 ("space_technology", "Space Technology", "Uzay Teknolojisi"),
                 ("tech_history", "Technology History", "Teknoloji Tarihi"),
             ])),
    Category("arts_literature", {"en": "Arts & Literature", "tr": "Sanat ve Edebiyat"}, "palette", _subs([
        ("painters", "Painters", "Ressamlar"), ("famous_works", "Famous Works", "Ünlü Eserler"),
        ("public_domain_art", "Public-domain Art", "Kamu Malı Sanat"),
        ("world_literature", "World Literature", "Dünya Edebiyatı"), ("authors", "Authors", "Yazarlar"),
        ("architecture", "Architecture", "Mimari"), ("mythology", "Mythology", "Mitoloji"),
        ("art_movements", "Art Movements", "Sanat Akımları"),
    ])),
)

CATEGORY_IDS: tuple[str, ...] = tuple(c.id for c in CATEGORIES)
CATEGORY_BY_ID: dict[str, Category] = {c.id: c for c in CATEGORIES}

assert len(CATEGORIES) == 9 and "gaming" not in CATEGORY_IDS


def is_valid_subcategory(category_id: str, subcategory_id: str) -> bool:
    category = CATEGORY_BY_ID.get(category_id)
    return bool(category and subcategory_id in category.subcategories)

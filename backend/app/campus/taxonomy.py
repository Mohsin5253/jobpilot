"""Fields and levels of education for every discipline, as data.

- Fields: UNESCO ISCED-F 2013 (11 broad, 29 narrow, 80 detailed fields), codes as published.
- Levels: ISCED 2011 (3 upper secondary ... 8 doctoral).
- Indian programmes: the AISHE 2015-16 reference tables (201 programmes, 35 discipline categories), mapped to ISCED
  (app/data/campus/, built by scripts/import_aishe.py), plus common international degrees.
A college adds its own specialisations under any field and any missing degree; nothing assumes engineering.
"""

BROAD = {
    "00": "Generic programmes and qualifications", "01": "Education", "02": "Arts and humanities",
    "03": "Social sciences, journalism and information", "04": "Business, administration and law",
    "05": "Natural sciences, mathematics and statistics", "06": "Information and communication technologies",
    "07": "Engineering, manufacturing and construction", "08": "Agriculture, forestry, fisheries and veterinary",
    "09": "Health and welfare", "10": "Services",
}
NARROW = {
    "001": "Basic programmes and qualifications", "002": "Literacy and numeracy", "003": "Personal skills and development",
    "011": "Education", "021": "Arts", "022": "Humanities (except languages)", "023": "Languages",
    "031": "Social and behavioural sciences", "032": "Journalism and information", "041": "Business and administration",
    "042": "Law", "051": "Biological and related sciences", "052": "Environment", "053": "Physical sciences",
    "054": "Mathematics and statistics", "061": "Information and communication technologies",
    "071": "Engineering and engineering trades", "072": "Manufacturing and processing", "073": "Architecture and construction",
    "081": "Agriculture", "082": "Forestry", "083": "Fisheries", "084": "Veterinary", "091": "Health", "092": "Welfare",
    "101": "Personal services", "102": "Hygiene and occupational health services", "103": "Security services",
    "104": "Transport services",
}
DETAILED = {
    "0011": "Basic programmes and qualifications", "0021": "Literacy and numeracy", "0031": "Personal skills and development",
    "0111": "Education science", "0112": "Training for pre-school teachers", "0113": "Teacher training without subject specialisation",
    "0114": "Teacher training with subject specialisation", "0211": "Audio-visual techniques and media production",
    "0212": "Fashion, interior and industrial design", "0213": "Fine arts", "0214": "Handicrafts", "0215": "Music and performing arts",
    "0221": "Religion and theology", "0222": "History and archaeology", "0223": "Philosophy and ethics", "0231": "Language acquisition",
    "0232": "Literature and linguistics", "0311": "Economics", "0312": "Political sciences and civics", "0313": "Psychology",
    "0314": "Sociology and cultural studies", "0321": "Journalism and reporting", "0322": "Library, information and archival studies",
    "0411": "Accounting and taxation", "0412": "Finance, banking and insurance", "0413": "Management and administration",
    "0414": "Marketing and advertising", "0415": "Secretarial and office work", "0416": "Wholesale and retail sales", "0417": "Work skills",
    "0421": "Law", "0511": "Biology", "0512": "Biochemistry", "0521": "Environmental sciences", "0522": "Natural environments and wildlife",
    "0531": "Chemistry", "0532": "Earth sciences", "0533": "Physics", "0541": "Mathematics", "0542": "Statistics", "0611": "Computer use",
    "0612": "Database and network design and administration", "0613": "Software and applications development and analysis",
    "0711": "Chemical engineering and processes", "0712": "Environmental protection technology", "0713": "Electricity and energy",
    "0714": "Electronics and automation", "0715": "Mechanics and metal trades", "0716": "Motor vehicles, ships and aircraft",
    "0721": "Food processing", "0722": "Materials (glass, paper, plastic and wood)", "0723": "Textiles (clothes, footwear and leather)",
    "0724": "Mining and extraction", "0731": "Architecture and town planning", "0732": "Building and civil engineering",
    "0811": "Crop and livestock production", "0812": "Horticulture", "0821": "Forestry", "0831": "Fisheries", "0841": "Veterinary",
    "0911": "Dental studies", "0912": "Medicine", "0913": "Nursing and midwifery", "0914": "Medical diagnostic and treatment technology",
    "0915": "Therapy and rehabilitation", "0916": "Pharmacy", "0917": "Traditional and complementary medicine and therapy",
    "0921": "Care of the elderly and of disabled adults", "0922": "Child care and youth services", "0923": "Social work and counselling",
    "1011": "Domestic services", "1012": "Hair and beauty services", "1013": "Hotel, restaurants and catering", "1014": "Sports",
    "1015": "Travel, tourism and leisure", "1021": "Community sanitation", "1022": "Occupational health and safety",
    "1031": "Military and defence", "1032": "Protection of persons and property", "1041": "Transport services",
}
LEVELS = {3: "Upper secondary", 4: "Post-secondary non-tertiary", 5: "Short-cycle tertiary (diploma)", 6: "Bachelor's or equivalent", 7: "Master's or equivalent", 8: "Doctoral or equivalent"}

# AISHE 2015-16 discipline categories -> ISCED-F 2013 (the closest detailed field, or the narrow field when broad).
AISHE_CATEGORY_TO_ISCED = {
    "01": "0811", "02": "0314", "03": "0411", "04": "1032", "05": "1031", "06": "011", "07": "071", "08": "0212", "09": "0213",
    "10": "0231", "11": "0223", "12": "1011", "13": "0232", "14": "0321", "15": "0421", "16": "0322", "17": "0232", "18": "0413",
    "19": "0532", "20": "0912", "21": "022", "22": "1014", "23": "0221", "24": "05", "25": "031", "26": "0923", "27": "0314",
    "28": "02", "29": "0314", "30": "0212", "31": "0831", "32": "061", "34": "0841", "35": "0921", "99": "",
}
# AISHE course levels -> ISCED 2011 levels. Integrated programmes are levelled by the highest award they give.
AISHE_LEVEL_TO_ISCED = {"1": 8, "2": 7, "3": 7, "4": 6, "5": 7, "6": 5, "7": 4}

# Degrees AISHE 2015-16 doesn't list, and common international ones. (name, abbreviation, level, years, country)
EXTRA_DEGREES = [
    ("Industrial Training Institute certificate", "ITI", 3, 2, "IN"), ("Polytechnic Diploma", "Diploma (Poly.)", 5, 3, "IN"),
    ("Chartered Accountant", "CA", 6, 4, "IN"), ("Company Secretary", "CS", 6, 3, "IN"), ("Cost and Management Accountant", "CMA", 6, 3, "IN"),
    ("Bachelor of Engineering / Technology (dual degree)", "B.Tech + M.Tech", 7, 5, "IN"),
    ("Associate Degree", "Associate", 5, 2, None), ("Bachelor of Arts", "BA", 6, 3, None), ("Bachelor of Science", "BS", 6, 4, None),
    ("Bachelor of Engineering", "BEng", 6, 3, None), ("Master of Engineering", "MEng", 7, 4, None), ("Master of Science", "MSc", 7, 1, None),
    ("Master of Arts", "MA", 7, 1, None), ("Master of Business Administration", "MBA", 7, 2, None), ("Master of Philosophy", "MPhil", 7, 2, None),
    ("Juris Doctor", "JD", 7, 3, "US"), ("Doctor of Medicine", "MD", 7, 4, "US"), ("Doctor of Philosophy", "PhD", 8, 4, None),
    ("Doctor of Philosophy (Oxford)", "DPhil", 8, 3, "GB"),
]


def all_fields() -> list[dict]:
    rows = [{"code": c, "level": "broad", "parent_code": None, "name": n} for c, n in BROAD.items()]
    rows += [{"code": c, "level": "narrow", "parent_code": c[:2], "name": n} for c, n in NARROW.items()]
    rows += [{"code": c, "level": "detailed", "parent_code": c[:3], "name": n} for c, n in DETAILED.items()]
    return rows


def aishe_degrees() -> list[dict]:
    """The 201 AISHE programmes as degrees: name, abbreviation, ISCED level."""
    import csv
    import gzip
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "data" / "campus" / "aishe_programmes.csv"
    if not path.exists():
        return []
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        return [{"name": r["name"], "abbreviation": r["abbreviation"], "isced_level": int(r["isced_level"]), "aishe_id": r["aishe_id"], "country_code": "IN"} for r in csv.DictReader(f)]

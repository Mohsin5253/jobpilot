"""Drive rounds for every field, as data. A drive picks any of these; each field gets sensible defaults, and a coding
test only appears where the role needs one (software and data roles), never as an assumption."""

ROUND_TYPES: dict[str, dict] = {
    "aptitude": {"label": "Aptitude test", "prep": ["Quant, logical reasoning and verbal: 30 minutes a day", "One timed mock test before the drive"]},
    "written_test": {"label": "Written test", "prep": ["Revise the syllabus areas the circular names", "Practise answering in the time given"]},
    "group_discussion": {"label": "Group discussion", "prep": ["Read the news for current topics", "Open with a structure, listen, summarise at the end"]},
    "case_study": {"label": "Case study", "prep": ["Structure: problem, options, numbers, recommendation", "Practise two cases out loud with a friend"]},
    "subject_interview": {"label": "Technical / subject interview", "prep": ["Your core subjects, explained with examples", "Walk through every project or posting on your resume"]},
    "coding": {"label": "Coding test", "prep": ["Arrays, strings, hashing, trees, graphs, basic DP", "Two timed problems a day; state time and space complexity"]},
    "clinical_practical": {"label": "Clinical / practical exam", "prep": ["Rehearse the procedures in the syllabus step by step", "History-taking and case presentation, timed"]},
    "portfolio_review": {"label": "Portfolio review", "prep": ["Pick 3-4 projects; for each: brief, process, your decisions, outcome", "Be ready to critique your own work"]},
    "audition": {"label": "Audition / performance", "prep": ["Prepare the pieces the panel asks for, plus one of your choice", "Warm up; plan for nerves"]},
    "teaching_demo": {"label": "Teaching demonstration", "prep": ["Plan one lesson: objective, activity, check for understanding", "Time it; prepare for questions"]},
    "moot_or_drafting": {"label": "Drafting / moot exercise", "prep": ["Practise drafting a notice or brief in the time given", "Structure arguments; cite authorities accurately"]},
    "hr": {"label": "HR interview", "prep": ["Tell me about yourself (60 seconds)", "Why this organisation and role; relocation, bond and joining date"]},
    "medical": {"label": "Medical examination", "prep": ["Carry the documents the circular lists", "Ask what tests are included"]},
    "document_verification": {"label": "Document verification", "prep": ["Originals and copies of marksheets, ID, certificates", "Registration certificates where the field needs them"]},
}

# ISCED broad / narrow codes -> default rounds (the most specific code that matches wins).
FIELD_DEFAULTS: dict[str, list[str]] = {
    "06": ["aptitude", "coding", "subject_interview", "hr"],
    "07": ["aptitude", "subject_interview", "hr"],
    "091": ["written_test", "clinical_practical", "subject_interview", "hr", "medical"],
    "0913": ["written_test", "clinical_practical", "subject_interview", "document_verification"],
    "042": ["written_test", "moot_or_drafting", "subject_interview", "hr"],
    "04": ["aptitude", "group_discussion", "case_study", "hr"],
    "0411": ["written_test", "subject_interview", "hr"],
    "01": ["written_test", "teaching_demo", "subject_interview"],
    "021": ["portfolio_review", "subject_interview", "hr"],
    "0215": ["audition", "subject_interview"],
    "0212": ["portfolio_review", "case_study", "hr"],
    "08": ["written_test", "subject_interview", "hr"],
    "10": ["group_discussion", "subject_interview", "hr"],
    "05": ["written_test", "subject_interview", "hr"],
    "03": ["written_test", "group_discussion", "subject_interview", "hr"],
    "02": ["written_test", "subject_interview", "hr"],
}


def defaults_for(field_code: str | None, role_needs_code: bool = False) -> list[str]:
    code = field_code or ""
    best = next((FIELD_DEFAULTS[k] for k in sorted(FIELD_DEFAULTS, key=len, reverse=True) if code.startswith(k)), ["aptitude", "subject_interview", "hr"])
    rounds = list(best)
    if role_needs_code and "coding" not in rounds:
        rounds.insert(1, "coding")
    if not role_needs_code and code[:2] != "06" and "coding" in rounds:
        rounds.remove("coding")
    return rounds

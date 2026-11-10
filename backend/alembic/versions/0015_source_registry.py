"""India sources (F8): a source registry with per-source ToS notes and rate limits; inbound alert tokens

Revision ID: 9d4b6a2e5c18
Revises: 7c2f9e4b1a63
Create Date: 2026-11-10 21:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '9d4b6a2e5c18'
down_revision: Union[str, Sequence[str], None] = '7c2f9e4b1a63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SOURCES = [
    ("greenhouse", "ats_api", "https://boards-api.greenhouse.io/v1/boards/", "Public Job Board API, documented for embedding a company's own openings.", 30, True),
    ("lever", "ats_api", "https://api.lever.co/v0/postings/", "Public Postings API, documented for displaying a company's openings.", 30, True),
    ("ashby", "ats_api", "https://api.ashbyhq.com/posting-api/job-board/", "Public Job Postings API for a company's job board.", 30, True),
    ("career_page", "career_page", "", "Company careers pages: reads only schema.org JobPosting JSON-LD published for search engines; obeys robots.txt; at most 1 request per minute per domain; cached.", 1, True),
    ("github_listings", "github_repo", "https://raw.githubusercontent.com/SimplifyJobs/", "Community-maintained internship lists, public JSON on GitHub; credited with links back.", 1, True),
    ("themuse", "public_api", "https://www.themuse.com/api/public/jobs", "Public API; attribution required (links back).", 4, True),
    ("remotive", "public_api", "https://remotive.com/api/remote-jobs", "Public API; asks for low volume, so fetched every 6 hours, with links back.", 1, True),
    ("jobicy", "public_api", "https://jobicy.com/api/v2/remote-jobs", "Public API with attribution.", 1, True),
    ("adzuna", "licensed_api", "https://api.adzuna.com/v1/api/jobs/", "Developer API key; quota shared across the service.", 1, True),
    ("jsearch", "licensed_api", "https://jsearch.p.rapidapi.com/search", "Licensed API over the Google for Jobs index; we never contact the underlying boards.", 1, True),
    ("gov_portal", "deep_link", "https://pminternship.mca.gov.in", "Government portals are linked, never fetched.", 0, True),
    ("email_alert", "user_forwarded", "", "Alerts the student subscribed to and forwards to us; we keep the links, never open the boards.", 0, True),
    ("user_link", "user_pasted", "", "Links the student pastes; job-board links are kept as links, never fetched.", 0, True),
    ("linkedin", "blocked", "https://www.linkedin.com", "Never automated, scraped or logged into (ToS).", 0, False),
    ("internshala", "blocked", "https://internshala.com", "Never automated, scraped or logged into; only alert links the student forwards.", 0, False),
    ("naukri", "blocked", "https://www.naukri.com", "Never automated, scraped or logged into; only alert links the student forwards.", 0, False),
    ("unstop", "blocked", "https://unstop.com", "Never automated, scraped or logged into; only alert links the student forwards.", 0, False),
    ("indeed", "blocked", "https://www.indeed.com", "Never automated or scraped (ToS).", 0, False),
    ("glassdoor", "blocked", "https://www.glassdoor.co.in", "Never automated or scraped (ToS).", 0, False),
    ("wellfound", "blocked", "https://wellfound.com", "Never automated or scraped (ToS).", 0, False),
]


def upgrade() -> None:
    t = op.create_table(
        'sources',
        sa.Column('id', sa.String(length=40), primary_key=True),
        sa.Column('kind', sa.String(length=30), nullable=False),
        sa.Column('base_url', sa.String(length=300), server_default='', nullable=False),
        sa.Column('tos_notes', sa.Text(), server_default='', nullable=False),
        sa.Column('rate_limit_per_min', sa.Integer(), server_default='1', nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default='true', nullable=False),
    )
    op.bulk_insert(t, [dict(id=i, kind=k, base_url=u, tos_notes=n, rate_limit_per_min=r, enabled=e) for i, k, u, n, r, e in SOURCES])
    op.add_column('users', sa.Column('inbound_token', sa.String(length=24), nullable=True, unique=True))


def downgrade() -> None:
    op.drop_column('users', 'inbound_token')
    op.drop_table('sources')

# hexnut-blog-tool

**Nederlandse samenvatting:**  
Python tool om technische artikelen in Markdown (met plaatjes, Mermaid diagrammen, cross-references en referenties) vanuit een git-repo voor te bereiden met behulp van AI/LLM (Grok/xAI eerst) en te publiceren naar hexnut.net via de Blogger API v3.  
Git is de bron van waarheid. De tool ondersteunt NL/EN als aparte posts, herschrijft images naar GitHub raw URLs, rendert Mermaid en houdt stijl consistent.

## Wat dit doet
- Git-backed Markdown als enige bron
- LLM-assist voor schrijven, vertalen (NL/EN), referenties aanvullen en cross-ref suggesties
- Build: MD → HTML met mermaid-cli, GitHub raw images, automatische References sectie, cross-refs
- Publish: Blogger API (insert/patch, labels/tags, draft/publish)
- Separate EN + NL posts met links naar elkaar
- Post ID write-back in frontmatter voor updates

## Project layout
```
hexnut-blog-tool/
├── content/
│   ├── en/projects/
│   └── nl/projecten/
├── assets/images/
├── templates/
├── scripts/                 # Python code (kleine modules)
├── config/default.yaml
├── .env.example
├── requirements.txt
├── README.md
└── .gitignore
```

## Installatie & setup
```bash
cd /home/oetelaar/hexnut-blog-tool
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Mermaid CLI (vereist voor diagrammen)
npm install -g @mermaid-js/mermaid-cli
# of: npx @mermaid-js/mermaid-cli --help

cp .env.example .env
# vul .env in (blog URL, github user/repo, XAI_API_KEY)

# Voor echte Blogger writes heb je ook een OAuth client nodig:
# 1. Ga naar https://console.cloud.google.com/apis/credentials
# 2. Maak "OAuth 2.0 Client ID" (Desktop app)
# 3. Download als client_secrets.json in deze map (nooit committen)
```

## Eerste OAuth setup (eenmalig)
```bash
python -m scripts auth
# Opent browser voor Google OAuth (Blogger scope). Token wordt lokaal gecached.
```

## Basis workflow
```bash
# 1. Schrijf of laat AI helpen
python -m scripts prepare content/en/projects/my-project.md

# 2. Bouw (valideer + render)
python -m scripts build

# 3. Publiceer (EN en/of NL)
python -m scripts publish --lang en --draft
python -m scripts publish --lang nl

# Check cross-refs, images, etc.
python -m scripts check
```

## Bidirectional workflow (list / fetch / offline edit / update with same ID)

Doel: bestaande posts ophalen, offline bewerken (met LLM + build pipeline), terugplaatsen met **exact dezelfde ID** (stats, comments, URLs blijven behouden).

```bash
# 1. Ontdek bestaande posts
python -m scripts list --max 10
python -m scripts list --status draft --json
# or sort by last update:
# python -m scripts list --order-by UPDATED --max 5
# Kopieer altijd het volledige post-ID uit de eerste kolom.

# 2. Download een post (wordt lokale .md met rijke frontmatter incl. blogger_post_id)
python -m scripts fetch 1234567890123456789 --lang en
# or forceer locatie:
# python -m scripts fetch 1234567890123456789 -o content/en/projects/my-post.md
# for drafts or status: --view ADMIN (may give 404 if no access)

# 3. Offline bewerken
python -m scripts prepare content/en/projects/... .md
# - pas images aan (zet in assets/images/, urls worden bij build herschreven)
# - voeg Mermaid toe, update referenties, cross-refs
# - edit velden in frontmatter: title, labels, published, etc.

python -m scripts build

# 4. Terugplaatsen (update op dezelfde ID)
python -m scripts publish --path content/en/.../xxx.md --dry-run
python -m scripts publish --path content/en/.../xxx.md --draft
```

## Kleine terminal-interface

Voor de normale live-posts is er een kleine interactieve menu-flow:

```bash
export EDITOR=nano   # of vim/code --wait
python -m scripts menu
```

Kies een nummer, daarna `f` (download), `e` (download + edit) of `u`
(download + edit + bevestigde update). De menu-update gebruikt de opgeslagen
`blogger_post_id` en maakt dus nooit een nieuw post-object aan.

Belangrijk:
- `fetch` zet `blogger_post_id` + andere velden (published, status, labels).
- De lijst toont volledige Blogger IDs; afgekorte IDs geven een 404 bij fetch.
- `publish --path` detecteert het ID en doet altijd een update (nooit insert).
- Alle bewerkbare velden uit de post resource (behalve immutable zoals id/url/author) kunnen via frontmatter of content mee.

## Verwachte werking
- Artikelen met frontmatter (zie docs in code)
- Mermaid blokken worden naar SVG/PNG omgezet en als <img> ingevoegd
- Images: relatieve paden → https://raw.githubusercontent.com/.../main/...
- Na eerste publish of fetch: `blogger_post_id` + `blogger_published`, `labels`, etc. in frontmatter
- Updates (via --path of publish) gebruiken altijd dezelfde ID via patch → statistieken blijven intact
- Labels in Blogger = tags + keywords + lang:en|nl
- Roundtrip: fetch → MD (markdownify) → bewerk (LLM/build) → update (HTML terug)


## Waar in de code kijken
- `scripts/cli.py` — entrypoint + commando's (incl. list, fetch)
- `scripts/convert.py` — MD↔HTML (process_article + html_to_md + post_to_article)
- `scripts/blogger.py` — list, get, patch/update met rijke velden, ID-preserving logic
- `scripts/utils.py` — frontmatter + write_blogger_meta
- `scripts/llm.py` — Grok/xAI integratie + prompts
- `config/default.yaml` + `.env`

## Mermaid diagrammen
De tool rendert ieder ` ```mermaid ` blok naar een SVG voor Blogger. Blogger
voert namelijk geen Mermaid JavaScript uit. Gegenereerde SVGs staan onder
`assets/diagrams/<lang>/` en moeten worden gecommit zodat de GitHub raw URL in
de gepubliceerde post geldig blijft.

Installeer lokaal:
```bash
npm install --save-dev @mermaid-js/mermaid-cli
```

Ubuntu 24.04 kan Chromium user namespaces blokkeren. Daarom gebruikt dit project
`config/puppeteer.json` met `--no-sandbox` voor de lokale Mermaid renderer. Dit
is alleen geschikt voor een vertrouwde lokale buildomgeving. Een renderfout laat
`build` nu duidelijk falen; er wordt geen ongerenderd Mermaid blok gepubliceerd.

Controleer Mermaid afzonderlijk:
```bash
./node_modules/.bin/mmdc -i content/en/projects/example-technical-project.md \
  -o /tmp/mermaid-preview.md -p config/puppeteer.json
python -m scripts build
```

## Oefeningen voor studenten / uitbreiding
1. Voeg een nieuw artikel toe in content/en en content/nl met dezelfde slug.
2. Maak een Mermaid flowchart in een artikel en run `build`.
3. Verander image rewrite logica om een andere base URL te gebruiken.
4. Voeg een `--dry-run` flag toe aan publish.
5. Schrijf een pytest test voor convert.py die een simpele MD met mermaid verwerkt.
6. Pas de LLM prompt aan voor een specifiekere schrijfstijl.
7. Fetch een bestaand bericht, bewerk het lokaal en push terug met dezelfde ID.
8. Test of published of status via frontmatter meegaat bij update.

## Notes
- Houd modules klein en leesbaar (volg de geest van AGENTS.md).
- Nooit secrets committen.
- Eenmalige OAuth + .env voor keys.
- Alle content moet in git staan.
- Voor productie: overweeg later optionele GitHub Action (niet in v1).

## Verification commands
```bash
python -m scripts --help
python -m pytest -q
python -m scripts list --help
python -m scripts fetch --help
python -m scripts build --help
```
